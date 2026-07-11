"""员工花名册（人事 / HR 数据）的数据访问层。

给主 AI 的 ``query_hr`` 工具提供**只读**的查询与聚合能力：花名册筛选、人数编制、
薪酬统计、绩效分布/排名、考勤请假、入离职趋势、按人查档。

设计：
- 只读——不提供任何写接口（写数据走 seed 脚本 / 后台导入），杜绝 AI 误改人事数据。
- 聚合在 **Python 侧**完成：演示规模（~50 人）下加载全部行再算，最省事、跨
  SQLite/Postgres 行为一致，也便于把结果整理成给模型读的文字。
- 所有函数都吃一个 SQLAlchemy ``Session``（由调用方 ``session_scope()`` 管理事务）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from cosmac.db.models import Employee

# 默认返回上限（供模型工具 query_hr 用，防止把整表塞进上下文；不传 limit 即取它）。
_MAX_ROWS = 60
# 绝对硬上限：花名册**页面**(handle_hr_employees)要全量展示，显式传大 limit 时放行到这——
# 否则超 60 人后列表被静默截断，而 company_summary 统计的是全量，列表与汇总口径打架（L13）。
_MAX_PAGE_ROWS = 2000


def _norm(s: Optional[str]) -> str:
    """去空白的小工具；None 归一成空串。"""
    return (s or "").strip()


def to_dict(e: Employee) -> Dict[str, Any]:
    """把一条员工记录转成给工具/模型读的字典（字段名用中文语义友好键）。"""
    return {
        "工号": e.emp_no,
        "姓名": e.name,
        "性别": e.gender,
        "部门": e.department,
        "职位": e.title,
        "职级": e.level,
        "汇报对象": e.manager,
        "入职日期": e.hire_date,
        "在职状态": e.status,
        "离职日期": e.resign_date,
        "城市": e.city,
        "月薪": e.salary,
        "绩效": e.perf_rating,
        "年假总额": e.annual_leave_total,
        "已用年假": e.annual_leave_used,
        "本月请假天数": e.leave_days_month,
        "本月加班小时": e.overtime_hours_month,
        "学历": e.education,
        "生日": e.birth_date,
    }


def to_api_dict(e: Employee) -> Dict[str, Any]:
    """转成给**前端**用的字典（英文键，TS 侧类型友好）。字段与 to_dict 同源、键名英文。"""
    return {
        "emp_no": e.emp_no,
        "name": e.name,
        "gender": e.gender,
        "department": e.department,
        "title": e.title,
        "level": e.level,
        "manager": e.manager,
        "hire_date": e.hire_date,
        "status": e.status,
        "resign_date": e.resign_date,
        "city": e.city,
        "salary": e.salary,
        "perf_rating": e.perf_rating,
        "annual_leave_total": e.annual_leave_total,
        "annual_leave_used": e.annual_leave_used,
        "leave_days_month": e.leave_days_month,
        "overtime_hours_month": e.overtime_hours_month,
        "education": e.education,
        "birth_date": e.birth_date,
    }


def list_employees(
    session: Session,
    *,
    department: str = "",
    status: str = "",
    keyword: str = "",
    city: str = "",
    level: str = "",
    perf_rating: str = "",
    limit: int = _MAX_ROWS,
) -> List[Employee]:
    """按条件筛选花名册（模糊 + 精确混合）。

    - department/city/level/perf_rating：包含匹配（子串，忽略大小写不适用中文，直接子串）
    - status：精确匹配（active/probation/resigned），空=不限
    - keyword：在 姓名/职位/部门/工号 里模糊找
    结果按入职日期倒序（新在前），最多返回 ``limit`` 条。
    """
    dep = _norm(department)
    st = _norm(status)
    kw = _norm(keyword)
    ct = _norm(city)
    lv = _norm(level)
    pf = _norm(perf_rating).upper()

    stmt = select(Employee)
    if st:
        stmt = stmt.where(Employee.status == st)
    rows = list(session.scalars(stmt).all())

    def _match(e: Employee) -> bool:
        if dep and dep not in (e.department or ""):
            return False
        if ct and ct not in (e.city or ""):
            return False
        if lv and lv not in (e.level or ""):
            return False
        if pf and pf != (e.perf_rating or "").upper():
            return False
        if kw:
            hay = f"{e.name} {e.title} {e.department} {e.emp_no}"
            if kw not in hay:
                return False
        return True

    rows = [e for e in rows if _match(e)]
    # 入职日期字符串 YYYY-MM-DD 可直接字典序倒排
    rows.sort(key=lambda e: e.hire_date or "", reverse=True)
    # 默认 60（工具/上下文）；页面显式传大 limit 时放行到 _MAX_PAGE_ROWS（L13）。
    n = max(1, min(int(limit or _MAX_ROWS), _MAX_PAGE_ROWS))
    return rows[:n]


def _all(session: Session, *, only_active: bool = False) -> List[Employee]:
    """加载全部（或仅在职）员工，供聚合复用。"""
    rows = list(session.scalars(select(Employee)).all())
    if only_active:
        rows = [e for e in rows if e.status in ("active", "probation")]
    return rows


def headcount(
    session: Session, *, group_by: str = "department", include_resigned: bool = False
) -> Dict[str, Any]:
    """人数编制统计。

    group_by ∈ {department, status, city, level, title}；其它值按 department。
    默认只统计在职 + 试用期（不含离职）；include_resigned=True 时全算。
    返回 {"总人数": N, "分组": [{"名称":.., "人数":..}, ...], "维度": ".."}
    """
    rows = _all(session, only_active=not include_resigned)
    field_map = {
        "department": lambda e: e.department,
        "status": lambda e: e.status,
        "city": lambda e: e.city,
        "level": lambda e: e.level,
        "title": lambda e: e.title,
    }
    key = group_by if group_by in field_map else "department"
    getter = field_map[key]
    buckets: Dict[str, int] = {}
    for e in rows:
        g = getter(e) or "（未填）"
        buckets[g] = buckets.get(g, 0) + 1
    groups = [{"名称": k, "人数": v} for k, v in buckets.items()]
    groups.sort(key=lambda x: x["人数"], reverse=True)
    return {"总人数": len(rows), "维度": key, "分组": groups}


def salary_stats(
    session: Session, *, group_by: str = "department"
) -> Dict[str, Any]:
    """薪酬统计（仅在职 + 试用期）。

    返回整体 + 按 group_by（默认部门）分组的 人数/平均/最高/最低/月薪总额。
    平均值取整（元），便于口播。
    """
    rows = _all(session, only_active=True)
    field_map = {
        "department": lambda e: e.department,
        "level": lambda e: e.level,
        "city": lambda e: e.city,
    }
    key = group_by if group_by in field_map else "department"
    getter = field_map[key]

    def _stat(items: List[Employee]) -> Dict[str, Any]:
        sals = [e.salary for e in items if e.salary]
        if not sals:
            return {"人数": len(items), "平均月薪": 0, "最高": 0, "最低": 0, "月薪总额": 0}
        return {
            "人数": len(items),
            "平均月薪": round(sum(sals) / len(sals)),
            "最高": max(sals),
            "最低": min(sals),
            "月薪总额": sum(sals),
        }

    buckets: Dict[str, List[Employee]] = {}
    for e in rows:
        g = getter(e) or "（未填）"
        buckets.setdefault(g, []).append(e)
    groups = [{"名称": g, **_stat(items)} for g, items in buckets.items()]
    groups.sort(key=lambda x: x["平均月薪"], reverse=True)
    return {"维度": key, "整体": _stat(rows), "分组": groups}


def perf_distribution(
    session: Session, *, department: str = ""
) -> Dict[str, Any]:
    """绩效评级分布（仅在职 + 试用期）。可按部门过滤。

    返回各评级人数（S/A/B/C）+ 各评级占比 + 待改进（C）名单。
    """
    rows = _all(session, only_active=True)
    dep = _norm(department)
    if dep:
        rows = [e for e in rows if dep in (e.department or "")]
    order = ["S", "A", "B", "C"]
    dist: Dict[str, int] = {r: 0 for r in order}
    for e in rows:
        r = (e.perf_rating or "").upper()
        if r in dist:
            dist[r] += 1
    total = len(rows) or 1
    breakdown = [
        {"评级": r, "人数": dist[r], "占比": f"{round(dist[r] * 100 / total)}%"}
        for r in order
    ]
    c_list = [
        {"姓名": e.name, "部门": e.department, "职位": e.title}
        for e in rows
        if (e.perf_rating or "").upper() == "C"
    ]
    return {
        "范围": dep or "全公司",
        "统计人数": len(rows),
        "分布": breakdown,
        "待改进名单": c_list,
    }


def top_by(
    session: Session, *, field: str = "salary", n: int = 5, department: str = ""
) -> Dict[str, Any]:
    """按某数值字段取 Top N（仅在职 + 试用期）。

    field ∈ {salary 月薪, overtime 本月加班, leave 本月请假, tenure 司龄(按入职早晚)}。
    可按部门过滤。返回排行榜。
    """
    rows = _all(session, only_active=True)
    dep = _norm(department)
    if dep:
        rows = [e for e in rows if dep in (e.department or "")]
    n = max(1, min(int(n or 5), 20))

    def _fmt(e: Employee) -> str:
        """把当前排行维度的数值格式化成可读文字。"""
        if field in ("overtime", "加班"):
            return f"{e.overtime_hours_month} 小时"
        if field in ("leave", "请假"):
            return f"{e.leave_days_month} 天"
        if field in ("tenure", "司龄", "入职"):
            return f"入职于 {e.hire_date}"
        return f"{e.salary} 元/月"

    if field in ("overtime", "加班"):
        rows.sort(key=lambda e: e.overtime_hours_month, reverse=True)
        label = "本月加班"
    elif field in ("leave", "请假"):
        rows.sort(key=lambda e: e.leave_days_month, reverse=True)
        label = "本月请假"
    elif field in ("tenure", "司龄", "入职"):
        # 入职越早司龄越长——按 hire_date 升序
        rows.sort(key=lambda e: e.hire_date or "9999")
        label = "司龄（最资深）"
    else:  # 默认按月薪
        rows.sort(key=lambda e: e.salary, reverse=True)
        label = "月薪"

    ranking = [
        {
            "排名": i + 1,
            "姓名": e.name,
            "部门": e.department,
            "职位": e.title,
            "指标": _fmt(e),
        }
        for i, e in enumerate(rows[:n])
    ]
    return {"排行维度": label, "范围": dep or "全公司", "排行榜": ranking}


def joins_leaves(session: Session, *, months: int = 6) -> Dict[str, Any]:
    """近 N 个月的入职 / 离职趋势（按月）。

    以 hire_date / resign_date 的年月前缀（YYYY-MM）归组计数。
    返回按月份升序的 [{"月份":.., "入职":.., "离职":..}]。
    """
    rows = _all(session, only_active=False)
    joins: Dict[str, int] = {}
    leaves: Dict[str, int] = {}
    for e in rows:
        if e.hire_date and len(e.hire_date) >= 7:
            m = e.hire_date[:7]
            joins[m] = joins.get(m, 0) + 1
        if e.status == "resigned" and e.resign_date and len(e.resign_date) >= 7:
            m = e.resign_date[:7]
            leaves[m] = leaves.get(m, 0) + 1
    all_months = sorted(set(joins) | set(leaves))
    n = max(1, min(int(months or 6), 24))
    picked = all_months[-n:]
    series = [
        {"月份": m, "入职": joins.get(m, 0), "离职": leaves.get(m, 0)}
        for m in picked
    ]
    return {"月数": len(series), "趋势": series}


def company_summary(session: Session) -> Dict[str, Any]:
    """公司人事总览快照——AI 开场/兜底时给个全局概况。"""
    rows = _all(session, only_active=False)
    active = [e for e in rows if e.status == "active"]
    probation = [e for e in rows if e.status == "probation"]
    resigned = [e for e in rows if e.status == "resigned"]
    on_board = active + probation
    sals = [e.salary for e in on_board if e.salary]
    deps: Dict[str, int] = {}
    for e in on_board:
        deps[e.department] = deps.get(e.department, 0) + 1
    return {
        "在职人数": len(active),
        "试用期人数": len(probation),
        "已离职人数": len(resigned),
        "部门数": len(deps),
        "月薪总额": sum(sals),
        "人均月薪": round(sum(sals) / len(sals)) if sals else 0,
        "各部门人数": [{"名称": k, "人数": v} for k, v in
                     sorted(deps.items(), key=lambda x: x[1], reverse=True)],
    }
