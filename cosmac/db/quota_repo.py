"""用量计数数据访问（模块4 变现第二步，rate 类指标）。

period_key 把"按天/按月"的额度切片：每天一个键、每月一个键，到期自然归零。
total 类（存量）不走这里——直接数现有实体行。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from cosmac.db.models import UsageCounter


def period_key(period: str, now: Optional[datetime] = None) -> str:
    """按周期算出计数键。day=YYYY-MM-DD / month=YYYY-MM / 其它=""（不分周期）。

    日/月的切换点按**产品时区**(tzutil,默认北京时间)——此前用 UTC,「当日额度」
    在北京时间早上 8 点才重置、0:00-8:00 的用量记进"昨天"(评审 #8);用户与运营
    都按北京时间理解"每日",账必须同一时钟。切换上线的那一天,旧 UTC 键的当日
    计数会被视作新的一天(用户当天额度小赚一次),一次性、可接受。
    """
    if now is None:
        from cosmac.tzutil import product_tz

        now = datetime.now(product_tz())
    if period == "day":
        return now.strftime("%Y-%m-%d")
    if period == "month":
        return now.strftime("%Y-%m")
    return ""


def get_count(session: Session, user_id: str, metric: str, pkey: str) -> int:
    """读某用户某计量项在某周期的已用量；无记录=0。"""
    row = session.scalars(
        select(UsageCounter).where(
            UsageCounter.user_id == user_id,
            UsageCounter.metric == metric,
            UsageCounter.period_key == pkey,
        ).limit(1)
    ).first()
    return int(row.count) if row else 0


def _ensure_counter(
    session: Session, user_id: str, metric: str, pkey: str
) -> None:
    """原子确保计数行存在；并发首次消费时只会成功插入一行。

    生产使用 PostgreSQL、本地与测试使用 SQLite，两者都原生支持
    ``INSERT ... ON CONFLICT DO NOTHING``。这里不能沿用“先查、没有再插”的写法：
    两个回复线程可能同时看到“没有”，随后撞唯一约束，导致其中一次计数失败并被上层
    fail-open 放行。把首次建行也做成原子 upsert，才能堵住周期第一笔用量的竞态窗口。
    """
    values = {
        "user_id": user_id,
        "metric": metric,
        "period_key": pkey,
        "count": 0,
    }
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        stmt = pg_insert(UsageCounter).values(**values).on_conflict_do_nothing(
            index_elements=["user_id", "metric", "period_key"]
        )
    elif dialect == "sqlite":
        stmt = sqlite_insert(UsageCounter).values(**values).on_conflict_do_nothing(
            index_elements=["user_id", "metric", "period_key"]
        )
    else:
        # 项目正式支持的数据库只有 PostgreSQL / SQLite。若以后增加新数据库，宁可明确
        # 报出“不支持原子计数”，也不能悄悄退回有并发漏洞的读改写实现。
        raise RuntimeError(f"不支持原子配额计数的数据库：{dialect}")
    session.execute(stmt)
    session.flush()


def incr(session: Session, user_id: str, metric: str, pkey: str, by: int = 1) -> int:
    """给某用户某计量项某周期的用量原子 ``+by``，返回新值（无则建行）。

    ``count = count + by`` 由数据库在一条 UPDATE 内完成；多个线程同时消费不会互相
    覆盖旧值。``by`` 必须为正，退款/回退若以后需要应另建带审计语义的明确接口。
    """
    amount = int(by)
    if amount <= 0:
        raise ValueError("配额增量必须为正")
    _ensure_counter(session, user_id, metric, pkey)
    session.execute(
        update(UsageCounter)
        .where(
            UsageCounter.user_id == user_id,
            UsageCounter.metric == metric,
            UsageCounter.period_key == pkey,
        )
        .values(count=UsageCounter.count + amount)
    )
    session.flush()
    return get_count(session, user_id, metric, pkey)


def consume_if_below(
    session: Session,
    user_id: str,
    metric: str,
    pkey: str,
    limit: int,
    by: int = 1,
) -> Optional[int]:
    """在不超过 ``limit`` 的前提下原子消费，成功返回新计数，额度不足返回 ``None``。

    关键守卫与自增放在同一条 SQL：
    ``UPDATE ... SET count=count+by WHERE count+by<=limit``。因此即使多个线程都曾读到
    “还有 1 次”，数据库最终也只允许一个线程拿到最后额度，不会出现检查通过后一起
    写穿上限。调用方可把 ``None`` 翻译成升级提示。
    """
    amount = int(by)
    ceiling = int(limit)
    if amount <= 0:
        raise ValueError("配额消费量必须为正")
    if ceiling < 0:
        raise ValueError("无限额项目不应调用原子限额消费")
    _ensure_counter(session, user_id, metric, pkey)
    result = session.execute(
        update(UsageCounter)
        .where(
            UsageCounter.user_id == user_id,
            UsageCounter.metric == metric,
            UsageCounter.period_key == pkey,
            UsageCounter.count + amount <= ceiling,
        )
        .values(count=UsageCounter.count + amount)
    )
    session.flush()
    if (result.rowcount or 0) < 1:
        return None
    return get_count(session, user_id, metric, pkey)
