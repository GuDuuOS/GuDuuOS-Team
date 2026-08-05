"""Nexus 具名超级管理员账号、登录会话与账号管理。

这个模块只处理平台主管身份，不承载任何 OEM 业务权限。数据库永远只保存密码派生串、
会话令牌哈希与单次恢复码哈希；明文只存在当前请求或 SSH 命令输出中。
"""

from __future__ import annotations

import hashlib
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import delete, func, select

from nexus import audit
from nexus.db import NexusAdmin, NexusAdminRecoveryCode, NexusAdminSession
from nexus.fleet import FleetError
from nexus.oem import hash_password, password_problem, verify_password

_SESSION_TTL_MS = 12 * 3600 * 1000
_RECOVERY_SESSION_TTL_MS = 30 * 60 * 1000
_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.@-]{3,80}$")

ADMIN_ROLES = {
    "superadmin": "超级管理员",
    "operations": "运营管理员",
    "finance": "财务管理员",
    "release": "发布管理员",
    "auditor": "只读审计员",
}

_ROLE_PERMISSIONS = {
    "superadmin": {"*"},
    "operations": {"operations.read", "operations.write", "audit.read"},
    "finance": {"operations.read", "finance.read", "finance.write", "audit.read"},
    "release": {"operations.read", "release.read", "release.write", "audit.read"},
    # 审计员可核对所有业务面板，但永远不能提交管理写操作。
    "auditor": {
        "operations.read",
        "finance.read",
        "release.read",
        "security.read",
        "audit.read",
    },
}


@dataclass(frozen=True)
class RecoveryAdmin:
    """服务器单次恢复身份的只读描述，不对应真实人员账号。"""

    id: int = 0
    display_name: str = "服务器应急恢复"
    status: str = "active"
    role: str = "superadmin"


def _now_ms() -> int:
    """返回统一的毫秒时间戳。"""
    return int(time.time() * 1000)


def _token_hash(token: str) -> str:
    """把浏览器持有的管理员会话令牌转换为数据库查询键。"""
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def public_admin(row: NexusAdmin) -> Dict[str, Any]:
    """返回可安全发送到浏览器的管理员字段，不包含密码派生串。"""
    return {
        "id": int(row.id),
        "username": row.username,
        "display_name": row.display_name,
        "role": row.role,
        "role_label": ADMIN_ROLES.get(row.role, row.role),
        "status": row.status,
        "created_ts": row.created_ts,
        "password_changed_ts": row.password_changed_ts,
        "last_login_ts": row.last_login_ts,
    }


def active_count(s) -> int:
    """返回有效管理员数量，用于保护最后一个可用管理员。"""
    return int(
        s.execute(
            select(func.count()).select_from(NexusAdmin).where(
                NexusAdmin.status == "active"
            )
        ).scalar()
        or 0
    )


def active_superadmin_count(s) -> int:
    """返回仍可登录的超级管理员数量，防止误删最后一个总控入口。"""
    return int(
        s.execute(
            select(func.count()).select_from(NexusAdmin).where(
                NexusAdmin.status == "active",
                NexusAdmin.role == "superadmin",
            )
        ).scalar()
        or 0
    )


def normalize_role(role: str) -> str:
    """校验平台主管角色，拒绝浏览器自造的未知权限名。"""
    normalized = (role or "superadmin").strip().lower()
    if normalized not in ADMIN_ROLES:
        raise FleetError("NEXUS_ADMIN_ROLE_INVALID", "管理员角色不合法")
    return normalized


def has_permission(role: str, permission: str) -> bool:
    """判断角色是否拥有服务端权限；空权限仅代表完成登录。"""
    if not permission:
        return True
    granted = _ROLE_PERMISSIONS.get((role or "").strip().lower(), set())
    return "*" in granted or permission in granted


def role_permissions(role: str) -> List[str]:
    """返回前端可用于隐藏无权入口的权限列表，服务端仍是最终边界。"""
    granted = _ROLE_PERMISSIONS.get((role or "").strip().lower(), set())
    return ["*"] if "*" in granted else sorted(granted)


def create_admin(
    s,
    username: str,
    password: str,
    display_name: str,
    *,
    role: str = "superadmin",
    actor_label: str,
    source_ip: str = "",
) -> Dict[str, Any]:
    """创建一个具名超级管理员并写入不可变审计事件。"""
    username = (username or "").strip().lower()
    display_name = (display_name or "").strip()
    if not _USERNAME_RE.fullmatch(username):
        raise FleetError(
            "NEXUS_ADMIN_USERNAME_INVALID",
            "管理员账号需为 3-80 位字母、数字、点、横线或 @",
        )
    if not (2 <= len(display_name) <= 120):
        raise FleetError("NEXUS_ADMIN_NAME_INVALID", "请填写 2-120 位管理员显示名")
    problem = password_problem(password)
    if problem:
        raise FleetError("NEXUS_WEAK_PASSWORD", problem)
    exists = s.execute(
        select(NexusAdmin).where(NexusAdmin.username == username)
    ).scalar_one_or_none()
    if exists is not None:
        raise FleetError("NEXUS_ADMIN_EXISTS", "该管理员账号已存在", 409)
    normalized_role = normalize_role(role)
    row = NexusAdmin(
        username=username,
        display_name=display_name,
        password_hash=hash_password(password),
        role=normalized_role,
        status="active",
    )
    s.add(row)
    s.flush()
    audit.record(
        s,
        object_type="admin",
        object_id=row.id,
        action="create",
        actor_type="admin",
        actor_label=actor_label,
        source_ip=source_ip,
        to_state="active",
        metadata={
            "username": username,
            "display_name": display_name,
            "role": normalized_role,
        },
    )
    return public_admin(row)


def issue_session(
    s,
    row: NexusAdmin,
    *,
    source_ip: str = "",
    token_prefix: str = "nxa_",
    login_action: str = "login",
) -> Dict[str, Any]:
    """为已完成身份验证的管理员签发 12 小时会话。

    密码和 Passkey 共用这一个出口，确保会话时长、审计、最后登录时间完全一致；
    ``nxp_`` 前缀只用于后续向管理员展示当前登录方式，不改变权限。
    """
    now = _now_ms()
    token = token_prefix + secrets.token_urlsafe(36)
    s.add(
        NexusAdminSession(
            token_hash=_token_hash(token),
            admin_id=row.id,
            created_ts=now,
            expires_ts=now + _SESSION_TTL_MS,
        )
    )
    row.last_login_ts = now
    audit.record(
        s,
        object_type="admin",
        object_id=row.id,
        action=login_action,
        actor_type="admin",
        actor_label=row.display_name,
        source_ip=source_ip,
        from_state="active",
        to_state="active",
    )
    return {"admin": public_admin(row), "token": token, "expires_ts": now + _SESSION_TTL_MS}


def login(s, username: str, password: str, source_ip: str = "") -> Dict[str, Any]:
    """验证账号密码并签发 12 小时会话，成功登录同时记录真实操作人。"""
    normalized = (username or "").strip().lower()
    row = s.execute(
        select(NexusAdmin).where(NexusAdmin.username == normalized)
    ).scalar_one_or_none()
    if row is None or not verify_password(password, row.password_hash):
        raise FleetError("NEXUS_BAD_CREDENTIALS", "账号或密码不正确", 401)
    if row.status != "active":
        raise FleetError("NEXUS_ADMIN_DISABLED", "管理员账号已停用", 403)
    return issue_session(s, row, source_ip=source_ip)


def create_recovery_code(
    s, *, ttl_minutes: int = 15, created_by: str = "server_ssh"
) -> Dict[str, Any]:
    """创建一枚只能从 SSH 命令读取一次的恢复码。

    ``ttl_minutes`` 限制在 5-60 分钟，避免运维误传一个长期凭据。
    返回值中的 ``code`` 是惟一一次明文暴露，调用方不得写日志或文件。
    """
    ttl = int(ttl_minutes)
    if not 5 <= ttl <= 60:
        raise FleetError(
            "NEXUS_RECOVERY_TTL_INVALID", "恢复码有效期必须为 5-60 分钟"
        )
    now = _now_ms()
    code = "NXR-" + secrets.token_urlsafe(24)
    s.add(
        NexusAdminRecoveryCode(
            code_hash=_token_hash(code),
            created_ts=now,
            expires_ts=now + ttl * 60 * 1000,
            created_by=(created_by or "server_ssh")[:120],
        )
    )
    return {"code": code, "expires_ts": now + ttl * 60 * 1000}


def _issue_recovery_session(s) -> Dict[str, Any]:
    """签发 30 分钟恢复会话，仅在单次码消费成功后调用。"""
    now = _now_ms()
    token = "nxr_" + secrets.token_urlsafe(36)
    s.add(
        NexusAdminSession(
            token_hash=_token_hash(token),
            # 0 是保留的服务器应急身份，不会与自增的具名管理员主键冲突。
            admin_id=0,
            created_ts=now,
            expires_ts=now + _RECOVERY_SESSION_TTL_MS,
        )
    )
    return {"token": token, "expires_ts": now + _RECOVERY_SESSION_TTL_MS}


def consume_recovery_code(s, code: str) -> Dict[str, Any]:
    """原子消费恢复码并签发一个 30 分钟 HttpOnly 恢复会话。

    PostgreSQL 上使用行锁保证两个并发请求不能同时消费一枚码；
    过期、已用和不存在对外统一为无效，不提供凭据枚举信息。
    """
    submitted = (code or "").strip()
    if not submitted.startswith("NXR-") or len(submitted) < 24:
        raise FleetError("NEXUS_RECOVERY_INVALID", "恢复码无效或已过期", 401)
    row = s.execute(
        select(NexusAdminRecoveryCode)
        .where(NexusAdminRecoveryCode.code_hash == _token_hash(submitted))
        .with_for_update()
    ).scalar_one_or_none()
    now = _now_ms()
    if row is None or row.used_ts is not None or int(row.expires_ts or 0) <= now:
        raise FleetError("NEXUS_RECOVERY_INVALID", "恢复码无效或已过期", 401)
    row.used_ts = now
    return _issue_recovery_session(s)


def resolve_session(s, token: str) -> Optional[Union[NexusAdmin, RecoveryAdmin]]:
    """解析有效会话；过期、停用或不存在时返回 ``None``。

    ``nxr_`` 会话只能由已消费的 SSH 单次码签发，且最长 30 分钟，
    因此不再依赖或信任长期环境令牌。
    """
    if not token or not token.startswith(("nxa_", "nxp_", "nxr_")):
        return None
    session_row = s.get(NexusAdminSession, _token_hash(token))
    if session_row is None:
        return None
    now = _now_ms()
    if int(session_row.expires_ts or 0) <= now:
        s.delete(session_row)
        s.commit()
        return None
    if int(session_row.admin_id or 0) == 0:
        return RecoveryAdmin()
    admin = s.get(NexusAdmin, session_row.admin_id)
    if admin is None or admin.status != "active":
        s.delete(session_row)
        s.commit()
        return None
    return admin


def logout(s, token: str) -> None:
    """撤销当前具名管理员会话；重复退出保持幂等。"""
    if token and token.startswith(("nxa_", "nxp_", "nxr_")):
        row = s.get(NexusAdminSession, _token_hash(token))
        if row is not None:
            s.delete(row)


def list_admins(s) -> List[Dict[str, Any]]:
    """按创建顺序返回管理员安全摘要。"""
    rows = s.execute(select(NexusAdmin).order_by(NexusAdmin.id.asc())).scalars().all()
    return [public_admin(row) for row in rows]


def set_status(
    s,
    admin_id: int,
    status: str,
    *,
    actor_id: int,
    actor_label: str,
    source_ip: str = "",
) -> Dict[str, Any]:
    """启用或停用管理员；禁止自停用和停用最后一个有效管理员。"""
    if status not in ("active", "disabled"):
        raise FleetError("NEXUS_ADMIN_STATUS_INVALID", "管理员状态不合法")
    row = s.get(NexusAdmin, int(admin_id))
    if row is None:
        raise FleetError("NEXUS_ADMIN_NOT_FOUND", "管理员不存在", 404)
    if status == "disabled" and int(actor_id or 0) == int(row.id):
        raise FleetError("NEXUS_ADMIN_SELF_DISABLE", "不能停用当前登录账号", 409)
    if status == "disabled" and row.status == "active" and active_count(s) <= 1:
        raise FleetError("NEXUS_ADMIN_LAST_ACTIVE", "不能停用最后一个有效管理员", 409)
    if (
        status == "disabled"
        and row.status == "active"
        and row.role == "superadmin"
        and active_superadmin_count(s) <= 1
    ):
        raise FleetError(
            "NEXUS_ADMIN_LAST_SUPERADMIN", "不能停用最后一个有效超级管理员", 409
        )
    old = row.status
    row.status = status
    if status == "disabled":
        s.execute(delete(NexusAdminSession).where(NexusAdminSession.admin_id == row.id))
    audit.record(
        s,
        object_type="admin",
        object_id=row.id,
        action="enable" if status == "active" else "disable",
        actor_type="admin",
        actor_label=actor_label,
        source_ip=source_ip,
        from_state=old,
        to_state=status,
    )
    return public_admin(row)


def set_role(
    s,
    admin_id: int,
    role: str,
    *,
    actor_id: int,
    actor_label: str,
    source_ip: str = "",
) -> Dict[str, Any]:
    """修改管理员职责；禁止自降权或移除最后一个有效超级管理员。"""
    normalized = normalize_role(role)
    row = s.get(NexusAdmin, int(admin_id))
    if row is None:
        raise FleetError("NEXUS_ADMIN_NOT_FOUND", "管理员不存在", 404)
    if int(actor_id or 0) == int(row.id) and normalized != row.role:
        raise FleetError("NEXUS_ADMIN_SELF_ROLE", "不能修改当前登录账号自己的角色", 409)
    if (
        row.status == "active"
        and row.role == "superadmin"
        and normalized != "superadmin"
        and active_superadmin_count(s) <= 1
    ):
        raise FleetError(
            "NEXUS_ADMIN_LAST_SUPERADMIN", "不能移除最后一个有效超级管理员", 409
        )
    old = row.role
    row.role = normalized
    if old != normalized:
        s.execute(delete(NexusAdminSession).where(NexusAdminSession.admin_id == row.id))
        audit.record(
            s,
            object_type="admin",
            object_id=row.id,
            action="set_role",
            actor_type="admin",
            actor_label=actor_label,
            source_ip=source_ip,
            from_state=old,
            to_state=normalized,
        )
    return public_admin(row)


def reset_password(
    s,
    admin_id: int,
    new_password: str,
    *,
    actor_label: str,
    source_ip: str = "",
) -> Dict[str, Any]:
    """重置管理员密码并撤销其全部旧会话，强制使用新密码重新登录。"""
    problem = password_problem(new_password)
    if problem:
        raise FleetError("NEXUS_WEAK_PASSWORD", problem)
    row = s.get(NexusAdmin, int(admin_id))
    if row is None:
        raise FleetError("NEXUS_ADMIN_NOT_FOUND", "管理员不存在", 404)
    row.password_hash = hash_password(new_password)
    row.password_changed_ts = _now_ms()
    s.execute(delete(NexusAdminSession).where(NexusAdminSession.admin_id == row.id))
    audit.record(
        s,
        object_type="admin",
        object_id=row.id,
        action="reset_password",
        actor_type="admin",
        actor_label=actor_label,
        source_ip=source_ip,
        from_state=row.status,
        to_state=row.status,
    )
    return public_admin(row)


__all__ = [
    "active_count",
    "active_superadmin_count",
    "ADMIN_ROLES",
    "consume_recovery_code",
    "create_admin",
    "create_recovery_code",
    "list_admins",
    "login",
    "logout",
    "public_admin",
    "has_permission",
    "role_permissions",
    "reset_password",
    "resolve_session",
    "set_status",
    "set_role",
]
