"""普通用户 OEM 归属的本地可靠队列。

注册成功先写本地，Nexus 同步只是后续投递；这样网络抖动不会让已经创建的 Matrix 账号
失去归属。一个 user_id 只允许首次归属，重复注册重试保持幂等、不能偷偷改挂到别家。
"""

from __future__ import annotations

from datetime import datetime
from typing import List

from sqlalchemy import select
from sqlalchemy.orm import Session

from cosmac.db.models import OemUserAttribution


def enqueue(session: Session, *, user_id: str, referral_code: str) -> bool:
    """幂等登记待同步关系；新建返回 True，已有同关系返回 False。"""
    user = (user_id or "").strip()
    code = (referral_code or "").strip()
    if not user or not code:
        return False
    row = session.execute(
        select(OemUserAttribution).where(OemUserAttribution.user_id == user)
    ).scalar_one_or_none()
    if row is not None:
        # 首次归属不可改。调用方已在注册前验证链接；这里遇到不同码只保留原关系。
        return False
    session.add(OemUserAttribution(user_id=user, referral_code=code))
    return True


def pending(session: Session, limit: int = 50) -> List[OemUserAttribution]:
    """按创建顺序取待同步关系，限制批量避免一次心跳占用太久。"""
    return list(
        session.execute(
            select(OemUserAttribution)
            .where(OemUserAttribution.status == "pending")
            .order_by(OemUserAttribution.id.asc())
            .limit(max(1, min(int(limit), 200)))
        ).scalars()
    )


def mark_synced(row: OemUserAttribution) -> None:
    """标记 Nexus 已确认，保留关系作为本地审计。"""
    row.status = "synced"
    row.attempts += 1
    row.last_error = ""
    row.synced_at = datetime.utcnow()


def mark_failed(row: OemUserAttribution, error: str, *, permanent: bool) -> None:
    """记录投递失败；永久 4xx 标 rejected，网络/5xx 保持 pending 供心跳重试。"""
    row.attempts += 1
    row.last_error = (error or "同步失败")[:300]
    if permanent:
        row.status = "rejected"


__all__ = ["enqueue", "pending", "mark_synced", "mark_failed"]
