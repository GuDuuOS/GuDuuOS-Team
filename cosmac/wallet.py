"""Token 钱包业务中枢（模块4 变现·Token 经济 P1）。

把「读后台配置（倍率/汇率/赠送/开关）+ 建钱包并赠送 + 用量前拦 + 按真实用量扣费 +
充值入账 + 管理员调整 + 查流水」串成一个 :class:`WalletStore`，供 bot / trading / HTTP 端点调用。

存储分层（CLAUDE.md §3）：
- **配置**（管理员后台调）→ 控制室 state event ``cosmac.token_config``（浏览器够不到 DB，同
  gating/quotas 套路，带 TTL 缓存）。
- **余额 + 流水**（派生/审计关系数据）→ 各实例自己的 cosmac DB（``cosmac_token_wallet`` /
  ``cosmac_token_ledger``，见 db/wallet_repo）。

计费模型（负责人拍板）：平台内置 AI 按**真实 LLM 用量 × 倍率**扣；用量是**后付**——回复前
只能前拦"有没有余额"，回复后按真实 token 结算。若结算额超过余额，则扣到 0 为止（末一次略微
补贴，避免把已发出的回复算失败），下一次因余额不足被前拦。

本期 token = **单用途消费积分（不可退现）**，把储值/资金归集的合规风险关在门外
（创作者分成/提现是后续单独评估的一步）。
"""

from __future__ import annotations

import logging
import math
import time
from typing import Any, Dict, List, Optional

from cosmac.config import TOKEN_CONFIG_EVENT_TYPE
from cosmac.db import session_scope, wallet_repo
from cosmac.db.models import TokenLedger

logger = logging.getLogger("cosmac.wallet")


# 免费日额度的计数项（走 cosmac_usage，period=day → 每天自动清零，天然满足"每天清零"）。
# 记的是"今日已用的免费 token 数"，剩余 = free_daily - 已用。
FREE_DAILY_METRIC = "token_daily_used"

# —— 后台配置的默认值（控制室没配或读失败时兜底）——
_DEFAULTS: Dict[str, Any] = {
    "enabled": False,       # 总开关默认关（见 config.py 说明：防一开就把存量用户全拦死）
    "markup": 1.0,          # 倍率，默认 1.0（不加价）；上线定价时后台调
    "tokens_per_yuan": 1000,  # 1 元 = 1000 token（充值/展示换算）
    "free_daily": 0,        # 每天赠送的免费 token（每天清零、不累积；负责人定的免费层模型）
    "free_grant": 0,        # 新钱包一次性欢迎赠送，默认 0（与每日免费额度是两回事）
    "min_balance": 1,       # 钱包余额低于此且无免费额度时，拦截并提示充值
    "platform_fee_pct": 10,  # 创作者商城平台抽成百分比（负责人定稿 10%；其余归创作者）
    # 创作者认证费（分，P3 类公众号认证；默认 300 元）。拒绝不退、可免费重提（定稿）。
    "creator_cert_fee_cents": 30000,
}


def _as_float(v: Any, default: float) -> float:
    try:
        f = float(v)
        return f if f >= 0 else default
    except (TypeError, ValueError):
        return default


def _as_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _parse_packages(raw: Any) -> List[Dict[str, Any]]:
    """校验充值包列表（管理员后台写进 cosmac.token_config 的 packages，外部可写、不可信）。

    只收：slug 非空且不重复、tokens 为正整数、prices 至少一项（货币小写 → 正整数分）。
    形如 [{"slug":"t100","name":"入门包","tokens":100000,"prices":{"cny":990}}]。
    """
    out: List[Dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    seen: set = set()
    for p in raw:
        if not isinstance(p, dict):
            continue
        slug = str(p.get("slug") or "").strip()
        if not slug or slug in seen:
            continue
        tokens = _as_int(p.get("tokens"), 0)
        if tokens <= 0:
            continue
        prices: Dict[str, int] = {}
        rp = p.get("prices")
        if isinstance(rp, dict):
            for cur, cents in rp.items():
                if not isinstance(cur, str):
                    continue
                c = _as_int(cents, 0)
                if c > 0:
                    prices[cur.strip().lower()] = c
        if not prices:
            continue  # 没有任何有效定价的包不可买，丢弃
        seen.add(slug)
        out.append({
            "slug": slug,
            "name": str(p.get("name") or slug),
            "tokens": tokens,
            "prices": prices,
            "enabled": bool(p.get("enabled", True)),
        })
    return out


def parse_token_config(ev: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """把控制室 cosmac.token_config 事件解析成规整的配置字典，缺的用默认补齐。"""
    raw = ev if isinstance(ev, dict) else {}
    return {
        "enabled": bool(raw.get("enabled", _DEFAULTS["enabled"])),
        "markup": _as_float(raw.get("markup"), _DEFAULTS["markup"]),
        "tokens_per_yuan": max(1, _as_int(raw.get("tokens_per_yuan"), _DEFAULTS["tokens_per_yuan"])),
        "free_daily": max(0, _as_int(raw.get("free_daily"), _DEFAULTS["free_daily"])),
        "free_grant": max(0, _as_int(raw.get("free_grant"), _DEFAULTS["free_grant"])),
        "min_balance": max(0, _as_int(raw.get("min_balance"), _DEFAULTS["min_balance"])),
        # 平台抽成百分比（P2 创作者商城）：0~100，脏值回默认 10
        "platform_fee_pct": min(100, max(0, _as_int(
            raw.get("platform_fee_pct"), _DEFAULTS["platform_fee_pct"]))),
        # 创作者认证费（分；0=免费认证）
        "creator_cert_fee_cents": max(0, _as_int(
            raw.get("creator_cert_fee_cents"), _DEFAULTS["creator_cert_fee_cents"])),
        # 充值包（1c）：管理员在后台配的"多少钱买多少 token"套餐，下单时按 slug 取快照。
        "packages": _parse_packages(raw.get("packages")),
    }


class WalletStore:
    """Token 钱包业务中枢。读控制室配置（TTL 缓存）+ 操作 cosmac DB 钱包/流水。

    构造参数：
        client:              读控制室 ``cosmac.token_config`` 用（resolve_alias/get_state_event）。
        control_room_alias:  控制室别名。
        ttl:                 配置缓存秒数（同 QuotaStore/GatingStore）。
    """

    def __init__(self, client: Any, control_room_alias: str, ttl: float = 20.0):
        self._client = client
        self._alias = control_room_alias
        self._ttl = ttl
        self._cache: Optional[Dict[str, Any]] = None
        self._cache_ts: float = float("-inf")

    # —— 配置 ——

    def config(self) -> Dict[str, Any]:
        """读 Token 经济配置（带 TTL 缓存，失败回退默认，绝不抛）。"""
        now = time.monotonic()
        if self._cache is not None and (now - self._cache_ts) < self._ttl:
            return self._cache
        try:
            room = self._client.resolve_alias(self._alias)
            ev = self._client.get_state_event(room, TOKEN_CONFIG_EVENT_TYPE) if room else None
            cfg = parse_token_config(ev)
        except Exception as e:
            logger.debug("读取 Token 配置失败，用默认：%s", e)
            cfg = parse_token_config(None)
        self._cache = cfg
        self._cache_ts = now
        return cfg

    def enabled(self) -> bool:
        """Token 经济总开关是否打开。关=不计量、不拦截（现网默认关）。"""
        return bool(self.config().get("enabled"))

    # —— 余额 / 建钱包 ——

    def balance(self, user_id: str) -> int:
        """读某用户余额（无钱包=0）。"""
        with session_scope() as s:
            return wallet_repo.get_balance(s, user_id)

    def ensure_wallet(self, user_id: str) -> int:
        """确保钱包存在；**首次创建**时若配置了 free_grant 就赠送。返回当前余额。

        赠送只在总开关打开时发放（关着时不应产生任何 token 变动）。幂等：钱包已存在则
        直接返回余额、不重复赠送。
        """
        cfg = self.config()
        grant = int(cfg.get("free_grant") or 0)
        # 显式查一次原始行：get_balance 无钱包也返回 0，区分不了"没钱包"和"余额恰为 0"，
        # 而"是否首次创建"决定要不要发赠送，必须精确判断。
        from sqlalchemy import select

        from cosmac.db.models import TokenWallet
        with session_scope() as s:
            row = s.execute(
                select(TokenWallet).where(TokenWallet.user_id == user_id)
            ).scalar_one_or_none()
            if row is not None:
                return int(row.balance)
            # 新建钱包（首次）
            wallet_repo.get_or_create(s, user_id)
            if cfg.get("enabled") and grant > 0:
                return wallet_repo.credit(
                    s, user_id, grant, reason="grant", ref="signup",
                    note="新用户赠送", meta={"kind": "free_grant"},
                )
            return 0

    # —— 免费日额度（每天清零，走 cosmac_usage 计数）——

    def free_daily_status(self, user_id: str) -> Dict[str, int]:
        """今日免费额度：{total, used, remaining}。total=后台配的 free_daily。"""
        from cosmac.db import quota_repo

        total = int(self.config().get("free_daily") or 0)
        pkey = quota_repo.period_key("day")
        with session_scope() as s:
            used = quota_repo.get_count(s, user_id, FREE_DAILY_METRIC, pkey)
        used = min(used, total)  # 展示不越界（config 调小后已用可能暂超）
        return {"total": total, "used": used, "remaining": max(0, total - used)}

    # —— 用量前拦（后付计费只能前拦"有没有额度/余额"）——

    def precheck(self, user_id: str) -> Optional[str]:
        """发起 AI 前的额度前拦。返回拦截提示串或 None（放行）。

        总开关关时恒放行。开时：**今日免费额度有剩** 或 **钱包余额 ≥ min_balance** 任一满足即放行；
        两者都空才拦。调用方（bot）负责"管理员豁免"——与 quota/gating 一致，管理员不进这里。
        """
        cfg = self.config()
        if not cfg.get("enabled"):
            return None
        self.ensure_wallet(user_id)  # 顺带给新用户发一次性欢迎赠送（若配了）
        if self.free_daily_status(user_id)["remaining"] > 0:
            return None  # 还有今日免费额度
        bal = self.balance(user_id)
        if bal >= int(cfg.get("min_balance") or 1):
            return None  # 钱包有余额
        return (
            f"你今天的免费 AI 额度已用完，token 余额也不足（当前 {bal}）。"
            "请充值后再用～"
        )

    # —— 按真实用量扣费（回复后结算）——

    def charge_usage(
        self,
        user_id: str,
        *,
        real_tokens: int,
        model: str = "",
        room_id: str = "",
        reason: str = "ai_usage",
        note: str = "AI 对话",
    ) -> Dict[str, Any]:
        """按真实 LLM 用量扣费：应扣 = ceil(real_tokens × markup)，**先扣今日免费额度、再扣钱包余额**。

        总开关关时不扣（charged=0）。开时两级扣减：
          1) 今日免费额度剩余里扣 from_free（走 cosmac_usage 计数，每天清零）；
          2) 剩下的从钱包余额扣 from_wallet（不足则扣到 0 为止，末次略补贴、不失败已发出的回复）。
        钱包流水只记**动了余额**的那部分（from_wallet>0 才记一行）；纯免费额度消费不进钱包流水
        （余额没变），由"今日免费额度"单独展示。返回明细字典。
        """
        from cosmac.db import quota_repo

        cfg = self.config()
        markup = float(cfg.get("markup") or 1.0)
        rt = max(0, int(real_tokens or 0))
        if not cfg.get("enabled"):
            return {"charged": 0, "from_free": 0, "from_wallet": 0, "real_tokens": rt,
                    "markup": markup, "balance": None, "capped": False}
        cost = int(math.ceil(rt * markup)) if rt > 0 else 0
        if cost <= 0:
            return {"charged": 0, "from_free": 0, "from_wallet": 0, "real_tokens": rt,
                    "markup": markup, "balance": self.balance(user_id), "capped": False}

        free_total = int(cfg.get("free_daily") or 0)
        pkey = quota_repo.period_key("day")
        with session_scope() as s:
            # 1) 先吃今日免费额度
            used_today = quota_repo.get_count(s, user_id, FREE_DAILY_METRIC, pkey)
            free_remaining = max(0, free_total - used_today)
            from_free = min(cost, free_remaining)
            if from_free > 0:
                quota_repo.incr(s, user_id, FREE_DAILY_METRIC, pkey, by=from_free)
            # 2) 剩余从钱包扣
            remainder = cost - from_free
            from_wallet = 0
            capped = False
            new_bal = wallet_repo.get_balance(s, user_id)
            if remainder > 0:
                charge = min(remainder, new_bal)  # 扣到 0 为止
                capped = remainder > new_bal
                if charge > 0:
                    bal2 = wallet_repo.try_debit(
                        s, user_id, charge, reason=reason, ref=room_id, note=note,
                        meta={"real_tokens": rt, "markup": markup, "model": model,
                              "cost": cost, "from_free": from_free,
                              "from_wallet": charge, "capped": capped},
                    )
                    if bal2 is None:  # 并发扣穿兜底：本次不扣，不阻断
                        logger.warning("扣费竞态：user=%s charge=%s 未扣成", user_id, charge)
                    else:
                        from_wallet = charge
                        new_bal = bal2
        return {"charged": from_free + from_wallet, "from_free": from_free,
                "from_wallet": from_wallet, "real_tokens": rt, "markup": markup,
                "balance": new_bal, "capped": capped}

    # —— 创作者商城按次扣费 + 分成（P2）——

    def agent_use_precheck(self, buyer: str, price_tokens: int) -> Optional[str]:
        """使用创作者 Agent 前的**硬前拦**：余额 < 固定价则拦（返回提示串），够则放行 None。

        与平台 AI 的"后付扣到 0 为止"不同：固定价/次是**先看得起再用**的预付语义——
        用户对"这一条要花多少"有明确预期，余额不够就明确拒绝，不产生欠账。
        总开关关 / 价格 0 恒放行。免费日额度**不抵扣**创作者 Agent（那是平台送的
        平台用量；创作者的钱得真金白银从钱包出，否则分成没有来源）。
        """
        price = max(0, int(price_tokens or 0))
        if price <= 0 or not self.config().get("enabled"):
            return None
        self.ensure_wallet(buyer)
        bal = self.balance(buyer)
        if bal < price:
            return (
                f"使用该创作者 Agent 每次需 {price} token，你的余额不足（当前 {bal}）。"
                "请先充值～"
            )
        return None

    def charge_agent_use(
        self,
        buyer: str,
        listing_id: int,
        *,
        room_id: str = "",
    ) -> Dict[str, Any]:
        """按次扣创作者 Agent 使用费并分账：扣用户 gross → 平台抽成 fee →
        创作者净得 net 充进其钱包 → 记 CreatorEarning 流水（同一事务）。

        返回 {charged, fee, net, creator, balance}；不该扣/扣不动时 charged=0（调用方
        无须区分原因，回复照发——前拦已把"余额不足"挡在生成之前，这里失败只可能是
        竞态或配置变化，不值得为它失败一条已生成的回复）。
        买家=创作者本人时不扣（自己用自己的免费，也不产生自我分成刷量）。
        """
        from cosmac.db import listing_repo

        cfg = self.config()
        out: Dict[str, Any] = {"charged": 0, "fee": 0, "net": 0, "creator": "", "balance": None}
        if not cfg.get("enabled"):
            return out
        try:
            with session_scope() as s:
                listing = listing_repo.get_listing(s, listing_id)
                if listing is None or listing.status != "on":
                    return out
                price = max(0, int(listing.price_tokens or 0))
                out["creator"] = listing.creator
                if price <= 0 or buyer == listing.creator:
                    return out
                # 1) 扣用户（原子守卫；不足=不扣不分成，回复不受影响）
                new_bal = wallet_repo.try_debit(
                    s, buyer, price, reason="agent_use",
                    ref=f"listing:{listing.id}", note=f"使用创作者 Agent「{listing.name}」",
                    meta={"listing_id": listing.id, "creator": listing.creator,
                          "agent_slug": listing.agent_slug},
                )
                if new_bal is None:
                    logger.info("按次扣费余额不足未扣：buyer=%s listing=%s", buyer, listing_id)
                    return out
                # 2) 分账：平台抽成向上取整（保护平台），创作者得其余
                fee_pct = int(cfg.get("platform_fee_pct") or 10)
                fee = int(math.ceil(price * fee_pct / 100.0))
                net = max(0, price - fee)
                if net > 0:
                    wallet_repo.credit(
                        s, listing.creator, net, reason="earning",
                        ref=f"listing:{listing.id}",
                        note=f"创作收益：{listing.name}",
                        meta={"listing_id": listing.id, "buyer": buyer,
                              "gross": price, "fee": fee},
                    )
                # 3) 收益账本 + listing 累计
                listing_repo.record_earning(
                    s, listing=listing, buyer=buyer, gross=price, fee=fee,
                    net=net, room_id=room_id,
                )
                out.update({"charged": price, "fee": fee, "net": net, "balance": new_bal})
        except Exception:
            logger.exception("按次扣费失败（不影响回复）：buyer=%s listing=%s", buyer, listing_id)
        return out

    def charge_skill_purchase(
        self, buyer: str, listing_id: int
    ) -> Dict[str, Any]:
        """Skill **一次性买断**：获取那一刻付清，之后永久可用（P4 定稿）。

        与 Agent 按次的关键差别：**扣不动就必须失败**（返回 ok=False + 提示），由调用方
        拒绝这次「获取」——买断是先付后得，不能像后付那样"扣到 0 为止"还把货给了。
        已买断过（listing_repo.has_purchased）/ 自己的 / 免费的 / 总开关关 → 直接放行不扣。
        返回 {ok, charged, fee, net, error}。
        """
        from cosmac.db import listing_repo

        cfg = self.config()
        out: Dict[str, Any] = {"ok": True, "charged": 0, "fee": 0, "net": 0, "error": ""}
        if not cfg.get("enabled"):
            return out
        try:
            with session_scope() as s:
                listing = listing_repo.get_listing(s, listing_id)
                if listing is None or listing.status != "on":
                    out.update(ok=False, error="该技能已下架")
                    return out
                price = max(0, int(listing.price_tokens or 0))
                # 免费 / 自己的 / 已买断过 → 放行不扣
                if (price <= 0 or buyer == listing.creator
                        or listing_repo.has_purchased(s, buyer, listing.id)):
                    return out
                self.ensure_wallet(buyer)
                new_bal = wallet_repo.try_debit(
                    s, buyer, price, reason="skill_buy",
                    ref=f"listing:{listing.id}", note=f"购买技能「{listing.name}」",
                    meta={"listing_id": listing.id, "creator": listing.creator,
                          "skill_slug": listing.agent_slug},
                )
                if new_bal is None:
                    bal = wallet_repo.get_balance(s, buyer)
                    out.update(
                        ok=False,
                        error=f"购买该技能需 {price} token，你的余额不足（当前 {bal}）。请先充值～",
                    )
                    return out
                fee_pct = int(cfg.get("platform_fee_pct") or 10)
                fee = int(math.ceil(price * fee_pct / 100.0))
                net = max(0, price - fee)
                if net > 0:
                    wallet_repo.credit(
                        s, listing.creator, net, reason="earning",
                        ref=f"listing:{listing.id}",
                        note=f"技能售出：{listing.name}",
                        meta={"listing_id": listing.id, "buyer": buyer,
                              "gross": price, "fee": fee, "kind": "skill"},
                    )
                listing_repo.record_earning(
                    s, listing=listing, buyer=buyer, gross=price, fee=fee, net=net,
                )
                out.update(charged=price, fee=fee, net=net)
        except Exception:
            logger.exception("技能买断扣费失败：buyer=%s listing=%s", buyer, listing_id)
            out.update(ok=False, error="购买失败，请稍后重试")
        return out

    # —— 充值入账（trading 支付成功后调）——

    def recharge(
        self, user_id: str, tokens: int, *, order_no: str = "", note: str = "充值"
    ) -> int:
        """充值入账：给钱包加 tokens，记 recharge 流水，返回新余额。tokens 必须 > 0。"""
        with session_scope() as s:
            return wallet_repo.credit(
                s, user_id, int(tokens), reason="recharge", ref=order_no,
                note=note, meta={"order_no": order_no},
            )

    # —— 管理员手动调整 ——

    def adjust(self, user_id: str, delta: int, *, note: str = "", operator: str = "") -> Optional[int]:
        """管理员手动加/减 token（可正可负）。返回新余额；负向且余额不足返回 None。"""
        with session_scope() as s:
            return wallet_repo.adjust(
                s, user_id, int(delta), note=note, meta={"operator": operator},
            )

    # —— 查流水 ——

    def ledger(self, user_id: str, *, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """取某用户流水（新→旧），转成 dict 列表便于 HTTP 下发。"""
        with session_scope() as s:
            rows: List[TokenLedger] = wallet_repo.list_ledger(
                s, user_id, limit=limit, offset=offset
            )
            return [
                {
                    "id": r.id,
                    "delta": int(r.delta),
                    "reason": r.reason,
                    "ref": r.ref,
                    "balance_after": int(r.balance_after),
                    "note": r.note,
                    "meta": r.meta or {},
                    "created_at": r.created_at.isoformat() if r.created_at else "",
                }
                for r in rows
            ]

    # —— 充值包（1c）——

    def packages(self) -> List[Dict[str, Any]]:
        """启用中的充值包列表（已强校验）。下单/前端展示用。"""
        return [p for p in self.config().get("packages", []) if p.get("enabled", True)]

    def find_package(self, slug: str) -> Optional[Dict[str, Any]]:
        """按 slug 找启用中的充值包；找不到返回 None。"""
        for p in self.packages():
            if p.get("slug") == slug:
                return p
        return None

    # —— 展示辅助 ——

    def yuan_to_tokens(self, yuan: float) -> int:
        """人民币元 → token（按后台汇率）。充值套餐/前端展示用。"""
        return int(round(float(yuan) * int(self.config().get("tokens_per_yuan") or 1000)))
