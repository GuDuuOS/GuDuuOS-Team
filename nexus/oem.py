"""Nexus OEM 账号层：注册 / 登录 / 会话 + KEY 认领 + 自有资源查询。

这是「角色分权」的 OEM 一侧（模块6 P1 拍板）：
    - 平台超管 = 现有 ``NEXUS_ADMIN_TOKEN``（看全部、签发 KEY、充值）——见 service.py；
    - OEM 客户 = 邮箱+密码独立账号，登录拿会话令牌，**只能看/操作自己认领的
      KEY 及其实例**（服务端强制，前端只是配合）。

纯函数层：每个函数收一个 SQLAlchemy Session，不自管事务（HTTP 层一请求一提交），
错误统一抛 ``FleetError``（复用 fleet 那套，HTTP 层已能翻成 JSON）。密码用标准库
pbkdf2 派生，不引三方库（与项目「栈越少越好」一致）。
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from nexus.db import (
    NexusInstance,
    NexusKey,
    NexusKeyClaim,
    NexusKeyRequest,
    NexusOem,
    NexusOemInvite,
    NexusSession,
    NexusWallet,
)
from nexus.fleet import FleetError
from nexus.keys import hash_key, looks_like_key, normalize_key

# 会话有效期：7 天（OEM 门户是低频配置场景，不需要长会话；到期重登）
_SESSION_TTL_MS = 7 * 24 * 3600 * 1000
# pbkdf2 迭代次数：兼顾安全与单机 CPU（同步服务，别把登录搞太慢）
_PBKDF2_ITERS = 200_000
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _now_ms() -> int:
    return int(time.time() * 1000)


# ---------- 密码哈希（pbkdf2，标准库）----------

def hash_password(password: str) -> str:
    """派生密码存储串：``pbkdf2$<迭代>$<salt_hex>$<hash_hex>``。"""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERS)
    return f"pbkdf2${_PBKDF2_ITERS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """校验密码。用 compare_digest 常数时间比对，防计时侧信道。"""
    try:
        scheme, iters_s, salt_hex, hash_hex = stored.split("$", 3)
        if scheme != "pbkdf2":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters_s)
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


def password_problem(password: str) -> Optional[str]:
    """密码强度校验：返回问题描述（中文），合格返回 None。"""
    if not password or len(password) < 8:
        return "密码至少 8 位"
    if len(password) > 128:
        return "密码过长"
    if password.isdigit() or password.isalpha():
        return "密码需同时包含字母和数字"
    return None


# ---------- 账号注册 / 登录 / 会话 ----------

# 平台官方邀请码：平台直属（一级）OEM 注册时填它，层级树挂在平台根节点下
_ROOT_INVITE_CODE = "GUDUU"


def _resolve_inviter(s, inviter: str) -> Optional[int]:
    """把注册表单里的「邀请人」解析成 inviter_id。

    规则（负责人 2026-07-23 拍板：必填、填错不能注册）：
      - 空 → 拒绝（层级必须完整，大屏星球图不允许悬空节点）；
      - 官方码 GUDUU（不分大小写）→ None（平台直属）；
      - 其他 → 必须是已存在且状态正常的 OEM 邮箱，否则拒绝。
    """
    inviter = (inviter or "").strip()
    if not inviter:
        raise FleetError("NEXUS_INVITER_REQUIRED", "请填写邀请人邮箱（平台直接客户填 GUDUU）")
    if inviter.upper() == _ROOT_INVITE_CODE:
        return None
    row = s.execute(
        select(NexusOem).where(NexusOem.email == inviter.lower())
    ).scalar_one_or_none()
    if row is None or row.status != "active":
        # 不存在与被停用同文案：不给探测账号存在性的口子
        raise FleetError("NEXUS_INVITER_INVALID", "邀请人不存在或不可用，请与邀请你的人确认", 400)
    return int(row.id)


def register(
    s, email: str, password: str, name: str = "", inviter: str = ""
) -> Dict[str, Any]:
    """OEM 自助注册。邮箱唯一、密码有强度要求、邀请人必填且必须有效。"""
    email = (email or "").strip().lower()
    if not _EMAIL_RE.match(email):
        raise FleetError("NEXUS_BAD_EMAIL", "邮箱格式不正确")
    problem = password_problem(password)
    if problem:
        raise FleetError("NEXUS_WEAK_PASSWORD", problem)
    # 邀请人先于"邮箱已注册"校验：填错邀请人时不泄露目标邮箱是否已注册
    inviter_id = _resolve_inviter(s, inviter)
    exists = s.execute(
        select(NexusOem).where(NexusOem.email == email)
    ).scalar_one_or_none()
    if exists is not None:
        raise FleetError("NEXUS_EMAIL_TAKEN", "该邮箱已注册", 409)
    oem = NexusOem(
        email=email,
        password_hash=hash_password(password),
        name=(name or "").strip()[:120],
    )
    s.add(oem)
    s.flush()  # 拿自增 id
    # 落邀请边：每个账号恰一条（层级树数据源；inviter_id=None = 平台直属）
    s.add(NexusOemInvite(oem_id=oem.id, inviter_id=inviter_id))
    return public_oem(oem)


def login(s, email: str, password: str) -> Dict[str, Any]:
    """邮箱+密码登录。成功则签发一个会话令牌（明文仅此一次）。

    安全：账号不存在与密码错误返回同一个错误码/文案，不泄露"邮箱是否注册"。
    """
    email = (email or "").strip().lower()
    oem = s.execute(
        select(NexusOem).where(NexusOem.email == email)
    ).scalar_one_or_none()
    if oem is None or not verify_password(password, oem.password_hash):
        raise FleetError("NEXUS_BAD_CREDENTIALS", "邮箱或密码不正确", 401)
    if oem.status != "active":
        raise FleetError("NEXUS_OEM_DISABLED", "账号已被停用，请联系 GuDuu", 403)
    token = _issue_session(s, oem.id)
    return {"oem": public_oem(oem), "token": token}


def _issue_session(s, oem_id: int) -> str:
    """创建会话：库里只存 token 的 sha256，返回明文 token。"""
    token = secrets.token_urlsafe(32)
    s.add(
        NexusSession(
            token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
            oem_id=int(oem_id),
            expires_ts=_now_ms() + _SESSION_TTL_MS,
        )
    )
    return token


def resolve_session(s, token: str) -> Optional[NexusOem]:
    """令牌 → OEM 账号（校验存在/未过期/账号仍启用）。无效返回 None。"""
    if not token:
        return None
    th = hashlib.sha256(token.encode("utf-8")).hexdigest()
    sess = s.get(NexusSession, th)
    if sess is None or sess.expires_ts < _now_ms():
        return None
    oem = s.get(NexusOem, sess.oem_id)
    if oem is None or oem.status != "active":
        return None
    return oem


def logout(s, token: str) -> None:
    """登出：删除该会话（幂等）。"""
    if not token:
        return
    th = hashlib.sha256(token.encode("utf-8")).hexdigest()
    sess = s.get(NexusSession, th)
    if sess is not None:
        s.delete(sess)
        s.flush()  # 立即落 DELETE：同一会话内后续 resolve 不再命中 identity map


def public_oem(oem: NexusOem) -> Dict[str, Any]:
    """账号对外表示（绝不含 password_hash）。"""
    return {
        "id": oem.id,
        "email": oem.email,
        "name": oem.name,
        "status": oem.status,
        "created_ts": oem.created_ts,
    }


# ---------- KEY 认领（把一把 KEY 归到自己名下）----------

def claim_key(s, oem_id: int, raw_key: str) -> Dict[str, Any]:
    """OEM 认领一把 KEY（下单拿到 KEY 后在门户激活绑定到自己账号）。

    与 fleet.redeem 的区别：redeem 是**装机时**把 KEY 绑到域名/实例；claim 是
    把 KEY 的**归属**记到某个 OEM 账号名下（门户"我的实例"据此过滤）。二者独立：
    OEM 可以先认领 KEY 看到它，再在自己服务器装机兑换域名。幂等：自己已认领直接放行。
    """
    if not looks_like_key(raw_key):
        raise FleetError("NEXUS_BAD_KEY", "授权码格式不正确")
    key = s.execute(
        select(NexusKey).where(NexusKey.key_hash == hash_key(raw_key))
    ).scalar_one_or_none()
    if key is None:
        raise FleetError("NEXUS_KEY_NOT_FOUND", "授权码不存在", 404)
    if key.status != "active":
        raise FleetError("NEXUS_KEY_REVOKED", "授权码已被吊销", 403)
    claim = s.get(NexusKeyClaim, key.id)
    if claim is not None:
        if claim.oem_id == int(oem_id):
            return {"key_id": key.id, "tail": key.key_tail, "already": True}
        raise FleetError("NEXUS_KEY_CLAIMED", "该授权码已被其他账号认领", 409)
    s.add(NexusKeyClaim(key_id=key.id, oem_id=int(oem_id)))
    return {
        "key_id": key.id,
        "tail": key.key_tail,
        "token_grant": int(key.token_grant),
        "already": False,
    }


# ---------- 自有资源查询（服务端按 oem_id 过滤，OEM 只见自己）----------

def _owned_key_ids(s, oem_id: int) -> List[int]:
    return [
        int(kid)
        for (kid,) in s.execute(
            select(NexusKeyClaim.key_id).where(NexusKeyClaim.oem_id == int(oem_id))
        ).all()
    ]


def my_keys(s, oem_id: int) -> List[Dict[str, Any]]:
    """该 OEM 认领的所有 KEY（含是否已兑换开通、附赠额度）。"""
    ids = _owned_key_ids(s, oem_id)
    if not ids:
        return []
    rows = s.execute(
        select(NexusKey).where(NexusKey.id.in_(ids)).order_by(NexusKey.id.desc())
    ).scalars().all()
    return [
        {
            "id": r.id,
            "tail": r.key_tail,
            "status": r.status,
            "token_grant": int(r.token_grant),
            "instance_id": r.instance_id,
            "redeemed_ts": r.redeemed_ts,
            "created_ts": r.created_ts,
        }
        for r in rows
    ]


def my_instances(s, oem_id: int) -> List[Dict[str, Any]]:
    """该 OEM 名下已开通的实例 + 钱包余额（门户"我的实例"数据源）。"""
    ids = _owned_key_ids(s, oem_id)
    if not ids:
        return []
    rows = s.execute(
        select(NexusInstance)
        .where(NexusInstance.key_id.in_(ids))
        .order_by(NexusInstance.id.desc())
    ).scalars().all()
    out: List[Dict[str, Any]] = []
    for r in rows:
        wallet = s.get(NexusWallet, r.id)
        out.append(
            {
                "id": r.id,
                "domain": r.domain,
                "admin_email": r.admin_email,
                "status": r.status,
                "version": r.version,
                "created_ts": r.created_ts,
                "last_seen_ts": r.last_seen_ts,
                "balance_tokens": int(wallet.balance_tokens) if wallet else 0,
            }
        )
    return out


def list_oems(s) -> List[Dict[str, Any]]:
    """全部 OEM 账号 + 认领的 KEY 数（**超管**控制台"客户列表"数据源）。

    只给超管端点用（service.py 里挂在 /nexus/admin/ 下、走 NEXUS_ADMIN_TOKEN 鉴权），
    OEM 自己永远看不到别人。
    """
    rows = s.execute(select(NexusOem).order_by(NexusOem.id.desc())).scalars().all()
    # 一次查出每个 OEM 的认领数，避免 N+1
    counts: Dict[int, int] = {}
    for (oid,) in s.execute(select(NexusKeyClaim.oem_id)).all():
        counts[int(oid)] = counts.get(int(oid), 0) + 1
    # 邀请边一次拉全：oem_id → inviter_id（None=平台直属；无边=旧账号,视同直属）
    invites: Dict[int, Optional[int]] = {}
    for oid, iid in s.execute(
        select(NexusOemInvite.oem_id, NexusOemInvite.inviter_id)
    ).all():
        invites[int(oid)] = int(iid) if iid is not None else None
    emails = {r.id: r.email for r in rows}
    out = []
    for r in rows:
        iid = invites.get(r.id)
        out.append(
            {
                **public_oem(r),
                "keys_claimed": counts.get(r.id, 0),
                "inviter_id": iid,
                # 展示名：上线邮箱 / GuDuu(平台直属或历史账号)
                "inviter": emails.get(iid, f"#{iid}") if iid is not None else "GuDuu",
            }
        )
    return out


# ---------- 授权码申请闭环（OEM 申请 → 超管签发 → 门户交付明文）----------

# 同一 OEM 最多同时挂起的申请数（防手滑/刷单；正常客户一次买一两把）
_MAX_PENDING_REQUESTS = 3


def request_key(s, oem_id: int, note: str = "") -> Dict[str, Any]:
    """OEM 在门户提交一张授权码申请单（一单=一把 KEY）。"""
    pending = s.execute(
        select(NexusKeyRequest).where(
            NexusKeyRequest.oem_id == int(oem_id),
            NexusKeyRequest.status == "pending",
        )
    ).scalars().all()
    if len(pending) >= _MAX_PENDING_REQUESTS:
        raise FleetError(
            "NEXUS_TOO_MANY_REQUESTS",
            f"已有 {len(pending)} 张待处理申请，请等待平台处理后再提交",
            429,
        )
    row = NexusKeyRequest(oem_id=int(oem_id), note=(note or "").strip()[:500])
    s.add(row)
    s.flush()
    return _public_request(row)


def my_requests(s, oem_id: int) -> List[Dict[str, Any]]:
    """该 OEM 的申请单列表（含已批准单的 KEY 明文——这就是交付通道）。"""
    rows = s.execute(
        select(NexusKeyRequest)
        .where(NexusKeyRequest.oem_id == int(oem_id))
        .order_by(NexusKeyRequest.id.desc())
    ).scalars().all()
    return [_public_request(r) for r in rows]


def _public_request(r: NexusKeyRequest) -> Dict[str, Any]:
    return {
        "id": r.id,
        "oem_id": r.oem_id,
        "note": r.note,
        "status": r.status,
        "created_ts": r.created_ts,
        "decided_ts": r.decided_ts,
        "key_id": r.key_id,
        # 明文只在「已批准且尚未装机兑换」窗口内可见，兑换后被清空
        "key": r.key_plain or None,
        "decide_note": r.decide_note,
    }


def list_requests(s, status: str = "pending") -> List[Dict[str, Any]]:
    """超管视角的申请列表（默认只看待处理；带申请人邮箱便于辨认）。"""
    q = select(NexusKeyRequest).order_by(NexusKeyRequest.id.desc())
    if status:
        q = q.where(NexusKeyRequest.status == status)
    rows = s.execute(q).scalars().all()
    emails: Dict[int, str] = {}
    for r in rows:
        if r.oem_id not in emails:
            acc = s.get(NexusOem, r.oem_id)
            emails[r.oem_id] = acc.email if acc else f"#{r.oem_id}"
    out = []
    for r in rows:
        item = _public_request(r)
        item.pop("key", None)  # 超管列表不需要明文（交付走 OEM 门户）
        item["oem_email"] = emails.get(r.oem_id, "")
        out.append(item)
    return out


def decide_request(
    s, request_id: int, approve: bool, token_grant: int = 0, decide_note: str = ""
) -> Dict[str, Any]:
    """超管裁决申请：批准=签发一把 KEY 并自动认领到申请人名下 + 明文存单交付。

    延迟导入 fleet 避免模块级循环依赖（fleet 不知道 oem 层，反向单向依赖）。
    """
    from nexus import fleet

    row = s.get(NexusKeyRequest, int(request_id))
    if row is None:
        raise FleetError("NEXUS_REQUEST_NOT_FOUND", f"申请 #{request_id} 不存在", 404)
    if row.status != "pending":
        raise FleetError("NEXUS_REQUEST_DECIDED", "该申请已处理过", 409)
    row.decided_ts = _now_ms()
    row.decide_note = (decide_note or "").strip()[:200]
    if not approve:
        row.status = "rejected"
        return _public_request(row)
    issued = fleet.issue_keys(
        s, count=1, note=f"申请单#{row.id} · {row.note[:60]}", token_grant=token_grant
    )[0]
    row.status = "approved"
    row.key_id = issued["id"]
    row.key_plain = issued["key"]
    # 自动认领到申请人名下：申请→签发→归属一步到位，OEM 无需再手动认领
    s.add(NexusKeyClaim(key_id=issued["id"], oem_id=row.oem_id))
    return _public_request(row)


def clear_plain_by_key(s, raw_key: str) -> None:
    """按明文 KEY 清空所有申请单里存的交付明文（实例兑换成功后调用，幂等）。"""
    if not looks_like_key(raw_key):
        return
    key = s.execute(
        select(NexusKey).where(NexusKey.key_hash == hash_key(raw_key))
    ).scalar_one_or_none()
    if key is None:
        return
    for r in s.execute(
        select(NexusKeyRequest).where(NexusKeyRequest.key_id == key.id)
    ).scalars():
        r.key_plain = ""


def set_oem_status(s, oem_id: int, status: str) -> Dict[str, Any]:
    """超管停用/启用某个 OEM 账号（自助注册模式下的唯一管控抓手）。

    disabled 的效果（既有逻辑已生效，这里只负责切状态）：
      - 不能再登录（login 校验 status）；
      - 已发出的会话立即失效（resolve_session 校验 status）；
      - 已认领的 KEY/实例数据保留——误停可无损恢复。
    """
    if status not in ("active", "disabled"):
        raise FleetError("NEXUS_BAD_STATUS", "状态只能是 active 或 disabled")
    row = s.get(NexusOem, int(oem_id))
    if row is None:
        raise FleetError("NEXUS_OEM_NOT_FOUND", f"OEM id={oem_id} 不存在", 404)
    row.status = status
    return public_oem(row)


def owns_instance(s, oem_id: int, instance_id: int) -> bool:
    """校验某实例是否归该 OEM（写操作/充值申请前的归属守卫）。"""
    inst = s.get(NexusInstance, int(instance_id))
    if inst is None:
        return False
    claim = s.get(NexusKeyClaim, inst.key_id)
    return claim is not None and claim.oem_id == int(oem_id)


__all__ = [
    "hash_password",
    "verify_password",
    "password_problem",
    "register",
    "login",
    "resolve_session",
    "logout",
    "public_oem",
    "claim_key",
    "my_keys",
    "my_instances",
    "list_oems",
    "set_oem_status",
    "request_key",
    "my_requests",
    "list_requests",
    "decide_request",
    "clear_plain_by_key",
    "owns_instance",
    "normalize_key",
]
