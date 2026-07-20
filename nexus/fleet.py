"""Nexus 舰队业务逻辑（纯函数层：签发 / 兑换 / 心跳 / 充值 / 扣费）。

设计约定：
    - 每个函数接收一个 SQLAlchemy Session，**不自己 commit 之外的事务管理**
      （HTTP 层一请求一 Session、一提交；测试里也好独立断言）；
    - 所有对外错误用 ``FleetError(code, message)`` 表达，HTTP 层翻译成
      {"errcode": ..., "error": ...} 的 JSON——与 Matrix 风格保持一致；
    - 钱包余额只能经 topup/debit 变动，保证每一分 token 都有流水。
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from nexus.db import (
    NexusHeartbeat,
    NexusInstance,
    NexusKey,
    NexusLedger,
    NexusWallet,
)
from nexus.keys import generate_key, hash_key, looks_like_key


class FleetError(Exception):
    """业务错误：code 用 NEXUS_ 前缀的大写蛇形，HTTP 层原样透出。"""

    def __init__(self, code: str, message: str, http_status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def _now_ms() -> int:
    return int(time.time() * 1000)


# ---------- KEY 签发 / 吊销（管理员操作）----------

def issue_keys(
    s, count: int = 1, note: str = "", token_grant: int = 0
) -> List[Dict[str, Any]]:
    """签发 ``count`` 把新 KEY，返回含**明文**的列表（明文仅此一次，不落库）。

    Args:
        count: 一次最多 100（防手滑批量刷爆）。
        note: 商务备注（卖给谁/订单号）。
        token_grant: 随 KEY 附赠的初始 token 额度（兑换时注入钱包）。
    """
    if not (1 <= count <= 100):
        raise FleetError("NEXUS_BAD_COUNT", "count 须在 1~100 之间")
    if token_grant < 0:
        raise FleetError("NEXUS_BAD_GRANT", "token_grant 不能为负")
    out: List[Dict[str, Any]] = []
    for _ in range(count):
        plain = generate_key()
        row = NexusKey(
            key_hash=hash_key(plain),
            key_tail=plain.rsplit("-", 1)[-1],
            note=note,
            token_grant=int(token_grant),
        )
        s.add(row)
        s.flush()  # 拿自增 id
        out.append({"id": row.id, "key": plain, "tail": row.key_tail})
    return out


def revoke_key(s, key_id: int) -> None:
    """吊销一把 KEY：兑换与（P2 起的）网关鉴权立即失效。幂等。"""
    row = s.get(NexusKey, int(key_id))
    if row is None:
        raise FleetError("NEXUS_KEY_NOT_FOUND", f"KEY id={key_id} 不存在", 404)
    row.status = "revoked"


def _key_by_plain(s, raw_key: str) -> NexusKey:
    """按明文 KEY 查行（内部工具）：格式粗筛 → 哈希查库 → 状态校验。"""
    if not looks_like_key(raw_key):
        raise FleetError("NEXUS_BAD_KEY", "授权码格式不正确", 400)
    row = s.execute(
        select(NexusKey).where(NexusKey.key_hash == hash_key(raw_key))
    ).scalar_one_or_none()
    if row is None:
        raise FleetError("NEXUS_KEY_NOT_FOUND", "授权码不存在", 404)
    if row.status != "active":
        raise FleetError("NEXUS_KEY_REVOKED", "授权码已被吊销", 403)
    return row


# ---------- 兑换（OEM 安装脚本调用）----------

def redeem(s, raw_key: str, domain: str, admin_email: str = "") -> Dict[str, Any]:
    """兑换 KEY、登记实例。**幂等**：同 KEY+同域名重复兑换（重装）直接返回原实例。

    规则（模块6 拍板语义）：
      - 一把 KEY 绑一个域名/实例；换域名视为新授权，须走人工（防一码多部）；
      - 一个域名只能被兑换一次（防抢注他人域名——真冲突走人工仲裁）；
      - 首次兑换时建钱包并注入 KEY 附赠的初始 token（记 grant 流水）。
    """
    domain = (domain or "").strip().lower()
    if not domain or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789.-" for c in domain):
        raise FleetError("NEXUS_BAD_DOMAIN", "域名不合法")
    key = _key_by_plain(s, raw_key)

    if key.instance_id is not None:
        inst = s.get(NexusInstance, key.instance_id)
        if inst is not None and inst.domain == domain:
            # 重装同域名：幂等放行
            return {"instance_id": inst.id, "domain": inst.domain, "reinstall": True}
        raise FleetError(
            "NEXUS_KEY_BOUND",
            "该授权码已绑定其他域名；如需换域名请联系 GuDuu 人工处理",
            409,
        )

    exists = s.execute(
        select(NexusInstance).where(NexusInstance.domain == domain)
    ).scalar_one_or_none()
    if exists is not None:
        raise FleetError("NEXUS_DOMAIN_TAKEN", "该域名已被其他授权码兑换", 409)

    inst = NexusInstance(domain=domain, admin_email=admin_email, key_id=key.id)
    s.add(inst)
    s.flush()
    key.instance_id = inst.id
    key.redeemed_ts = _now_ms()

    # 建钱包 + 注入初始额度（0 也建，网关统一按钱包判额度）
    s.add(NexusWallet(instance_id=inst.id, balance_tokens=int(key.token_grant)))
    if key.token_grant:
        s.add(
            NexusLedger(
                instance_id=inst.id,
                delta_tokens=int(key.token_grant),
                kind="grant",
                note=f"KEY#{key.id} 兑换附赠",
            )
        )
    return {"instance_id": inst.id, "domain": inst.domain, "reinstall": False}


# ---------- 心跳（实例定期回连）----------

def heartbeat(
    s, raw_key: str, version: str = "", stats: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """实例心跳：更新快照 + 记历史。返回母舰想让实例知道的少量信息。

    返回里带 ``balance_tokens``：实例侧可以在后台展示"余额快见底"提醒，
    这是续费转化的重要触点（钱包=唯一续费抓手）。
    """
    key = _key_by_plain(s, raw_key)
    if key.instance_id is None:
        raise FleetError("NEXUS_NOT_REDEEMED", "授权码尚未兑换开通", 403)
    inst = s.get(NexusInstance, key.instance_id)
    if inst is None:  # 理论不可达；防御一致性破损
        raise FleetError("NEXUS_INSTANCE_MISSING", "实例登记缺失", 500)

    payload = json.dumps(stats or {}, ensure_ascii=False)[:8000]  # 截断防灌爆
    inst.last_seen_ts = _now_ms()
    inst.version = (version or "")[:64]
    inst.stats_json = payload
    s.add(
        NexusHeartbeat(
            instance_id=inst.id, version=inst.version, stats_json=payload
        )
    )
    wallet = s.get(NexusWallet, inst.id)
    return {
        "instance_id": inst.id,
        "status": inst.status,
        "balance_tokens": int(wallet.balance_tokens) if wallet else 0,
    }


# ---------- 钱包（充值 / 扣费）----------

def topup(s, instance_id: int, tokens: int, note: str = "") -> int:
    """人工充值（P1 手动记账；P3 接支付后由订单回调调用）。返回新余额。"""
    if tokens <= 0:
        raise FleetError("NEXUS_BAD_TOPUP", "充值额度必须为正")
    wallet = s.get(NexusWallet, int(instance_id))
    if wallet is None:
        raise FleetError("NEXUS_INSTANCE_MISSING", "实例不存在", 404)
    wallet.balance_tokens = int(wallet.balance_tokens) + int(tokens)
    wallet.updated_ts = _now_ms()
    s.add(
        NexusLedger(
            instance_id=int(instance_id),
            delta_tokens=int(tokens),
            kind="topup",
            note=note,
        )
    )
    return int(wallet.balance_tokens)


def debit(s, instance_id: int, tokens: int, note: str = "") -> int:
    """网关计量扣费（P1 预留给 gateway 用）。余额可扣到负——

    为什么允许负数：一次 LLM 调用的用量要**事后**才知道，预扣会把流式体验
    搞复杂；断供判定是"余额 ≤ 0 拒绝**下一次**请求"，轻微透支计入商誉成本。
    返回扣后余额。
    """
    if tokens <= 0:
        raise FleetError("NEXUS_BAD_DEBIT", "扣费额度必须为正")
    wallet = s.get(NexusWallet, int(instance_id))
    if wallet is None:
        raise FleetError("NEXUS_INSTANCE_MISSING", "实例不存在", 404)
    wallet.balance_tokens = int(wallet.balance_tokens) - int(tokens)
    wallet.updated_ts = _now_ms()
    s.add(
        NexusLedger(
            instance_id=int(instance_id),
            delta_tokens=-int(tokens),
            kind="usage",
            note=note,
        )
    )
    return int(wallet.balance_tokens)


# ---------- 列表（console 用）----------

def list_keys(s) -> List[Dict[str, Any]]:
    """全部 KEY（不含任何可还原明文的信息）。"""
    rows = s.execute(select(NexusKey).order_by(NexusKey.id.desc())).scalars().all()
    return [
        {
            "id": r.id,
            "tail": r.key_tail,
            "status": r.status,
            "note": r.note,
            "token_grant": int(r.token_grant),
            "instance_id": r.instance_id,
            "created_ts": r.created_ts,
            "redeemed_ts": r.redeemed_ts,
        }
        for r in rows
    ]


def list_instances(s) -> List[Dict[str, Any]]:
    """全部实例 + 钱包余额快照（console 列表页/大屏树状图的数据源）。"""
    rows = s.execute(
        select(NexusInstance).order_by(NexusInstance.id.desc())
    ).scalars().all()
    out = []
    for r in rows:
        wallet = s.get(NexusWallet, r.id)
        try:
            stats = json.loads(r.stats_json or "{}")
        except Exception:
            stats = {}
        out.append(
            {
                "id": r.id,
                "domain": r.domain,
                "admin_email": r.admin_email,
                "status": r.status,
                "version": r.version,
                "created_ts": r.created_ts,
                "last_seen_ts": r.last_seen_ts,
                "stats": stats,
                "balance_tokens": int(wallet.balance_tokens) if wallet else 0,
            }
        )
    return out


# ---------- 大屏数据聚合（console/dashboard 用）----------

# 在线判定阈值：心跳间隔设计为 10 分钟级，15 分钟没心跳=警告，2 小时=离线
_ONLINE_MS = 15 * 60 * 1000
_WARN_MS = 2 * 60 * 60 * 1000


def _day_start_ms(offset_days: int = 0) -> int:
    """今日（本地时区）零点的毫秒时间戳；offset_days=-1 即昨日零点。"""
    lt = time.localtime(time.time() + offset_days * 86400)
    return int(
        time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1)) * 1000
    )


def _display_status(inst: NexusInstance, now: int) -> str:
    """把「停用标志 + 心跳新旧」折叠成大屏的三色状态。"""
    if inst.status != "active":
        return "offline"
    if inst.last_seen_ts is None or now - inst.last_seen_ts > _WARN_MS:
        return "offline"
    if now - inst.last_seen_ts > _ONLINE_MS:
        return "warning"
    return "active"


def dash_summary(s) -> Dict[str, Any]:
    """给数据大屏的一站式聚合：实例 × 用量 × 钱包 × 心跳 → 一个 JSON。

    设计考量：
      - 用量走 SQL 聚合（ledger 的 usage 行 = 每次 AI 调用一行，量会很大，
        绝不能全捞进内存）；模型分布只扫**今日**流水且封顶 2000 行；
      - delta（环比）= 今日 vs 昨日 token 消耗百分比，大屏涨跌角标用；
      - recent = 最近 15 条流水（充值/消耗/兑换都算"实时动态"素材）。
    """
    from sqlalchemy import func  # 就近导入：仅此函数用聚合

    now = _now_ms()
    today0 = _day_start_ms()
    yesterday0 = _day_start_ms(-1)

    def _usage_by_instance(since: int = 0, until: int = 0) -> Dict[int, Dict[str, int]]:
        """usage 流水按实例聚合：{instance_id: {tokens, requests}}（SQL SUM/COUNT）。"""
        q = select(
            NexusLedger.instance_id,
            func.sum(NexusLedger.delta_tokens),
            func.count(),
        ).where(NexusLedger.kind == "usage")
        if since:
            q = q.where(NexusLedger.ts >= since)
        if until:
            q = q.where(NexusLedger.ts < until)
        out: Dict[int, Dict[str, int]] = {}
        for iid, total, cnt in s.execute(q.group_by(NexusLedger.instance_id)).all():
            # usage 的 delta 是负数，取绝对值当消耗
            out[int(iid)] = {"tokens": abs(int(total or 0)), "requests": int(cnt or 0)}
        return out

    all_usage = _usage_by_instance()
    today_usage = _usage_by_instance(since=today0)
    yesterday_usage = _usage_by_instance(since=yesterday0, until=today0)

    # 今日模型分布：从流水备注（"provider/model in=x out=y"）解析，封顶 2000 行
    model_rows = s.execute(
        select(NexusLedger.instance_id, NexusLedger.note)
        .where(NexusLedger.kind == "usage", NexusLedger.ts >= today0)
        .order_by(NexusLedger.id.desc())
        .limit(2000)
    ).all()
    models_by_inst: Dict[int, set] = {}
    for iid, note in model_rows:
        model = (note or "").split(" ", 1)[0]
        if model:
            models_by_inst.setdefault(int(iid), set()).add(model)

    oems: List[Dict[str, Any]] = []
    online = 0
    for inst in s.execute(select(NexusInstance).order_by(NexusInstance.id)).scalars():
        wallet = s.get(NexusWallet, inst.id)
        try:
            stats = json.loads(inst.stats_json or "{}")
        except Exception:
            stats = {}
        status = _display_status(inst, now)
        if status != "offline":
            online += 1
        t_today = today_usage.get(inst.id, {}).get("tokens", 0)
        t_yesterday = yesterday_usage.get(inst.id, {}).get("tokens", 0)
        # 环比：昨日为 0 时不算涨幅（避免 +∞），显示 0
        delta = round((t_today - t_yesterday) / t_yesterday * 100, 1) if t_yesterday else 0.0
        oems.append(
            {
                "id": inst.id,
                "domain": inst.domain,
                "status": status,
                "version": inst.version,
                "last_seen_ts": inst.last_seen_ts,
                "balance_tokens": int(wallet.balance_tokens) if wallet else 0,
                "tokens_total": all_usage.get(inst.id, {}).get("tokens", 0),
                "tokens_today": t_today,
                "requests_today": today_usage.get(inst.id, {}).get("requests", 0),
                "models_today": len(models_by_inst.get(inst.id, ())),
                "delta_pct": delta,
                "users": int(stats.get("users") or 0),
            }
        )

    recent_rows = s.execute(
        select(NexusLedger).order_by(NexusLedger.id.desc()).limit(15)
    ).scalars().all()
    domains = {o["id"]: o["domain"] for o in oems}
    recent = [
        {
            "ts": r.ts,
            "kind": r.kind,
            "domain": domains.get(r.instance_id, f"#{r.instance_id}"),
            "tokens": int(r.delta_tokens),
            "note": (r.note or "")[:80],
        }
        for r in recent_rows
    ]

    return {
        "generated_ts": now,
        "totals": {
            "instances": len(oems),
            "online": online,
            "users": sum(o["users"] for o in oems),
            "tokens_total": sum(o["tokens_total"] for o in oems),
            "tokens_today": sum(o["tokens_today"] for o in oems),
            "requests_today": sum(o["requests_today"] for o in oems),
            "balance_total": sum(o["balance_tokens"] for o in oems),
        },
        "oems": oems,
        "recent": recent,
    }
