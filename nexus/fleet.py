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
import hmac
import time
from typing import Any, Dict, List, Optional

from sqlalchemy import case, func, select, update

from nexus import geo
from nexus.db import (
    NexusHeartbeat,
    NexusInstance,
    NexusInstanceGeo,
    NexusKey,
    NexusKeyBinding,
    NexusKeyClaim,
    NexusLedger,
    NexusOem,
    NexusOemProfile,
    NexusRequestStat,
    NexusWallet,
)
from nexus.keys import generate_key, hash_key, looks_like_key
from nexus import network_binding


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

_MAX_TOKEN_GRANT = 1_000_000_000_000


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
    if token_grant < 0 or token_grant > _MAX_TOKEN_GRANT:
        raise FleetError(
            "NEXUS_BAD_GRANT",
            f"token_grant 须在 0~{_MAX_TOKEN_GRANT} 之间",
        )
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
    """永久吊销一把 KEY，并同步暂停已绑定实例。幂等且不可恢复。"""
    set_key_status(s, key_id, "revoked")


def set_key_status(s, key_id: int, status: str) -> Dict[str, Any]:
    """暂停、恢复或永久吊销 KEY，并让实例状态与授权状态保持一致。

    ``suspended`` 用于合同/安全事件临时止用，可恢复；``revoked`` 是不可逆终态，防止
    管理员误点“恢复”让已经泄露或被替换的 KEY 重新取得网关权限。
    """
    if status not in ("active", "suspended", "revoked"):
        raise FleetError("NEXUS_BAD_STATUS", "KEY 状态不受支持")
    row = s.get(NexusKey, int(key_id))
    if row is None:
        raise FleetError("NEXUS_KEY_NOT_FOUND", f"KEY id={key_id} 不存在", 404)
    old_status = row.status
    if old_status == "revoked" and status != "revoked":
        raise FleetError("NEXUS_KEY_REVOKED", "已吊销 KEY 不能恢复", 409)
    if status == "active" and old_status != "suspended":
        raise FleetError("NEXUS_KEY_NOT_SUSPENDED", "只有已暂停 KEY 可以恢复", 409)
    row.status = status
    if row.instance_id is not None:
        instance = s.get(NexusInstance, row.instance_id)
        if instance is not None:
            instance.status = "active" if status == "active" else "suspended"
    return {"id": row.id, "from_status": old_status, "status": row.status}


def _key_by_plain(s, raw_key: str) -> NexusKey:
    """按明文 KEY 查行（内部工具）：格式粗筛 → 哈希查库 → 状态校验。"""
    if not looks_like_key(raw_key):
        raise FleetError("NEXUS_BAD_KEY", "授权码格式不正确", 400)
    row = s.execute(
        select(NexusKey).where(NexusKey.key_hash == hash_key(raw_key))
    ).scalar_one_or_none()
    if row is None:
        raise FleetError("NEXUS_KEY_NOT_FOUND", "授权码不存在", 404)
    if row.status == "suspended":
        raise FleetError("NEXUS_KEY_SUSPENDED", "授权码已被平台暂停", 403)
    if row.status != "active":
        raise FleetError("NEXUS_KEY_REVOKED", "授权码已被吊销", 403)
    return row


# ---------- 兑换（OEM 安装脚本调用）----------


def redeem(
    s,
    raw_key: str,
    domain: str,
    admin_email: str = "",
    region: str = "",
    client_ip: str = "",
) -> Dict[str, Any]:
    """兑换 KEY、登记实例。**幂等**：同 KEY+同域名重复兑换（重装）直接返回原实例。

    规则（模块6 拍板语义）：
      - 一把 KEY 绑一个域名/实例；换域名视为新授权，须走人工（防一码多部）；
      - 一个域名只能被兑换一次（防抢注他人域名——真冲突走人工仲裁）；
      - 首次兑换时建钱包并注入 KEY 附赠的初始 token（记 grant 流水）。
    """
    domain = (domain or "").strip().lower()
    if not domain or any(
        c not in "abcdefghijklmnopqrstuvwxyz0123456789.-" for c in domain
    ):
        raise FleetError("NEXUS_BAD_DOMAIN", "域名不合法")
    key = _key_by_plain(s, raw_key)
    region_code = geo.normalize(region)
    binding = s.get(NexusKeyBinding, key.id)
    # 新签发 KEY 已在审批时冻结域名；历史 KEY 没有绑定记录，首次兑换仍保持兼容，
    # 但会立即把实际域名冻结下来，之后不能换服务器域名复用。
    if binding is not None and binding.approved_domain:
        if binding.approved_domain != domain:
            raise FleetError(
                "NEXUS_KEY_BOUND"
                if key.instance_id is not None
                else "NEXUS_DOMAIN_MISMATCH",
                (
                    "该授权码已绑定其他域名；如需换域名请联系 GuDuu 人工处理"
                    if key.instance_id is not None
                    else f"该 KEY 仅允许部署到 {binding.approved_domain}"
                ),
                409 if key.instance_id is not None else 403,
            )
    elif binding is None:
        binding = NexusKeyBinding(key_id=key.id, approved_domain=domain)
        s.add(binding)

    warnings: List[str] = []
    observed_hash = network_binding.fingerprint(client_ip) if client_ip else ""
    observed_masked = network_binding.masked(client_ip) if client_ip else ""
    if binding.expected_ip_hash:
        matches = bool(observed_hash) and hmac.compare_digest(
            binding.expected_ip_hash, observed_hash
        )
        if not matches and int(binding.strict_ip or 0):
            raise FleetError(
                "NEXUS_ACTIVATION_IP_MISMATCH",
                "激活请求来源 IP 与授权申请中的严格绑定 IP 不一致",
                403,
            )
        if not matches:
            warnings.append("activation_ip_mismatch")

    if key.instance_id is not None:
        inst = s.get(NexusInstance, key.instance_id)
        if inst is not None and inst.domain == domain:
            # 重装同域名：幂等放行
            # 新安装器会在每次兑换时携带地域。历史实例过去可能漏填，
            # 因此重装/补激活时允许顺手补齐或纠正，不要求人工改数据库。
            if region_code:
                set_geo(s, int(inst.id), region_code)
            if observed_hash:
                binding.activation_ip_hash = observed_hash
                binding.activation_ip_masked = observed_masked
                binding.risk_status = warnings[0] if warnings else ""
                binding.activated_ts = _now_ms()
            return {
                "instance_id": inst.id,
                "domain": inst.domain,
                "reinstall": True,
                "warnings": warnings,
            }
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
    binding.approved_domain = binding.approved_domain or domain
    binding.activation_ip_hash = observed_hash
    binding.activation_ip_masked = observed_masked
    binding.risk_status = warnings[0] if warnings else ""
    binding.activated_ts = _now_ms()

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
    # 地域：真实 HTTP 部署已在 ``deployment_region`` 强制校验；这里仍兼容
    # 内部历史脚本，避免数据库修复工具因旧参数立即失效。
    if region_code:
        info = geo.lookup(region_code)
        s.add(
            NexusInstanceGeo(
                instance_id=inst.id,
                region_code=region_code,
                region_label=info["label"],
                lat=info["lat"],
                lon=info["lon"],
            )
        )
    return {
        "instance_id": inst.id,
        "domain": inst.domain,
        "reinstall": False,
        "warnings": warnings,
    }


def deployment_region(s, raw_key: str, region: str) -> str:
    """校验真实 HTTP 部署请求的地域，并兼容已有定位的历史实例。

    首次部署必须提供 ``geo.REGIONS`` 中的地域代码，保证实例一登记就能在
    大屏地图定位。历史实例重装时若请求未携带地域，只在数据库已经存在
    有效定位时复用旧值；历史实例本身也缺定位则继续拒绝，不能静默消失。

    Args:
        s: Nexus 数据库会话。
        raw_key: 节点提交的 OEM KEY 明文，仅用于查询其绑定实例。
        region: 安装器或受限激活服务提交的地域代码。

    Returns:
        规范化后的有效地域代码。

    Raises:
        FleetError: KEY 无效、地域缺失或地域代码不受支持。
    """
    key = _key_by_plain(s, raw_key)
    supplied = (region or "").strip()
    normalized = geo.normalize(supplied)
    if normalized:
        return normalized
    if supplied:
        raise FleetError(
            "NEXUS_BAD_REGION",
            "机房地域代码无效，请重新选择部署地域",
            400,
        )
    if key.instance_id is not None:
        row = s.get(NexusInstanceGeo, int(key.instance_id))
        if row is not None and geo.is_valid(row.region_code or ""):
            return geo.normalize(row.region_code)
    raise FleetError(
        "NEXUS_REGION_REQUIRED",
        "部署必须选择机房地域，节点才能接入运营大屏地图",
        400,
    )


# ---------- 心跳（实例定期回连）----------


def heartbeat(
    s,
    raw_key: str,
    version: str = "",
    stats: Optional[Dict[str, Any]] = None,
    client_ip: str = "",
) -> Dict[str, Any]:
    """实例心跳：更新快照 + 记历史。返回母舰想让实例知道的少量信息。

    返回里带 ``balance_tokens``：实例侧可以在后台展示"余额快见底"提醒，
    这是续费转化的重要触点（钱包=唯一续费抓手）。

    ``client_ip``：母舰从请求里读到的**真实来源 IP**（实例自报不可信：它在 NAT/容器里
    根本不知道自己的公网 IP，且可伪造）。这里只**脱敏存网段**、供人工核对 OEM 填的地域
    是否离谱，**不做自动定位**（云 IP 归属常是服务商注册地，反而更不准，见 geo.py）。
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
    s.add(NexusHeartbeat(instance_id=inst.id, version=inst.version, stats_json=payload))
    # 记下来源网段（best-effort：地域行不存在就顺手建一条空的，等 OEM/管理员填地域）
    masked = geo.mask_ip(client_ip)
    if masked:
        row = s.get(NexusInstanceGeo, inst.id)
        if row is None:
            row = NexusInstanceGeo(instance_id=inst.id)
            s.add(row)
        if row.last_ip != masked:
            row.last_ip = masked
            row.updated_ts = _now_ms()

    wallet = s.get(NexusWallet, inst.id)
    return {
        "instance_id": inst.id,
        "status": inst.status,
        "balance_tokens": int(wallet.balance_tokens) if wallet else 0,
    }


# ---------- 网关请求统计（成功率 / 延迟 / 峰值）----------


def record_request(s, instance_id: int, *, ok: bool, latency_ms: int = 0) -> None:
    """记一次网关请求到**分钟桶**。成败都要记——只记成功的话成功率永远是 100%。

    并发收敛：先原子 UPDATE 累加,rowcount=0 说明本分钟还没有行,再 INSERT;
    INSERT 撞唯一键(另一并发线程刚建)就重试一次 UPDATE。
    延迟只累计成功请求(失败多是秒回的 4xx,混进来会把均值拉得虚低)。
    **best-effort**:统计失败绝不能影响网关转发,调用方吞异常。
    """
    minute = (int(time.time() * 1000) // 60000) * 60000
    ms = max(0, int(latency_ms))
    inc_ok, inc_fail = (1, 0) if ok else (0, 1)
    lat_sum = ms if ok else 0

    def _update() -> int:
        res = s.execute(
            update(NexusRequestStat)
            .where(
                NexusRequestStat.instance_id == int(instance_id),
                NexusRequestStat.minute_ts == minute,
            )
            .values(
                ok_count=NexusRequestStat.ok_count + inc_ok,
                fail_count=NexusRequestStat.fail_count + inc_fail,
                latency_sum_ms=NexusRequestStat.latency_sum_ms + lat_sum,
                latency_max_ms=case(
                    (NexusRequestStat.latency_max_ms < ms, ms),
                    else_=NexusRequestStat.latency_max_ms,
                ),
            )
        )
        return res.rowcount or 0

    if _update():
        return
    try:
        s.add(
            NexusRequestStat(
                instance_id=int(instance_id),
                minute_ts=minute,
                ok_count=inc_ok,
                fail_count=inc_fail,
                latency_sum_ms=lat_sum,
                latency_max_ms=ms if ok else 0,
            )
        )
        s.flush()
    except Exception:
        s.rollback()
        _update()  # 撞并发插入:回到累加路径


def request_stats(s, since_ms: int = 0) -> Dict[int, Dict[str, Any]]:
    """按实例聚合请求统计：{instance_id: {ok, fail, success_pct, avg_ms, peak_per_min}}。

    success_pct 为 None 表示**这段时间内一次请求都没有**——大屏必须显示「—」而不是 0%
    （0% 成功率读起来像"全线故障",比不显示更误导）。
    """
    q = select(
        NexusRequestStat.instance_id,
        func.sum(NexusRequestStat.ok_count),
        func.sum(NexusRequestStat.fail_count),
        func.sum(NexusRequestStat.latency_sum_ms),
        func.max(NexusRequestStat.ok_count + NexusRequestStat.fail_count),
    )
    if since_ms:
        q = q.where(NexusRequestStat.minute_ts >= since_ms)
    out: Dict[int, Dict[str, Any]] = {}
    for iid, ok, fail, lat_sum, peak in s.execute(
        q.group_by(NexusRequestStat.instance_id)
    ).all():
        ok = int(ok or 0)
        fail = int(fail or 0)
        total = ok + fail
        out[int(iid)] = {
            "ok": ok,
            "fail": fail,
            "success_pct": round(ok / total * 100, 2) if total else None,
            "avg_ms": int((lat_sum or 0) / ok) if ok else None,
            "peak_per_min": int(peak or 0),
        }
    return out


# ---------- 实例地域（大屏地图）----------


def set_geo(s, instance_id: int, region_code: str) -> Dict[str, Any]:
    """设置或修改实例地域；已部署节点不允许清空定位。

    坐标从字典查出来**冗余存下**：字典将来微调坐标不影响历史展示，大屏读表即可、免查表。
    """
    inst = s.get(NexusInstance, int(instance_id))
    if inst is None:
        raise FleetError("NEXUS_INSTANCE_MISSING", "实例不存在", 404)
    code = geo.normalize(region_code)
    if not (region_code or "").strip():
        raise FleetError(
            "NEXUS_REGION_REQUIRED",
            "已部署节点必须保留机房地域，不能从运营大屏地图移除",
            400,
        )
    if not code:
        raise FleetError("NEXUS_BAD_REGION", "地域代码不合法", 400)
    row = s.get(NexusInstanceGeo, inst.id)
    if row is None:
        row = NexusInstanceGeo(instance_id=inst.id)
        s.add(row)
    info = geo.lookup(code)
    row.region_code = code
    row.region_label = info["label"]
    row.lat = info["lat"]
    row.lon = info["lon"]
    row.updated_ts = _now_ms()
    s.flush()
    return {"instance_id": inst.id, "region": code, "label": row.region_label}


def _geo_of(s, instance_id: int) -> Dict[str, Any]:
    """取某实例的地域快照（没填过就返回空壳，调用方无需判 None）。"""
    row = s.get(NexusInstanceGeo, int(instance_id))
    if row is None:
        return {
            "region": "",
            "region_label": "",
            "lat": None,
            "lon": None,
            "last_ip": "",
        }
    return {
        "region": row.region_code or "",
        "region_label": row.region_label or "",
        "lat": row.lat,
        "lon": row.lon,
        "last_ip": row.last_ip or "",
    }


# ---------- 钱包（充值 / 扣费）----------


def topup(s, instance_id: int, tokens: int, note: str = "") -> int:
    """人工充值（P1 手动记账；P3 接支付后由订单回调调用）。返回新余额。

    余额用数据库原子 ``balance = balance + tokens`` 更新，避免支付回调与网关扣费并发时
    双方都基于旧余额回写，造成充值或扣费其中一笔凭空丢失。
    """
    if tokens <= 0:
        raise FleetError("NEXUS_BAD_TOPUP", "充值额度必须为正")
    iid = int(instance_id)
    amount = int(tokens)
    result = s.execute(
        update(NexusWallet)
        .where(NexusWallet.instance_id == iid)
        .values(
            balance_tokens=NexusWallet.balance_tokens + amount,
            updated_ts=_now_ms(),
        )
    )
    if (result.rowcount or 0) < 1:
        raise FleetError("NEXUS_INSTANCE_MISSING", "实例不存在", 404)
    new_balance = int(
        s.execute(
            select(NexusWallet.balance_tokens).where(NexusWallet.instance_id == iid)
        ).scalar_one()
    )
    s.add(
        NexusLedger(
            instance_id=iid,
            delta_tokens=amount,
            kind="topup",
            note=note,
        )
    )
    return new_balance


def debit(s, instance_id: int, tokens: int, note: str = "") -> int:
    """网关计量扣费（P1 预留给 gateway 用）。余额可扣到负——

    为什么允许负数：一次 LLM 调用的用量要**事后**才知道，预扣会把流式体验
    搞复杂；断供判定是"余额 ≤ 0 拒绝**下一次**请求"，轻微透支计入商誉成本。
    返回扣后余额。
    """
    if tokens <= 0:
        raise FleetError("NEXUS_BAD_DEBIT", "扣费额度必须为正")
    iid = int(instance_id)
    amount = int(tokens)
    # 允许扣成负数是既定的“最后一单后付”语义；但减法必须由数据库原子执行，不能先读
    # 再回写，否则与充值/其他扣费并发时会丢更新。网关实例闸门负责限制同实例在途请求。
    result = s.execute(
        update(NexusWallet)
        .where(NexusWallet.instance_id == iid)
        .values(
            balance_tokens=NexusWallet.balance_tokens - amount,
            updated_ts=_now_ms(),
        )
    )
    if (result.rowcount or 0) < 1:
        raise FleetError("NEXUS_INSTANCE_MISSING", "实例不存在", 404)
    new_balance = int(
        s.execute(
            select(NexusWallet.balance_tokens).where(NexusWallet.instance_id == iid)
        ).scalar_one()
    )
    s.add(
        NexusLedger(
            instance_id=iid,
            delta_tokens=-amount,
            kind="usage",
            note=note,
        )
    )
    return new_balance


def _usage_by_instance(s, since: int = 0, until: int = 0) -> Dict[int, Dict[str, int]]:
    """Nexus usage 流水按实例聚合 token 消耗与 AI 请求次数。

    返回 ``{instance_id: {tokens, requests}}``。账本中 usage 是负数扣费，
    展示统计取绝对值；时间边界用毫秒，``since`` 包含、``until`` 不包含。
    SQL 直接 SUM/COUNT，不会把大量明细流水拉进内存。
    """
    query = select(
        NexusLedger.instance_id,
        func.sum(NexusLedger.delta_tokens),
        func.count(),
    ).where(NexusLedger.kind == "usage")
    if since:
        query = query.where(NexusLedger.ts >= since)
    if until:
        query = query.where(NexusLedger.ts < until)
    out: Dict[int, Dict[str, int]] = {}
    for instance_id, total, count in s.execute(
        query.group_by(NexusLedger.instance_id)
    ).all():
        out[int(instance_id)] = {
            "tokens": abs(int(total or 0)),
            "requests": int(count or 0),
        }
    return out


# ---------- 列表（console 用）----------


def list_keys(s) -> List[Dict[str, Any]]:
    """全部 KEY + 归属企业（不含任何可还原明文的信息）。"""
    rows = s.execute(select(NexusKey).order_by(NexusKey.id.desc())).scalars().all()
    key_ids = [int(row.id) for row in rows]
    claims = {
        int(claim.key_id): int(claim.oem_id)
        for claim in s.execute(
            select(NexusKeyClaim).where(NexusKeyClaim.key_id.in_(key_ids or [-1]))
        )
        .scalars()
        .all()
    }
    owner_ids = sorted(set(claims.values()))
    accounts = {
        int(account.id): account.email
        for account in s.execute(
            select(NexusOem).where(NexusOem.id.in_(owner_ids or [-1]))
        )
        .scalars()
        .all()
    }
    profiles = {
        int(profile.oem_id): profile.company
        for profile in s.execute(
            select(NexusOemProfile).where(NexusOemProfile.oem_id.in_(owner_ids or [-1]))
        )
        .scalars()
        .all()
    }
    bindings = {
        int(binding.key_id): binding
        for binding in s.execute(
            select(NexusKeyBinding).where(NexusKeyBinding.key_id.in_(key_ids or [-1]))
        )
        .scalars()
        .all()
    }
    out: List[Dict[str, Any]] = []
    for row in rows:
        owner_id = claims.get(int(row.id))
        binding = bindings.get(int(row.id))
        out.append(
            {
                "id": row.id,
                "tail": row.key_tail,
                "status": row.status,
                "note": row.note,
                "token_grant": int(row.token_grant),
                "instance_id": row.instance_id,
                "created_ts": row.created_ts,
                "redeemed_ts": row.redeemed_ts,
                "oem_id": owner_id,
                "oem_email": accounts.get(owner_id, "") if owner_id else "",
                "company_name": profiles.get(owner_id, "") if owner_id else "",
                "approved_domain": binding.approved_domain if binding else "",
                "expected_public_ip_masked": (
                    binding.expected_ip_masked if binding else ""
                ),
                "strict_ip": bool(binding.strict_ip) if binding else False,
                "activation_ip_masked": (
                    binding.activation_ip_masked if binding else ""
                ),
                "risk_status": binding.risk_status if binding else "",
            }
        )
    return out


def list_instances(s) -> List[Dict[str, Any]]:
    """全部实例 + OEM 企业 + 钱包 + Token 消耗快照。

    所属关系不直接写在实例表，而是沿 ``实例.key_id → KEY 认领记录
    → OEM 企业档案`` 查找。这样 KEY 的商业归属仍保持单一真实源，不会在
    实例表再复制一份企业名造成改名后不一致。早期未认领节点返回空企业，
    由前端明确显示“未绑定企业”。
    """
    rows = (
        s.execute(select(NexusInstance).order_by(NexusInstance.id.desc()))
        .scalars()
        .all()
    )
    # 两次聚合查询一次拿齐所有实例，避免列表里每个节点再查两遍账本。
    all_usage = _usage_by_instance(s)
    today_usage = _usage_by_instance(s, since=_day_start_ms())
    key_ids = [int(row.key_id) for row in rows]
    owners: Dict[int, Dict[str, Any]] = {}
    if key_ids:
        # 一次 JOIN 拿齐所有企业，避免实例越多时产生 N+1 查询。
        owner_rows = s.execute(
            select(
                NexusKeyClaim.key_id,
                NexusOem.id,
                NexusOem.email,
                NexusOem.name,
                NexusOemProfile.company,
            )
            .join(NexusOem, NexusOem.id == NexusKeyClaim.oem_id)
            .outerjoin(NexusOemProfile, NexusOemProfile.oem_id == NexusOem.id)
            .where(NexusKeyClaim.key_id.in_(key_ids))
        ).all()
        for key_id, oem_id, email, name, company in owner_rows:
            # 新注册必有 company；历史账号无档案时回退显示名，再回退邮箱。
            owners[int(key_id)] = {
                "oem_id": int(oem_id),
                "company_name": (company or name or email or "").strip(),
                "oem_email": email or "",
            }
    out = []
    for r in rows:
        wallet = s.get(NexusWallet, r.id)
        owner = owners.get(int(r.key_id), {})
        try:
            stats = json.loads(r.stats_json or "{}")
        except Exception:
            stats = {}
        out.append(
            {
                "id": r.id,
                "domain": r.domain,
                "admin_email": r.admin_email,
                "oem_id": owner.get("oem_id"),
                "company_name": owner.get("company_name", ""),
                "oem_email": owner.get("oem_email", ""),
                "status": r.status,
                "version": r.version,
                "created_ts": r.created_ts,
                "last_seen_ts": r.last_seen_ts,
                "stats": stats,
                "balance_tokens": int(wallet.balance_tokens) if wallet else 0,
                "tokens_total": all_usage.get(r.id, {}).get("tokens", 0),
                "tokens_today": today_usage.get(r.id, {}).get("tokens", 0),
                "requests_total": all_usage.get(r.id, {}).get("requests", 0),
                "requests_today": today_usage.get(r.id, {}).get("requests", 0),
                # 地域（大屏地图打点）；历史缺失记录仍在 totals.unlocated 中显式告警，
                # 新部署由 HTTP 兑换入口强制选择，不能再静默漏点。
                **_geo_of(s, r.id),
            }
        )
    return out


def instance_snapshot(s, instance_id: int) -> Dict[str, Any]:
    """返回单个节点的心跳、钱包、用量和地域快照。

    参数 ``instance_id`` 是 Nexus 实例编号，返回值与超管实例列表中
    单个节点的运行字段保持同一口径。本函数只组装运行数据，不判断
    谁可以看；OEM 归属权限必须在调用它之前由 ``oem.my_instance_detail``
    强制校验，这样权限边界不会混进通用统计函数。
    """
    iid = int(instance_id)
    row = s.get(NexusInstance, iid)
    if row is None:
        raise FleetError("NEXUS_INSTANCE_MISSING", "实例不存在", 404)
    wallet = s.get(NexusWallet, iid)
    try:
        stats = json.loads(row.stats_json or "{}")
    except Exception:
        # 历史心跳如果曾写入损坏 JSON，详情页仍应展示基础运行信息。
        stats = {}
    all_usage = _usage_by_instance(s).get(iid, {})
    today_usage = _usage_by_instance(s, since=_day_start_ms()).get(iid, {})
    return {
        "id": row.id,
        "domain": row.domain,
        "admin_email": row.admin_email,
        "status": row.status,
        "version": row.version,
        "created_ts": row.created_ts,
        "last_seen_ts": row.last_seen_ts,
        "stats": stats,
        "balance_tokens": int(wallet.balance_tokens) if wallet else 0,
        "tokens_total": all_usage.get("tokens", 0),
        "tokens_today": today_usage.get("tokens", 0),
        "requests_total": all_usage.get("requests", 0),
        "requests_today": today_usage.get("requests", 0),
        **_geo_of(s, iid),
    }


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

    all_usage = _usage_by_instance(s)
    today_usage = _usage_by_instance(s, since=today0)
    yesterday_usage = _usage_by_instance(s, since=yesterday0, until=today0)

    # 今日模型分布：从流水备注（"provider/model in=x out=y"）解析，封顶 4000 行。
    # 同一次扫描喂两个面板：每实例的"在用模型数" + 全舰队的"模型用量分布环图"。
    model_rows = s.execute(
        select(NexusLedger.instance_id, NexusLedger.note, NexusLedger.delta_tokens)
        .where(NexusLedger.kind == "usage", NexusLedger.ts >= today0)
        .order_by(NexusLedger.id.desc())
        .limit(4000)
    ).all()
    models_by_inst: Dict[int, set] = {}
    model_tokens: Dict[str, int] = {}
    for iid, note, delta in model_rows:
        model = (note or "").split(" ", 1)[0]
        if model:
            models_by_inst.setdefault(int(iid), set()).add(model)
            model_tokens[model] = model_tokens.get(model, 0) + abs(int(delta or 0))
    # 环图数据：按用量降序取前 8（再多环图挤不下也没意义）
    models_top = [
        {"model": m, "tokens": t}
        for m, t in sorted(model_tokens.items(), key=lambda kv: -kv[1])[:8]
    ]

    # 近 24 小时逐小时消耗（趋势图数据源）：SQL 按小时桶聚合
    hour_ms = 3600 * 1000
    since_24h = now - 24 * hour_ms
    # ⚠️ 用 op("/") 发原生整除——SQLAlchemy 2.0 的 Python 风格 `/` 是真除法，
    # 会产生小数桶导致每行自成一组（实测踩坑：聚合结果只剩每桶最后一行）
    bucket_expr = NexusLedger.ts.op("/")(hour_ms)
    hourly_rows = s.execute(
        select(bucket_expr, func.sum(NexusLedger.delta_tokens))
        .where(NexusLedger.kind == "usage", NexusLedger.ts >= since_24h)
        .group_by(bucket_expr)
    ).all()
    by_bucket = {int(b): abs(int(t or 0)) for b, t in hourly_rows}
    start_bucket = int(since_24h // hour_ms) + 1
    hourly = [
        {
            "ts": (start_bucket + i) * hour_ms,
            "tokens": by_bucket.get(start_bucket + i, 0),
        }
        for i in range(24)
    ]

    # 总发放（grant+topup 的正数流水合计）：配额面板"已消耗/总发放"的分母
    granted_total = int(
        s.execute(
            select(func.sum(NexusLedger.delta_tokens)).where(
                NexusLedger.delta_tokens > 0
            )
        ).scalar()
        or 0
    )

    # 今日请求质量（成功率/延迟/峰值）——分钟桶聚合，一次查完供所有实例用
    req_stats = request_stats(s, since_ms=today0)

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
        # 新节点已将业务用户与管理员/AI 拆开；旧节点只有 ``users``
        # 总数时仍兼容展示，等节点升级后自动切换到准确口径。
        business_users = int(stats.get("users_business", stats.get("users", 0)) or 0)
        accounts_total = int(stats.get("users_total", stats.get("users", 0)) or 0)
        admin_users = int(stats.get("users_admin") or 0)
        ai_users = int(stats.get("users_ai") or 0)
        # 环比：昨日为 0 时不算涨幅（避免 +∞），显示 0
        delta = (
            round((t_today - t_yesterday) / t_yesterday * 100, 1)
            if t_yesterday
            else 0.0
        )
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
                # 请求质量（网关分钟桶聚合）：无请求时 success_pct/avg_ms 为 None,
                # 前端必须显示「—」而不是 0%——0% 成功率读起来像"全线故障"。
                "success_pct": (req_stats.get(inst.id) or {}).get("success_pct"),
                "avg_latency_ms": (req_stats.get(inst.id) or {}).get("avg_ms"),
                "peak_per_min": (req_stats.get(inst.id) or {}).get("peak_per_min", 0),
                # 地域（大屏地图按真实经纬度打点；未填时 lat/lon=None，前端跳过不画）
                **_geo_of(s, inst.id),
                "users": business_users,
                "accounts_total": accounts_total,
                "admin_users": admin_users,
                "ai_users": ai_users,
            }
        )

    recent_rows = (
        s.execute(select(NexusLedger).order_by(NexusLedger.id.desc()).limit(15))
        .scalars()
        .all()
    )
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

    tokens_yesterday = sum(
        yesterday_usage.get(o["id"], {}).get("tokens", 0) for o in oems
    )
    return {
        "generated_ts": now,
        "totals": {
            "instances": len(oems),
            # 即使历史节点缺地域也必须计入接入总数，并把缺口显式交给大屏；
            # 不能因为地图无法打点就让整台 OEM 节点看起来不存在。
            "unlocated": sum(1 for o in oems if not o.get("region_label")),
            "online": online,
            "users": sum(o["users"] for o in oems),
            "accounts_total": sum(o["accounts_total"] for o in oems),
            "admin_users": sum(o["admin_users"] for o in oems),
            "ai_users": sum(o["ai_users"] for o in oems),
            "tokens_total": sum(o["tokens_total"] for o in oems),
            "tokens_today": sum(o["tokens_today"] for o in oems),
            "tokens_yesterday": tokens_yesterday,
            "requests_today": sum(o["requests_today"] for o in oems),
            "balance_total": sum(o["balance_tokens"] for o in oems),
            "granted_total": granted_total,
            # 全舰队今日请求质量：成功率(无请求=None,前端显示「—」)/峰值 req/min
            "success_pct": (
                round(
                    sum(v["ok"] for v in req_stats.values())
                    / max(1, sum(v["ok"] + v["fail"] for v in req_stats.values()))
                    * 100,
                    2,
                )
                if any(v["ok"] + v["fail"] for v in req_stats.values())
                else None
            ),
            "peak_per_min": max([v["peak_per_min"] for v in req_stats.values()] or [0]),
            # 舰队覆盖的地域（底部 Region 用；多地域显示"N 个地域"）。
            # 统计**所有已定位实例**而非仅在线——否则单实例偶发掉线时底栏会闪成「—」，
            # 而"部署在哪"这件事并不随在线状态变化。
            "regions": sorted(
                {o["region_label"] for o in oems if o.get("region_label")}
            ),
        },
        "oems": oems,
        "models": models_top,
        "hourly": hourly,
        "recent": recent,
    }
