"""销售业绩（销售额 / 签单 / 业绩完成率）的数据访问层。

给主 AI 的 ``query_sales`` 工具提供**只读**查询与聚合：月度概况、排行榜、趋势、
目标完成率、按人查业绩。只读——写数据走 seed 脚本，杜绝 AI 误改。

聚合在 Python 侧完成（数据量小：~5 销售 × 6 月）；跨 SQLite/PG 一致。
"""

from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from cosmac.db.models import SalesRecord


def _rate(actual: int, target: int) -> float:
    """业绩完成率 = 实际 / 目标；目标为 0 时按 0 处理。"""
    return round(actual / target, 3) if target else 0.0


def _pct(actual: int, target: int) -> str:
    """完成率的百分比文字（如 ``112%``）。"""
    return f"{round(_rate(actual, target) * 100)}%" if target else "—"


def latest_period(session: Session) -> str:
    """最近一个有数据的月份（YYYY-MM）；无数据返回空串。"""
    rows = session.scalars(select(SalesRecord.period)).all()
    return max(rows) if rows else ""


def _rows(session: Session, *, period: str = "") -> List[SalesRecord]:
    """取某月（默认全部）的业绩记录。"""
    stmt = select(SalesRecord)
    if period:
        stmt = stmt.where(SalesRecord.period == period)
    return list(session.scalars(stmt).all())


def monthly_summary(session: Session, *, period: str = "") -> Dict[str, Any]:
    """某月销售概况（默认最近月）：团队总目标/总销售额/总签单/整体完成率 + 每人明细。"""
    p = period or latest_period(session)
    rows = _rows(session, period=p)
    tot_target = sum(r.target for r in rows)
    tot_actual = sum(r.actual for r in rows)
    tot_deals = sum(r.deals for r in rows)
    people = [
        {
            "姓名": r.name, "目标": r.target, "销售额": r.actual,
            "签单数": r.deals, "新增客户": r.new_customers,
            "完成率": _pct(r.actual, r.target),
        }
        for r in sorted(rows, key=lambda x: x.actual, reverse=True)
    ]
    return {
        "月份": p,
        "团队目标": tot_target,
        "团队销售额": tot_actual,
        "团队签单数": tot_deals,
        "整体完成率": _pct(tot_actual, tot_target),
        "人数": len(rows),
        "每人明细": people,
    }


def ranking(
    session: Session, *, period: str = "", by: str = "actual", n: int = 5
) -> Dict[str, Any]:
    """某月销售排行榜。by ∈ {actual 销售额, completion 完成率, deals 签单数}。"""
    p = period or latest_period(session)
    rows = _rows(session, period=p)
    n = max(1, min(int(n or 5), 20))
    if by in ("completion", "完成率", "达成率"):
        rows.sort(key=lambda r: _rate(r.actual, r.target), reverse=True)
        label = "业绩完成率"
        val = lambda r: _pct(r.actual, r.target)  # noqa: E731
    elif by in ("deals", "签单", "签单数"):
        rows.sort(key=lambda r: r.deals, reverse=True)
        label = "签单数"
        val = lambda r: f"{r.deals} 单"  # noqa: E731
    else:
        rows.sort(key=lambda r: r.actual, reverse=True)
        label = "销售额"
        val = lambda r: f"¥{r.actual:,}"  # noqa: E731
    board = [
        {"排名": i + 1, "姓名": r.name, "指标": val(r),
         "销售额": r.actual, "完成率": _pct(r.actual, r.target)}
        for i, r in enumerate(rows[:n])
    ]
    return {"月份": p, "排行维度": label, "排行榜": board}


def trend(session: Session, *, months: int = 6) -> Dict[str, Any]:
    """近 N 个月团队销售趋势：每月总销售额 / 总目标 / 完成率 / 签单数。"""
    all_rows = _rows(session)
    by_period: Dict[str, List[SalesRecord]] = {}
    for r in all_rows:
        by_period.setdefault(r.period, []).append(r)
    periods = sorted(by_period)
    n = max(1, min(int(months or 6), 24))
    picked = periods[-n:]
    series = []
    for p in picked:
        rs = by_period[p]
        ta = sum(x.actual for x in rs)
        tt = sum(x.target for x in rs)
        series.append({
            "月份": p, "销售额": ta, "目标": tt,
            "完成率": _pct(ta, tt), "签单数": sum(x.deals for x in rs),
        })
    return {"月数": len(series), "趋势": series}


def person(session: Session, *, keyword: str, months: int = 6) -> Dict[str, Any]:
    """按姓名/工号查某销售员近 N 个月的业绩明细。"""
    kw = (keyword or "").strip()
    if not kw:
        return {}
    rows = [
        r for r in _rows(session)
        if kw in (r.name or "") or kw == (r.emp_no or "")
    ]
    rows.sort(key=lambda r: r.period)
    n = max(1, min(int(months or 6), 24))
    rows = rows[-n:]
    if not rows:
        return {}
    return {
        "姓名": rows[-1].name,
        "工号": rows[-1].emp_no,
        "近月业绩": [
            {"月份": r.period, "目标": r.target, "销售额": r.actual,
             "签单数": r.deals, "完成率": _pct(r.actual, r.target)}
            for r in rows
        ],
    }


def to_api_dict(r: SalesRecord) -> Dict[str, Any]:
    """给前端用的字典（英文键 + 完成率）。"""
    return {
        "emp_no": r.emp_no, "name": r.name, "department": r.department,
        "period": r.period, "target": r.target, "actual": r.actual,
        "deals": r.deals, "new_customers": r.new_customers,
        "completion": _pct(r.actual, r.target),
    }


def api_overview(session: Session, *, period: str = "") -> Dict[str, Any]:
    """给前端「销售业绩」面板用：某月概况 + 排行 + 趋势打包。"""
    p = period or latest_period(session)
    return {
        "period": p,
        "summary": monthly_summary(session, period=p),
        "ranking": ranking(session, period=p, by="actual", n=10),
        "trend": trend(session, months=6),
    }


def has_data(session: Session) -> bool:
    """是否已有销售数据（工具兜底用）。"""
    return session.scalars(select(SalesRecord.id).limit(1)).first() is not None
