"""创作者认证申请的数据访问（Token 经济 P3：申请/付费/审核）。

只管 cosmac_creator_application 一张表的读写与状态流转；业务编排（建认证费订单、
授予 creator 会员）在 bot 端点 / trading 里做。
"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from cosmac.db.models import CreatorApplication


def get_application(session: Session, user_id: str) -> Optional[CreatorApplication]:
    """取某用户的申请（一人一条）。"""
    return session.execute(
        select(CreatorApplication).where(CreatorApplication.user_id == user_id)
    ).scalar_one_or_none()


def submit(
    session: Session,
    *,
    user_id: str,
    name: str,
    contact: str,
    intro: str,
    portfolio: str,
) -> CreatorApplication:
    """提交/重新提交申请资料。

    状态流转（负责人定稿：拒绝不退费、可免费重新提交）：
      - 没有记录 → 新建，status=pending_payment（待付认证费）
      - rejected 且已付过费(paid) → 更新资料，直接回 pending_review（免费重提）
      - rejected 未付过费 → 更新资料，回 pending_payment（还没付过，仍要付）
      - pending_payment / pending_review → 就地更新资料，状态不变
      - approved → 不变（已是创作者，改资料无意义，调用方应拦）
    """
    row = get_application(session, user_id)
    if row is None:
        row = CreatorApplication(user_id=user_id, status="pending_payment")
        session.add(row)
    row.name = name
    row.contact = contact
    row.intro = intro
    row.portfolio = portfolio
    if row.status == "rejected":
        row.status = "pending_review" if row.paid else "pending_payment"
        row.reason = ""
    session.flush()
    return row


def mark_paid(session: Session, user_id: str, order_no: str) -> bool:
    """认证费支付成功：置 paid 并把 pending_payment → pending_review。

    幂等：重复回调时状态已不是 pending_payment，只确保 paid=True，不重复流转。
    """
    row = get_application(session, user_id)
    if row is None:
        return False
    row.paid = True
    row.order_no = order_no or row.order_no
    if row.status == "pending_payment":
        row.status = "pending_review"
    session.flush()
    return True


def review(
    session: Session, user_id: str, *, approve: bool, reason: str = ""
) -> Optional[CreatorApplication]:
    """管理员审核：approve=True → approved；False → rejected（记原因）。

    只允许审 pending_review 的（防止把 approved 的又拒了产生资格悬空）；
    状态不符返回 None，调用方转提示。
    """
    row = get_application(session, user_id)
    if row is None or row.status != "pending_review":
        return None
    row.status = "approved" if approve else "rejected"
    row.reason = "" if approve else (reason or "")[:500]
    session.flush()
    return row


def list_pending(session: Session, *, limit: int = 100) -> List[CreatorApplication]:
    """待审核申请列表（管理员后台用，旧→新：先来先审）。"""
    return list(session.execute(
        select(CreatorApplication)
        .where(CreatorApplication.status == "pending_review")
        .order_by(CreatorApplication.id.asc())
        .limit(max(1, min(int(limit), 500)))
    ).scalars())
