"""token 钱包 + 流水账的数据访问（模块4 变现·Token 经济 P1）。

只管两张表的读写：钱包余额的**原子**增减 + 每笔变动追加一行流水。业务编排（倍率换算、
余额不足提示、充值开通）在上层 :mod:`cosmac.wallet` / trading 里做。

扣费原子性是命门：并发的回复线程/多房间可能同时给同一用户扣费。这里用**带余额守卫的
原子 UPDATE**（``balance = balance - :cost WHERE user_id=:u AND balance >= :cost``，看
rowcount 判成败），从根上避免"读余额→判断→写回"这种读改写竞态把余额扣穿（透支）。
单 bot 小规模，读回一次余额补记流水即可，不引入 SELECT FOR UPDATE 的额外复杂度。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from cosmac.db.models import TokenLedger, TokenWallet


def get_or_create(session: Session, user_id: str) -> TokenWallet:
    """取用户钱包；没有就建一个 0 余额的。"""
    w = session.execute(
        select(TokenWallet).where(TokenWallet.user_id == user_id)
    ).scalar_one_or_none()
    if w is None:
        w = TokenWallet(user_id=user_id, balance=0, total_in=0, total_out=0)
        session.add(w)
        session.flush()
    return w


def get_balance(session: Session, user_id: str) -> int:
    """读余额；无钱包=0。"""
    bal = session.execute(
        select(TokenWallet.balance).where(TokenWallet.user_id == user_id)
    ).scalar_one_or_none()
    return int(bal or 0)


def _append_ledger(
    session: Session,
    *,
    user_id: str,
    delta: int,
    reason: str,
    ref: str,
    balance_after: int,
    note: str,
    meta: Optional[Dict[str, Any]],
) -> TokenLedger:
    """追加一行流水（只增不改）。内部用，调用方已算好 balance_after。"""
    row = TokenLedger(
        user_id=user_id,
        delta=int(delta),
        reason=reason or "",
        ref=ref or "",
        balance_after=int(balance_after),
        note=note or "",
        meta=meta or {},
    )
    session.add(row)
    session.flush()
    return row


def credit(
    session: Session,
    user_id: str,
    amount: int,
    *,
    reason: str,
    ref: str = "",
    note: str = "",
    meta: Optional[Dict[str, Any]] = None,
) -> int:
    """入账（充值/赠送/退款/正向调整）：给余额 +amount，累计 total_in +amount，记流水。

    amount 必须 > 0（负向调整走 adjust_down / 直接用 try_debit）。返回入账后新余额。
    """
    amt = int(amount)
    if amt <= 0:
        raise ValueError("入账金额必须为正")
    w = get_or_create(session, user_id)
    # 原子自增：即便并发也不会丢入账（不读旧值再写回）
    session.execute(
        update(TokenWallet)
        .where(TokenWallet.user_id == user_id)
        .values(balance=TokenWallet.balance + amt, total_in=TokenWallet.total_in + amt)
    )
    session.flush()
    session.refresh(w)
    new_bal = int(w.balance)
    _append_ledger(
        session, user_id=user_id, delta=amt, reason=reason, ref=ref,
        balance_after=new_bal, note=note, meta=meta,
    )
    return new_bal


def try_debit(
    session: Session,
    user_id: str,
    amount: int,
    *,
    reason: str,
    ref: str = "",
    note: str = "",
    meta: Optional[Dict[str, Any]] = None,
) -> Optional[int]:
    """扣费（消费）：**原子守卫**扣 amount，够扣才扣、扣成记流水，返回扣后新余额；
    余额不足返回 None（不记流水、不改余额）。

    amount 允许为 0（免费/未产生用量时的空扣，直接返回当前余额、不记流水）。
    并发安全靠这条带 ``balance >= amount`` 守卫的原子 UPDATE + rowcount 判定。
    """
    amt = int(amount)
    if amt < 0:
        raise ValueError("扣费金额不能为负")
    get_or_create(session, user_id)  # 确保钱包存在（余额可能为 0）
    if amt == 0:
        return get_balance(session, user_id)
    # 关键：带余额守卫的原子扣减。rowcount==1 说明当时余额足够且已扣成；==0 说明不足。
    res = session.execute(
        update(TokenWallet)
        .where(TokenWallet.user_id == user_id, TokenWallet.balance >= amt)
        .values(balance=TokenWallet.balance - amt, total_out=TokenWallet.total_out + amt)
    )
    session.flush()
    if (res.rowcount or 0) < 1:
        return None  # 余额不足，未扣
    new_bal = get_balance(session, user_id)
    _append_ledger(
        session, user_id=user_id, delta=-amt, reason=reason, ref=ref,
        balance_after=new_bal, note=note, meta=meta,
    )
    return new_bal


def adjust(
    session: Session,
    user_id: str,
    delta: int,
    *,
    ref: str = "",
    note: str = "",
    meta: Optional[Dict[str, Any]] = None,
) -> Optional[int]:
    """管理员手动调整（可正可负），reason 恒为 adjust。

    正数走 credit；负数走 try_debit（余额不足则返回 None、不强行扣成负）。
    """
    if int(delta) >= 0:
        return credit(session, user_id, int(delta), reason="adjust", ref=ref, note=note, meta=meta)
    return try_debit(session, user_id, -int(delta), reason="adjust", ref=ref, note=note, meta=meta)


def list_ledger(
    session: Session, user_id: str, *, limit: int = 50, offset: int = 0
) -> List[TokenLedger]:
    """取某用户的流水（新→旧分页）。"""
    lim = max(1, min(int(limit), 200))
    off = max(0, int(offset))
    return list(
        session.execute(
            select(TokenLedger)
            .where(TokenLedger.user_id == user_id)
            .order_by(TokenLedger.id.desc())
            .limit(lim)
            .offset(off)
        ).scalars()
    )
