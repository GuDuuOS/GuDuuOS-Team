"""订单生命周期编排（模块4 P1 核心）。

把"下单 → 拿支付方式 → 平台回调 → 开/续会员"串起来，是交易系统的业务中枢。
- 套餐从控制室 ``cosmac.plans`` 读（plans.py 解析）。
- 订单进 DB（order_repo）。
- 开会员调 :class:`cosmac.members.MembersStore` 的 grant（写 ``cosmac.member`` state event）。
- 支付渠道走可插拔的 :class:`PaymentProvider`。

**幂等是命门**：支付平台 webhook 会重复回调。``order_repo.mark_paid`` 的原子 CAS
(created→paid) 是"恰好一次"的闸——只有第一次回调真正开/续会员，重复回调直接幂等返回，
绝不重复续期。开会员失败则回滚订单待重试，避免"收了钱没开会员"。
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
from typing import Any, Dict, List, Optional

from cosmac.config import PLANS_EVENT_TYPE
from cosmac.db import order_repo, session_scope
from cosmac.members import MembersStore, active_tier, tier_label, tier_level
from cosmac.trading.base import PaymentProvider
from cosmac.trading.manual import ManualProvider
from cosmac.trading.plans import Plan, find_plan, parse_plans

logger = logging.getLogger("cosmac.trading")

_DAY_SECONDS = 86400


class OrderError(Exception):
    """下单/支付过程中的业务错误（套餐不存在、货币不支持、渠道未知等）。"""


def build_default_providers() -> Dict[str, PaymentProvider]:
    """构造默认支付渠道表。P1 只有 manual；真实渠道(stripe 等) adapter 后续分期注册进来。"""
    return {"manual": ManualProvider()}


def _gen_order_no() -> str:
    """生成对外订单号：时间前缀（可读、可排序）+ 随机尾（防猜）。唯一性最终由 DB 唯一约束保证。"""
    return f"{int(time.time())}-{secrets.token_hex(5)}"


class OrderService:
    """交易系统业务中枢。

    构造参数：
        members:  会员写入口（grant/get_record）。
        client:   读控制室 ``cosmac.plans`` 用（需 resolve_alias/get_state_event）。
        control_room_alias: 控制室别名。
        providers: 渠道名→PaymentProvider；不传用 :func:`build_default_providers`。
    """

    def __init__(
        self,
        members: MembersStore,
        client: Any,
        control_room_alias: str,
        providers: Optional[Dict[str, PaymentProvider]] = None,
        wallet: Any = None,
    ):
        self._members = members
        self._client = client
        self._alias = control_room_alias
        self._providers = providers or build_default_providers()
        # Token 经济（1c）：token 充值单支付成功后经它入账（WalletStore.recharge）。
        # 不传则 token 单不可下（create_token_order 会拒），会员链路不受影响。
        self._wallet = wallet
        # 按 user_id 的串行锁：同一用户的多笔订单回调并发时，避免各自从相同旧到期日顺延
        # 导致续期叠加错误（用户付两次却只续一次 / grant 互相覆盖）。
        self._user_locks: Dict[str, threading.Lock] = {}
        self._user_locks_guard = threading.Lock()

    def _user_lock(self, user_id: str) -> threading.Lock:
        """取（或惰性建）某 user 的串行锁。单实例进程内有效——多实例 fencing 是已知边界、本期不做。"""
        with self._user_locks_guard:
            lk = self._user_locks.get(user_id)
            if lk is None:
                lk = threading.Lock()
                self._user_locks[user_id] = lk
            return lk

    def get_provider(self, name: str) -> Optional[PaymentProvider]:
        """按名取支付渠道 adapter；未注册返回 None。"""
        return self._providers.get(name)

    # —— 套餐 ——

    def list_plans(self) -> List[Plan]:
        """读控制室套餐列表（只读，失败返回空，不抛）。"""
        try:
            room = self._client.resolve_alias(self._alias)
            if not room:
                return []
            return parse_plans(self._client.get_state_event(room, PLANS_EVENT_TYPE))
        except Exception as e:
            logger.warning("读取套餐失败：%s", e)
            return []

    # —— 下单 ——

    def create_order(
        self,
        *,
        user_id: str,
        plan_slug: str,
        currency: str,
        provider: str = "manual",
        return_url: str = "",
    ) -> Dict[str, Any]:
        """下单：校验套餐/货币/渠道 → 建 DB 订单(created) → 让渠道生成支付方式。

        返回 {order_no, amount_cents, currency, tier, period_days, checkout}。
        校验失败抛 :class:`OrderError`（调用方转成对用户的提示）。
        """
        if not user_id.startswith("@") or ":" not in user_id:
            raise OrderError("非法用户")
        plan = find_plan(self.list_plans(), plan_slug)
        if plan is None:
            raise OrderError("套餐不存在或已下架")
        cur = (currency or "").lower()
        cents = plan.price_cents(cur)
        if cents is None:
            raise OrderError(f"该套餐不支持货币 {currency}")
        prov = self._providers.get(provider)
        if prov is None:
            raise OrderError(f"暂不支持的支付渠道 {provider}")

        # 降级保护（#2 资损修复）：当前正持**更高等级**会员时，不允许购买更低档套餐——否则
        # 支付成功会用低档 tier 覆盖高档、剩余高档天数一并清零。在下单入口就明确拦下（比支付
        # 后再拒绝体验好、也不用退款）。同档=续费、升级=买更高档，都放行。
        cur_tier = self._members.get_tier(user_id)
        if tier_level(cur_tier) > tier_level(plan.tier):
            raise OrderError(
                f"你当前是{tier_label(cur_tier)}，无需购买更低档的「{plan.name}」"
            )

        order_no = _gen_order_no()
        with session_scope() as s:
            order_repo.create_order(
                s, order_no=order_no, user_id=user_id, plan_slug=plan.slug,
                tier=plan.tier, period_days=plan.period_days, amount_cents=cents,
                currency=cur, provider=provider,
            )
        checkout = prov.create_checkout(
            order_no=order_no, amount_cents=cents, currency=cur,
            title=plan.name, return_url=return_url,
        )
        return {
            "order_no": order_no, "amount_cents": cents, "currency": cur,
            "tier": plan.tier, "period_days": plan.period_days, "checkout": checkout,
        }

    # —— token 充值下单（1c）——

    def create_token_order(
        self,
        *,
        user_id: str,
        package_slug: str,
        currency: str,
        provider: str = "manual",
        return_url: str = "",
    ) -> Dict[str, Any]:
        """token 充值下单：校验充值包/货币/渠道 → 建 DB 订单(kind=token) → 生成支付方式。

        与会员下单同骨架（同一渠道表、同一回调端点），差别只在履约：支付成功后不开会员、
        而是给钱包充 tokens（见 on_payment_success 的 kind 分流）。校验失败抛 OrderError。
        """
        if not user_id.startswith("@") or ":" not in user_id:
            raise OrderError("非法用户")
        if self._wallet is None:
            raise OrderError("token 充值未开通")
        pkg = self._wallet.find_package(package_slug)
        if pkg is None:
            raise OrderError("充值包不存在或已下架")
        cur = (currency or "").lower()
        cents = (pkg.get("prices") or {}).get(cur)
        if not cents:
            raise OrderError(f"该充值包不支持货币 {currency}")
        prov = self._providers.get(provider)
        if prov is None:
            raise OrderError(f"暂不支持的支付渠道 {provider}")

        order_no = _gen_order_no()
        tokens = int(pkg.get("tokens") or 0)
        with session_scope() as s:
            order_repo.create_order(
                s, order_no=order_no, user_id=user_id, plan_slug=pkg["slug"],
                tier="", period_days=0, amount_cents=int(cents), currency=cur,
                provider=provider, kind="token", tokens=tokens,
            )
        checkout = prov.create_checkout(
            order_no=order_no, amount_cents=int(cents), currency=cur,
            title=str(pkg.get("name") or pkg["slug"]), return_url=return_url,
        )
        return {
            "order_no": order_no, "amount_cents": int(cents), "currency": cur,
            "tokens": tokens, "package": pkg["slug"], "checkout": checkout,
        }

    def _fulfill_token_order(
        self, order_no: str, *, provider_ref: str, user_id: str, tokens: int
    ) -> Dict[str, Any]:
        """token 单履约：原子置 paid（恰好一次闸）→ 给钱包充值。

        与会员履约同幂等骨架：mark_paid 的 CAS 保证重复回调只充一次；充值失败回滚订单
        待平台重试（收了钱必须最终把 token 给到）。
        """
        with session_scope() as s:
            first = order_repo.mark_paid(
                s, order_no, provider_ref=provider_ref, granted_expires_ts=0,
            )
        if not first:
            return {"ok": True, "already": True, "order_no": order_no}
        try:
            if self._wallet is None:
                raise RuntimeError("wallet 未注入")
            new_bal = self._wallet.recharge(
                user_id, tokens, order_no=order_no,
                note=f"充值 {tokens} token",
            )
        except Exception:
            # 收了钱却没充上 → 回滚订单，让平台重试回调（与会员开通失败同口径）
            with session_scope() as s:
                order_repo.revert_to_created(s, order_no)
            logger.exception("订单 %s 已支付但 token 入账失败，已回滚待重试", order_no)
            raise OrderError("充值入账失败，请稍后重试")
        logger.info(
            "订单 %s 支付成功：%s 充值 %s token，余额 %s",
            order_no, user_id, tokens, new_bal,
        )
        return {
            "ok": True, "order_no": order_no, "user_id": user_id,
            "tokens": tokens, "balance": new_bal,
        }

    # —— 创作者认证费下单（P3 认证流程）——

    def create_cert_order(
        self, *, user_id: str, provider: str = "manual", return_url: str = "",
    ) -> Dict[str, Any]:
        """创作者认证费下单：金额从后台配置读（token_config.creator_cert_fee_cents，元→分已配好）。

        与会员/token 下单同骨架、同回调端点；支付成功后履约=把认证申请从「待付费」
        推进到「待审核」（见 on_payment_success 的 kind 分流）。货币固定 cny（认证费
        面向国内创作者；将来要多币种再扩）。
        """
        if not user_id.startswith("@") or ":" not in user_id:
            raise OrderError("非法用户")
        if self._wallet is None:
            raise OrderError("认证服务未开通")
        cents = int(self._wallet.config().get("creator_cert_fee_cents") or 0)
        if cents <= 0:
            raise OrderError("当前认证免费，无需支付")
        prov = self._providers.get(provider)
        if prov is None:
            raise OrderError(f"暂不支持的支付渠道 {provider}")
        order_no = _gen_order_no()
        with session_scope() as s:
            order_repo.create_order(
                s, order_no=order_no, user_id=user_id, plan_slug="creator-cert",
                tier="", period_days=0, amount_cents=cents, currency="cny",
                provider=provider, kind="creator_cert",
            )
        checkout = prov.create_checkout(
            order_no=order_no, amount_cents=cents, currency="cny",
            title="创作者认证费", return_url=return_url,
        )
        return {"order_no": order_no, "amount_cents": cents, "currency": "cny",
                "checkout": checkout}

    def _fulfill_cert_order(
        self, order_no: str, *, provider_ref: str, user_id: str
    ) -> Dict[str, Any]:
        """认证费履约：原子置 paid → 申请状态 待付费→待审核（幂等）。

        入账失败回滚订单待平台重试（收了钱必须把申请推进到待审）。
        """
        from cosmac.db import cert_repo

        with session_scope() as s:
            first = order_repo.mark_paid(
                s, order_no, provider_ref=provider_ref, granted_expires_ts=0,
            )
        if not first:
            return {"ok": True, "already": True, "order_no": order_no}
        try:
            with session_scope() as s:
                ok = cert_repo.mark_paid(s, user_id, order_no)
            if not ok:
                raise RuntimeError("没有找到该用户的认证申请")
        except Exception:
            with session_scope() as s:
                order_repo.revert_to_created(s, order_no)
            logger.exception("订单 %s 已支付但认证申请推进失败，已回滚待重试", order_no)
            raise OrderError("认证费入账失败，请稍后重试")
        logger.info("订单 %s 支付成功：%s 认证申请进入待审核", order_no, user_id)
        return {"ok": True, "order_no": order_no, "user_id": user_id, "cert": True}

    # —— 支付成功（平台回调归一化后调这里）——

    def on_payment_success(
        self, order_no: str, *, provider_ref: str = "",
        paid_amount_cents: Optional[int] = None, paid_currency: str = "",
        now_ts: Optional[int] = None,
    ) -> Dict[str, Any]:
        """支付成功：**幂等地**置订单 paid 并开/续会员。

        返回 {ok, order_no, ...}；``already=True`` 表示重复回调（已处理过、本次不重复开通）。
        - 金额校验：平台回传了实收金额(paid_amount_cents)就必须与下单金额一致，否则拒绝开通
          （防"少付/改币种拿全权益"——支付系统经典资损漏洞）。adapter 取不到金额时传 None 跳过。
        - 续费：若用户当前正持同档会员，从其**原到期日顺延**（不是从现在重新算），不亏天数。
        - 先原子置 paid（恰好一次闸）→ 再开会员；开会员失败回滚订单待重试。
        - 同一 user 的并发回调用 _user_lock 串行化，避免续期叠加错乱。
        """
        now = int(now_ts if now_ts is not None else time.time())
        with session_scope() as s:
            order = order_repo.get_by_order_no(s, order_no)
            if order is None:
                raise OrderError("订单不存在")
            if order.status == "paid":
                return {"ok": True, "already": True, "order_no": order_no}
            tier, period, user_id = order.tier, order.period_days, order.user_id
            order_amount = int(order.amount_cents or 0)
            order_currency = (order.currency or "").lower()
            # 订单种类（Token 经济 1c）：token 充值单走独立履约（充钱包），会员单走原有开通链。
            order_kind = str(getattr(order, "kind", "") or "member")
            order_tokens = int(getattr(order, "tokens", 0) or 0)

        # 金额/货币二次校验：平台回传了就强制比对，不符绝不开通（先于一切开通逻辑）。
        if paid_amount_cents is not None and int(paid_amount_cents) != order_amount:
            logger.error(
                "订单 %s 金额不符：下单 %s 实收 %s，拒绝开通",
                order_no, order_amount, paid_amount_cents,
            )
            raise OrderError("支付金额与订单不符")
        if paid_currency and paid_currency.lower() != order_currency:
            logger.error(
                "订单 %s 货币不符：下单 %s 实收 %s，拒绝开通",
                order_no, order_currency, paid_currency,
            )
            raise OrderError("支付货币与订单不符")

        # token 充值单：金额校验已过，直接充钱包（幂等靠 mark_paid CAS），不进会员逻辑。
        if order_kind == "token":
            return self._fulfill_token_order(
                order_no, provider_ref=provider_ref,
                user_id=user_id, tokens=order_tokens,
            )
        # 创作者认证费单（P3）：推进认证申请 待付费→待审核，不进会员逻辑。
        if order_kind == "creator_cert":
            return self._fulfill_cert_order(
                order_no, provider_ref=provider_ref, user_id=user_id,
            )

        # 同一用户串行：读旧到期日 + 算 new_exp + 置 paid + grant 整体不被另一笔回调插队。
        with self._user_lock(user_id):
            # 算到期：续费从原到期日顺延，否则从现在起算
            rec = self._members.get_record(user_id)
            # 降级保护（#2 防御）：下单后、支付前被管理员升到**更高等级**的极端竞态里，绝不能
            # 用本单的低档 tier 覆盖现有高档会员。此时保留现有高等级不动，仍幂等置 paid（钱已收），
            # 不再往下走 grant。create_order 已在正常路径拦了降级购买，这里兜住竞态。
            cur_active = active_tier(rec, now)
            if tier_level(cur_active) > tier_level(tier):
                with session_scope() as s:
                    first = order_repo.mark_paid(
                        s, order_no, provider_ref=provider_ref, granted_expires_ts=0,
                    )
                if not first:
                    return {"ok": True, "already": True, "order_no": order_no}
                logger.warning(
                    "订单 %s 目标等级 %s 低于用户当前 %s，保留高等级不降级",
                    order_no, tier, cur_active,
                )
                return {
                    "ok": True, "order_no": order_no, "user_id": user_id,
                    "tier": cur_active, "kept": True,
                }
            # 当前是否正持**同档**有效会员（到期的 active_tier 已回落免费，不算同档）。
            same_tier_active = bool(rec) and active_tier(rec, now) == tier
            # get_record 的 expires_ts 已过 _as_int，一定是 int；0 = 永久。
            cur_exp = int(rec.get("expires_ts") or 0) if rec else 0
            if same_tier_active and cur_exp <= 0:
                # 当前已是**永久**同档会员（管理员授予 expires_ts=0）：购买绝不能把"永久"
                # 缩水成"限期"（否则付了钱反而权益变小，#1 资损修复）。保持永久。
                new_exp = 0
            else:
                # 续费顺延：持同档且未到期 → 从原到期日往后顺延；否则从现在起算。
                base = cur_exp if (same_tier_active and cur_exp > now) else now
                new_exp = base + period * _DAY_SECONDS

            # 原子置 paid（恰好一次）——只有第一笔回调拿到 first=True
            with session_scope() as s:
                first = order_repo.mark_paid(
                    s, order_no, provider_ref=provider_ref, granted_expires_ts=new_exp,
                )
            if not first:
                return {"ok": True, "already": True, "order_no": order_no}

            # 开/续会员
            ok = self._members.grant(
                user_id, tier, source="purchase", now_ts=now, expires_ts=new_exp
            )
            if not ok:
                # 收了钱却没开成会员 → 回滚订单，留给平台/人工重试回调
                with session_scope() as s:
                    order_repo.revert_to_created(s, order_no)
                logger.error("订单 %s 已支付但开通会员失败，已回滚待重试", order_no)
                raise OrderError("开通会员失败，请稍后重试")
        logger.info(
            "订单 %s 支付成功：%s 开通 %s 至 %s", order_no, user_id, tier, new_exp
        )
        return {
            "ok": True, "order_no": order_no, "user_id": user_id,
            "tier": tier, "expires_ts": new_exp,
        }
