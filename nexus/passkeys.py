"""Nexus 平台超级管理员的 WebAuthn / Passkey 服务。

这里负责生成和核验 WebAuthn 仪式、保存公钥凭据与一次性挑战。RP ID 和 Origin 只
从服务器环境变量读取，绝不采用请求 Host；否则伪造 Host 可能把管理员引到攻击者控制
的 relying party。浏览器设备里的私钥永远不会发送给 Nexus。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from typing import Any, Dict, List, Tuple

from sqlalchemy import delete, select
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from nexus import admin_auth, audit
from nexus.db import (
    NexusAdmin,
    NexusAdminPasskey,
    NexusAdminWebAuthnChallenge,
)
from nexus.fleet import FleetError

_CHALLENGE_TTL_MS = 5 * 60 * 1000


def _now_ms() -> int:
    """返回全服务统一使用的毫秒时间戳。"""
    return int(time.time() * 1000)


def _b64url(raw: bytes) -> str:
    """把二进制编码为 WebAuthn 使用的无填充 base64url。"""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64url(value: str) -> bytes:
    """解码无填充 base64url；畸形值统一由调用方转换成安全错误。"""
    value = str(value or "")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _hash(value: str) -> str:
    """将一次性仪式 ID 转换成数据库查询键，避免库中保存可直接使用的 ID。"""
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def config() -> Tuple[str, str, str]:
    """返回固定 RP ID、Origin 和展示名；缺配置时明确禁用 Passkey。"""
    rp_id = os.environ.get("NEXUS_WEBAUTHN_RP_ID", "").strip().lower()
    origin = os.environ.get("NEXUS_WEBAUTHN_ORIGIN", "").strip().rstrip("/")
    rp_name = os.environ.get("NEXUS_WEBAUTHN_RP_NAME", "GuDuu Nexus").strip()
    if not rp_id or not origin.startswith("https://"):
        raise FleetError(
            "NEXUS_PASSKEY_DISABLED",
            "Passkey 尚未配置正式管理域名",
            503,
        )
    # Origin 只能是协议+主机，不允许路径、查询或与 RP ID 无关的主机。
    expected_origin = f"https://{rp_id}"
    if origin != expected_origin:
        raise FleetError(
            "NEXUS_PASSKEY_CONFIG_INVALID",
            "Passkey Origin 必须与 RP ID 完全对应",
            503,
        )
    return rp_id, origin, rp_name or "GuDuu Nexus"


def enabled() -> bool:
    """供登录页探测 Passkey 是否已经具备生产配置。"""
    try:
        config()
        return True
    except FleetError:
        return False


def _credential_descriptor(row: NexusAdminPasskey) -> PublicKeyCredentialDescriptor:
    """把数据库凭据转换为生成 options 所需的公开描述。"""
    return PublicKeyCredentialDescriptor(id=_unb64url(row.credential_id))


def _save_challenge(s, admin_id: int, kind: str, challenge: bytes) -> str:
    """保存五分钟单次挑战并返回只给浏览器的随机仪式 ID。"""
    now = _now_ms()
    # 每次创建时顺手清理过期挑战，避免长期无人登录时表无限增长。
    s.execute(
        delete(NexusAdminWebAuthnChallenge).where(
            NexusAdminWebAuthnChallenge.expires_ts <= now
        )
    )
    ceremony_id = "nwc_" + secrets.token_urlsafe(32)
    s.add(
        NexusAdminWebAuthnChallenge(
            ceremony_hash=_hash(ceremony_id),
            admin_id=int(admin_id),
            kind=kind,
            challenge_b64=_b64url(challenge),
            created_ts=now,
            expires_ts=now + _CHALLENGE_TTL_MS,
        )
    )
    return ceremony_id


def _consume_challenge(s, ceremony_id: str, kind: str) -> Tuple[int, bytes]:
    """原子消费一次挑战，返回管理员 ID 与挑战；重复、过期和串用途全部拒绝。"""
    row = s.get(NexusAdminWebAuthnChallenge, _hash(ceremony_id))
    if row is None or row.kind != kind or int(row.expires_ts or 0) <= _now_ms():
        if row is not None:
            s.delete(row)
        raise FleetError(
            "NEXUS_PASSKEY_CHALLENGE_INVALID",
            "Passkey 请求已过期，请重新操作",
            400,
        )
    admin_id = int(row.admin_id)
    challenge = _unb64url(row.challenge_b64)
    # 先删除再做密码学验证：即便响应无效，也不能反复试同一挑战。
    s.delete(row)
    s.flush()
    return admin_id, challenge


def registration_options(s, admin_id: int) -> Dict[str, Any]:
    """为已登录管理员生成新增 Passkey 的注册参数。"""
    rp_id, _origin, rp_name = config()
    admin = s.get(NexusAdmin, int(admin_id))
    if admin is None or admin.status != "active":
        raise FleetError("NEXUS_ADMIN_NOT_FOUND", "管理员不存在或已停用", 404)
    rows = s.execute(
        select(NexusAdminPasskey).where(NexusAdminPasskey.admin_id == admin.id)
    ).scalars().all()
    challenge = secrets.token_bytes(32)
    options = generate_registration_options(
        rp_id=rp_id,
        rp_name=rp_name,
        user_id=f"nexus-admin:{admin.id}".encode("utf-8"),
        user_name=admin.username,
        user_display_name=admin.display_name,
        challenge=challenge,
        exclude_credentials=[_credential_descriptor(row) for row in rows],
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    return {
        "ceremony_id": _save_challenge(s, admin.id, "register", challenge),
        "public_key": json.loads(options_to_json(options)),
    }


def verify_registration(
    s,
    admin_id: int,
    ceremony_id: str,
    credential: Dict[str, Any],
    name: str,
    *,
    actor_label: str,
    source_ip: str = "",
) -> Dict[str, Any]:
    """核验注册签名并保存公钥；返回可展示的 Passkey 摘要。"""
    rp_id, origin, _rp_name = config()
    challenge_admin_id, challenge = _consume_challenge(
        s, ceremony_id, "register"
    )
    if challenge_admin_id != int(admin_id):
        raise FleetError("NEXUS_FORBIDDEN", "不能为其他管理员登记 Passkey", 403)
    try:
        verified = verify_registration_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=rp_id,
            expected_origin=origin,
            require_user_verification=True,
        )
    except Exception as exc:
        raise FleetError(
            "NEXUS_PASSKEY_VERIFY_FAILED",
            "Passkey 验证失败，请重新操作",
            400,
        ) from exc
    credential_id = _b64url(verified.credential_id)
    existing = s.execute(
        select(NexusAdminPasskey).where(
            NexusAdminPasskey.credential_id == credential_id
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise FleetError("NEXUS_PASSKEY_EXISTS", "这个 Passkey 已经登记", 409)
    safe_name = (name or "").strip()[:120] or "Passkey"
    transports = credential.get("response", {}).get("transports", [])
    transports = transports if isinstance(transports, list) else []
    row = NexusAdminPasskey(
        admin_id=int(admin_id),
        credential_id=credential_id,
        public_key=verified.credential_public_key,
        sign_count=int(verified.sign_count),
        name=safe_name,
        transports_json=json.dumps(transports, ensure_ascii=False),
    )
    s.add(row)
    s.flush()
    audit.record(
        s,
        object_type="admin_passkey",
        object_id=row.id,
        action="register",
        actor_type="admin",
        actor_label=actor_label,
        source_ip=source_ip,
        to_state="active",
        metadata={"name": safe_name},
    )
    return public_passkey(row)


def authentication_options(s, username: str) -> Dict[str, Any]:
    """为指定具名管理员生成 Passkey 登录参数，不泄露账号是否存在的细节。"""
    rp_id, _origin, _rp_name = config()
    normalized = (username or "").strip().lower()
    admin = s.execute(
        select(NexusAdmin).where(NexusAdmin.username == normalized)
    ).scalar_one_or_none()
    if admin is None or admin.status != "active":
        raise FleetError("NEXUS_PASSKEY_UNAVAILABLE", "该账号暂不能使用 Passkey", 400)
    rows = s.execute(
        select(NexusAdminPasskey).where(NexusAdminPasskey.admin_id == admin.id)
    ).scalars().all()
    if not rows:
        raise FleetError("NEXUS_PASSKEY_UNAVAILABLE", "该账号暂不能使用 Passkey", 400)
    challenge = secrets.token_bytes(32)
    options = generate_authentication_options(
        rp_id=rp_id,
        challenge=challenge,
        allow_credentials=[_credential_descriptor(row) for row in rows],
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return {
        "ceremony_id": _save_challenge(s, admin.id, "authenticate", challenge),
        "public_key": json.loads(options_to_json(options)),
    }


def verify_authentication(
    s,
    ceremony_id: str,
    credential: Dict[str, Any],
    *,
    source_ip: str = "",
) -> Dict[str, Any]:
    """核验 Passkey 登录断言，更新计数器并签发普通 12 小时管理会话。"""
    rp_id, origin, _rp_name = config()
    admin_id, challenge = _consume_challenge(s, ceremony_id, "authenticate")
    credential_id = str(credential.get("id") or "")
    row = s.execute(
        select(NexusAdminPasskey).where(
            NexusAdminPasskey.admin_id == admin_id,
            NexusAdminPasskey.credential_id == credential_id,
        )
    ).scalar_one_or_none()
    admin = s.get(NexusAdmin, admin_id)
    if row is None or admin is None or admin.status != "active":
        raise FleetError("NEXUS_PASSKEY_VERIFY_FAILED", "Passkey 验证失败", 401)
    try:
        verified = verify_authentication_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=rp_id,
            expected_origin=origin,
            credential_public_key=bytes(row.public_key),
            credential_current_sign_count=int(row.sign_count or 0),
            require_user_verification=True,
        )
    except Exception as exc:
        raise FleetError(
            "NEXUS_PASSKEY_VERIFY_FAILED", "Passkey 验证失败", 401
        ) from exc
    row.sign_count = int(verified.new_sign_count)
    row.last_used_ts = _now_ms()
    return admin_auth.issue_session(
        s,
        admin,
        source_ip=source_ip,
        token_prefix="nxp_",
        login_action="passkey_login",
    )


def public_passkey(row: NexusAdminPasskey) -> Dict[str, Any]:
    """返回管理页面需要的非敏感 Passkey 摘要。"""
    return {
        "id": int(row.id),
        "name": row.name,
        "created_ts": row.created_ts,
        "last_used_ts": row.last_used_ts,
    }


def list_passkeys(s, admin_id: int) -> List[Dict[str, Any]]:
    """列出当前管理员自己的 Passkey，不暴露公钥或 credential ID。"""
    rows = s.execute(
        select(NexusAdminPasskey)
        .where(NexusAdminPasskey.admin_id == int(admin_id))
        .order_by(NexusAdminPasskey.id.asc())
    ).scalars().all()
    return [public_passkey(row) for row in rows]


def delete_passkey(
    s,
    admin_id: int,
    passkey_id: int,
    *,
    actor_label: str,
    source_ip: str = "",
) -> None:
    """删除当前管理员自己的一个 Passkey；密码备用登录不受影响。"""
    row = s.get(NexusAdminPasskey, int(passkey_id))
    if row is None or int(row.admin_id) != int(admin_id):
        raise FleetError("NEXUS_PASSKEY_NOT_FOUND", "Passkey 不存在", 404)
    metadata = {"name": row.name}
    object_id = int(row.id)
    s.delete(row)
    audit.record(
        s,
        object_type="admin_passkey",
        object_id=object_id,
        action="delete",
        actor_type="admin",
        actor_label=actor_label,
        source_ip=source_ip,
        from_state="active",
        to_state="deleted",
        metadata=metadata,
    )
