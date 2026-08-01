"""Nexus 具名超级管理员账号、登录会话与账号管理。

这个模块只处理平台主管身份，不承载任何 OEM 业务权限。数据库永远只保存密码派生串
与会话令牌哈希；明文密码和令牌只存在于当前请求内。原有 ``NEXUS_ADMIN_TOKEN``
由 HTTP 层继续作为应急入口，本模块不会读取或复制它。
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
from nexus.db import NexusAdmin, NexusAdminSession
from nexus.fleet import FleetError
from nexus.oem import hash_password, password_problem, verify_password

_SESSION_TTL_MS = 12 * 3600 * 1000
_RECOVERY_SESSION_TTL_MS = 30 * 60 * 1000
_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.@-]{3,80}$")


@dataclass(frozen=True)
class EmergencyAdmin:
    """服务器应急身份的只读描述，不对应真实人员账号。"""

    id: int = 0
    display_name: str = "服务器应急恢复"
    status: str = "active"


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


def create_admin(
    s,
    username: str,
    password: str,
    display_name: str,
    *,
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
    row = NexusAdmin(
        username=username,
        display_name=display_name,
        password_hash=hash_password(password),
        role="superadmin",
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
        metadata={"username": username, "display_name": display_name},
    )
    return public_admin(row)


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
    now = _now_ms()
    token = "nxa_" + secrets.token_urlsafe(36)
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
        action="login",
        actor_type="admin",
        actor_label=row.display_name,
        source_ip=source_ip,
        from_state="active",
        to_state="active",
    )
    return {"admin": public_admin(row), "token": token, "expires_ts": now + _SESSION_TTL_MS}


def issue_emergency_session(s) -> Dict[str, Any]:
    """签发 30 分钟应急恢复会话，浏览器不再长期持有服务器静态令牌。"""
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


def resolve_session(
    s, token: str, *, allow_emergency: bool = False
) -> Optional[Union[NexusAdmin, EmergencyAdmin]]:
    """解析有效会话；过期、停用或不存在时返回 ``None``。

    ``allow_emergency`` 由 HTTP 层根据服务器是否仍配置应急令牌决定。这样运维删除或
    轮换静态令牌后，已经签发的恢复 Cookie 也会立即失效。
    """
    if not token or not token.startswith(("nxa_", "nxr_")):
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
        if allow_emergency:
            return EmergencyAdmin()
        s.delete(session_row)
        s.commit()
        return None
    admin = s.get(NexusAdmin, session_row.admin_id)
    if admin is None or admin.status != "active":
        s.delete(session_row)
        s.commit()
        return None
    return admin


def logout(s, token: str) -> None:
    """撤销当前具名管理员会话；重复退出保持幂等。"""
    if token and token.startswith(("nxa_", "nxr_")):
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
    "create_admin",
    "issue_emergency_session",
    "list_admins",
    "login",
    "logout",
    "public_admin",
    "reset_password",
    "resolve_session",
    "set_status",
]
