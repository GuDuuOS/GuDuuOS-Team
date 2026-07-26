"""会员订单的数据访问（模块4 交易系统）。

只管订单表的增查 + **幂等地**把订单置 paid；会员开通（写 state event）由 trading.service 在
mark_paid 成功后做。金额用最小货币单位整数（分/cent）。
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from cosmac.db.models import Order


def create_order(
    session: Session,
    *,
    order_no: str,
    user_id: str,
    plan_slug: str,
    tier: str,
    period_days: int,
    amount_cents: int,
    currency: str,
    provider: str,
    provider_ref: str = "",
    kind: str = "member",
    tokens: int = 0,
) -> Order:
    """新建一笔待支付订单（status=created）。order_no 须唯一（调用方生成）。

    kind=member（会员套餐，默认）/ token（token 充值包，tokens=购买数量）。
    """
    order = Order(
        order_no=order_no,
        user_id=user_id,
        kind=kind or "member",
        plan_slug=plan_slug,
        tier=tier,
        period_days=int(period_days),
        tokens=int(tokens or 0),
        amount_cents=int(amount_cents),
        currency=(currency or "usd").lower(),
        provider=provider or "manual",
        provider_ref=provider_ref or "",
        status="created",
    )
    session.add(order)
    session.flush()
    return order


def get_by_order_no(session: Session, order_no: str) -> Optional[Order]:
    """按对外订单号取订单。"""
    return session.execute(
        select(Order).where(Order.order_no == order_no)
    ).scalar_one_or_none()


def mark_paid(
    session: Session,
    order_no: str,
    *,
    provider_ref: str = "",
    granted_expires_ts: int = 0,
    now: Optional[datetime] = None,
) -> bool:
    """**原子幂等**地把订单 created→paid。

    支付平台 webhook 可能重复回调；用带条件的 ``UPDATE ... WHERE status='created'`` 由 DB
    保证只有第一次成功（rowcount==1），后续重复回调 rowcount==0 → 返回 False，调用方据此
    **只开通一次会员**。返回 True 表示"本次真正完成了支付"。
    """
    res = session.execute(
        update(Order)
        .where(Order.order_no == order_no, Order.status == "created")
        .values(
            status="paid",
            paid_at=now or datetime.utcnow(),
            provider_ref=provider_ref or Order.provider_ref,
            granted_expires_ts=int(granted_expires_ts or 0),
        )
    )
    session.flush()
    return (res.rowcount or 0) == 1


def mark_failed(session: Session, order_no: str, *, reason: str = "") -> bool:
    """把仍 created 的订单置 failed（支付失败/取消）。已 paid 的不动。"""
    res = session.execute(
        update(Order)
        .where(Order.order_no == order_no, Order.status == "created")
        .values(status="failed")
    )
    session.flush()
    return (res.rowcount or 0) == 1


def revert_to_created(session: Session, order_no: str) -> bool:
    """把 paid 订单回滚成 created（仅当开通会员失败时用，留给平台/人工重试回调再开通）。

    避免"收了钱却没开会员"：mark_paid 成功后若 grant 失败，回滚订单状态，下次回调重做。
    """
    res = session.execute(
        update(Order)
        .where(Order.order_no == order_no, Order.status == "paid")
        .values(status="created", paid_at=None, granted_expires_ts=0)
    )
    session.flush()
    return (res.rowcount or 0) == 1


def recent_orders(
    session: Session, *, user_id: str = "", limit: int = 20
) -> List[Order]:
    """查最近订单（可按用户过滤），按时间倒序。"""
    stmt = select(Order)
    if user_id:
        stmt = stmt.where(Order.user_id == user_id)
    stmt = stmt.order_by(Order.id.desc()).limit(limit)
    return list(session.scalars(stmt).all())
