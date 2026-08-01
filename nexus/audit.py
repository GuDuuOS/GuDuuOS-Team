"""Nexus 运营审计日志。

本模块只做两件事：把授权/KEY 等管理动作追加到不可变事件表，以及按业务对象读取时间线。
业务代码不应直接拼 ``NexusAuditEvent``，统一走这里可以保证来源 IP、状态变化和元数据的
截断/序列化规则一致。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from nexus.db import NexusAuditEvent


def record(
    s,
    *,
    object_type: str,
    object_id: int,
    action: str,
    actor_type: str = "system",
    actor_label: str = "",
    source_ip: str = "",
    from_state: str = "",
    to_state: str = "",
    note: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> NexusAuditEvent:
    """追加一条审计事件并返回 ORM 行。

    Args:
        s: 当前 SQLAlchemy Session，事件与业务修改共用事务，避免只改状态却漏记审计。
        object_type: 业务对象类型，例如 ``key_request`` 或 ``key``。
        object_id: 对象主键。
        action: 稳定的机器动作名，例如 ``approve``、``revoke``。
        actor_type: ``admin`` / ``oem`` / ``system``。
        actor_label: 当前可辨认的操作人；具名管理员上线前超管统一写平台超级管理员。
        source_ip: 服务端观察到的来源 IP；长度受限，避免伪造头灌库。
        from_state: 操作前状态。
        to_state: 操作后状态。
        note: 人类可读原因或补充说明。
        metadata: 不含密钥明文的结构化补充信息。
    """
    row = NexusAuditEvent(
        object_type=(object_type or "")[:32],
        object_id=int(object_id),
        action=(action or "")[:32],
        actor_type=(actor_type or "system")[:16],
        actor_label=(actor_label or "")[:120],
        source_ip=(source_ip or "")[:64],
        from_state=(from_state or "")[:32],
        to_state=(to_state or "")[:32],
        note=(note or "")[:2000],
        metadata_json=json.dumps(metadata or {}, ensure_ascii=False)[:4000],
    )
    s.add(row)
    return row


def timeline(s, object_type: str, object_id: int) -> List[Dict[str, Any]]:
    """按时间正序返回一个业务对象的完整审计时间线。"""
    rows = s.execute(
        select(NexusAuditEvent)
        .where(
            NexusAuditEvent.object_type == object_type,
            NexusAuditEvent.object_id == int(object_id),
        )
        .order_by(NexusAuditEvent.created_ts.asc(), NexusAuditEvent.id.asc())
    ).scalars().all()
    out: List[Dict[str, Any]] = []
    for row in rows:
        try:
            metadata = json.loads(row.metadata_json or "{}")
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        out.append(
            {
                "id": row.id,
                "action": row.action,
                "actor_type": row.actor_type,
                "actor_label": row.actor_label,
                "source_ip": row.source_ip,
                "from_state": row.from_state,
                "to_state": row.to_state,
                "note": row.note,
                "metadata": metadata,
                "created_ts": row.created_ts,
            }
        )
    return out


__all__ = ["record", "timeline"]
