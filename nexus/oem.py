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
    NexusOem,
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

def register(s, email: str, password: str, name: str = "") -> Dict[str, Any]:
    """OEM 自助注册。邮箱唯一、密码有强度要求。返回账号公开信息（不含密码）。"""
    email = (email or "").strip().lower()
    if not _EMAIL_RE.match(email):
        raise FleetError("NEXUS_BAD_EMAIL", "邮箱格式不正确")
    problem = password_problem(password)
    if problem:
        raise FleetError("NEXUS_WEAK_PASSWORD", problem)
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
    "owns_instance",
    "normalize_key",
]
