"""任务看板的数据访问（AI 任务编排 · P1）。

主 AI 拆解目标 → create_tasks 批量落库；任务看板读 list_tasks；手动/自动改状态走 update_task。
P1 只做"拆解 + 看板 + 改状态"，派发执行与结果回填(P2)以后在此扩展。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from cosmac.db.models import Task

_VALID_STATUS = ("todo", "doing", "done")
_VALID_KIND = ("human", "agent", "workflow", "none")  # 类型化执行者（档2）
_MAX_TITLE = 2000
_MAX_TASKS = 30  # 一次拆解最多落这么多子任务，防失控


def _norm_kind(kind: Any) -> str:
    """规范化执行者类型：不在白名单的一律回落 none（防模型瞎填）。"""
    k = str(kind or "none").strip().lower()
    return k if k in _VALID_KIND else "none"


def create_tasks(
    session: Session,
    *,
    goal: str,
    items: List[Dict[str, Any]],
    room_id: str = "",
    sender: str = "",
    space_id: str = "",
) -> List[Task]:
    """把一批子任务落库。items: [{"title","assignee","executor_kind","executor_ref"}]。

    executor_kind/ref（档2）是主AI 读能力名册后填的类型化执行者；缺省/非法 kind 回落 none。
    space_id：所属工作区(Space room_id)，任务看板据它按工作区过滤；空=无归属(前端各处显示)。
    脏数据兜底：title 空的丢弃；超量截断到 _MAX_TASKS。
    """
    out: List[Task] = []
    for it in (items or [])[:_MAX_TASKS]:
        if not isinstance(it, dict):
            continue
        title = str(it.get("title") or "").strip()[:_MAX_TITLE]
        if not title:
            continue
        kind = _norm_kind(it.get("executor_kind"))
        ref = str(it.get("executor_ref") or "").strip()[:255]
        if kind == "none":
            ref = ""  # 未指派就不留 ref，避免悬空引用
        # 截止时间（epoch 秒，可空）：主 AI 拆任务时可给，非法/缺省 → None（无时限）。
        due_ts = None
        raw_due = it.get("due_ts")
        if raw_due is not None:
            try:
                due_ts = int(raw_due)
            except (TypeError, ValueError):
                due_ts = None
        t = Task(
            goal=str(goal or "")[:_MAX_TITLE],
            title=title,
            assignee=str(it.get("assignee") or "").strip()[:255],
            executor_kind=kind,
            executor_ref=ref,
            status="todo",
            progress=0,
            room_id=room_id or "",
            sender=sender or "",
            space_id=(space_id or "")[:255],
            due_ts=due_ts,
        )
        session.add(t)
        out.append(t)
    session.flush()
    return out


def list_tasks(
    session: Session,
    *,
    room_ids: Optional[List[str]] = None,
    sender: Optional[str] = None,
    limit: int = 200,
) -> List[Task]:
    """列出任务（按 id 倒序，新建在前）。单实例小规模，全列即可。

    越权防护：``room_ids``/``sender`` 任一非 None 时，只返回「属于这些房间」或「由本人下达」
    的任务（两者取并集）。两者都为 None 才返回全部——仅供平台管理员/内部统计调用，**不要**
    直接拿用户请求里的空作用域去调它，否则会泄露全平台任务。
    """
    stmt = select(Task)
    # 只要传了任一作用域，就收敛到「房间命中 ∪ 本人下达」；防止任意登录用户拉到全平台任务。
    if room_ids is not None or sender is not None:
        conds = []
        if room_ids:
            conds.append(Task.room_id.in_(room_ids))
        if sender:
            conds.append(Task.sender == sender)
        if not conds:
            # 作用域显式给了但为空（既不在任何房间、也无本人任务）→ 不返回任何东西。
            return []
        stmt = stmt.where(or_(*conds))
    return list(
        session.execute(
            stmt.order_by(Task.id.desc()).limit(limit)
        ).scalars().all()
    )


def list_tasks_for_user(
    session: Session, *, user_id: str, localpart: str, limit: int = 500,
) -> List[Task]:
    """列出**某用户可能可见**的任务（本人下达 ∪ 可能派给本人），按 id 倒序。

    专给任务看板用，修 #6：旧实现先 ``list_tasks()`` 全局取最新 200 条、再在 Python 里按人
    过滤——平台任务总数超过 200 后，某用户的任务会被别人的新任务挤出窗口而整块消失，违背
    「派给我的任务永远可见」。这里把过滤**下推到 DB**，limit 落在「本人相关任务」上而非全平台。

    executor_ref/assignee 的精确归属判定是模糊的（``_lp`` 提取 localpart、旧任务按 assignee
    首词兜底），纯 SQL 难精确表达。故这里用 ``LIKE '%localpart%'`` 做**宽松超集**匹配：返回集
    保证是调用方精确谓词(`_is_task_assignee`)的**超集**（凡 ``_lp(x)==localpart`` 者，x 必含
    localpart 子串），调用方**必须再用精确谓词收口**去掉过匹配项。宁可多取、绝不漏取。
    """
    lp = (localpart or "").strip().lower()
    conds = [Task.sender == user_id]
    if lp:
        like = f"%{lp}%"
        # 类型化执行者(human)：executor_ref 含本人 localpart（全 id/纯 localpart/带不带 @ 都覆盖）
        conds.append(and_(
            Task.executor_kind == "human",
            func.lower(func.coalesce(Task.executor_ref, "")).like(like),
        ))
        # 旧任务无 executor_ref：按 assignee 文本含本人 localpart 兜底
        conds.append(and_(
            or_(Task.executor_ref.is_(None), Task.executor_ref == ""),
            func.lower(func.coalesce(Task.assignee, "")).like(like),
        ))
    stmt = select(Task).where(or_(*conds)).order_by(Task.id.desc()).limit(limit)
    return list(session.execute(stmt).scalars().all())


def get_task(session: Session, task_id: int) -> Optional[Task]:
    """按 id 取单个任务（给改状态前做归属校验用）。不存在返回 None。"""
    return session.execute(
        select(Task).where(Task.id == task_id)
    ).scalars().first()


_DUE_UNSET = object()  # 哨兵：区分"不动 due_ts"与"显式清空为 None"


def update_task(
    session: Session,
    task_id: int,
    *,
    status: Optional[str] = None,
    progress: Optional[int] = None,
    result: Optional[str] = None,
    due_ts: Any = _DUE_UNSET,
    assignee: Optional[str] = None,
    executor_kind: Optional[str] = None,
    executor_ref: Optional[str] = None,
) -> bool:
    """改任务状态/进度/结果/截止时间/**执行者**（手动拖卡、AI 推进/审核回填、改派）。

    status 改成 done 时进度补满 100；从 done **重新打开**(改回 todo/doing)且没显式给
    进度时,把挂着的 100% 清回 0——重开的任务卡还显示 100% 会误导(负责人报的)。
    due_ts 传值（含 None=清空）会**重置 reminded=0**——新截止时间要重新计提醒。
    assignee/executor_kind/executor_ref：改派用（AI 把任务重新指派给别人/别的 AI 时,
    看板的责任人要跟着变,不能只改状态嘴上说改了派）。返回是否命中。
    """
    values: Dict[str, Any] = {}
    if status is not None and status in _VALID_STATUS:
        values["status"] = status
        if status == "done" and progress is None:
            values["progress"] = 100
        elif status != "done" and progress is None:
            # 重新打开：进度还挂 100% 的清回 0（其它进度值保留——暂停再继续别丢进度）
            t = session.get(Task, task_id)
            if t is not None and (t.progress or 0) >= 100:
                values["progress"] = 0
    if progress is not None:
        try:
            values["progress"] = max(0, min(100, int(progress)))
        except (TypeError, ValueError):
            pass
    if result is not None:
        values["result"] = str(result)[:_MAX_TITLE]
    if assignee is not None and str(assignee).strip():
        values["assignee"] = str(assignee).strip()[:255]
    if executor_kind is not None:
        values["executor_kind"] = _norm_kind(executor_kind)
    if executor_ref is not None:
        values["executor_ref"] = str(executor_ref).strip()[:255]
    if due_ts is not _DUE_UNSET:
        parsed = None
        if due_ts is not None:
            try:
                parsed = int(due_ts)
            except (TypeError, ValueError):
                parsed = None
        values["due_ts"] = parsed
        values["reminded"] = 0  # 截止时间变了 → 提醒去重位清零，重新计
    if not values:
        return False
    res = session.execute(
        update(Task).where(Task.id == task_id).values(**values)
    )
    session.flush()
    return (res.rowcount or 0) == 1


# —— 时效提醒（定时扫描用）：位掩码 bit0=快到期已提醒 / bit1=逾期已提醒 ——
REMIND_SOON = 1
REMIND_OVERDUE = 2


def tasks_needing_reminder(
    session: Session, *, now_ts: int, soon_secs: int
) -> List[Dict[str, Any]]:
    """扫出**需要发提醒**的任务（未完成 + 有截止时间 + 该档提醒还没发过）。

    返回 [{"task": Task, "kind": "soon"|"overdue"}]：
      · 逾期(now ≥ due) 且 未发过逾期提醒 → kind=overdue（优先于快到期）；
      · 未逾期但 now ≥ due-soon_secs 且 未发过快到期提醒 → kind=soon。
    只读；发完提醒由调用方调 mark_reminded 记位（避免重复打扰）。
    """
    out: List[Dict[str, Any]] = []
    rows = session.execute(
        select(Task).where(
            Task.status != "done",
            Task.due_ts.is_not(None),
        )
    ).scalars().all()
    for t in rows:
        due = t.due_ts
        if due is None:
            continue
        if now_ts >= due:
            if not (t.reminded & REMIND_OVERDUE):
                out.append({"task": t, "kind": "overdue"})
        elif now_ts >= due - soon_secs:
            if not (t.reminded & REMIND_SOON):
                out.append({"task": t, "kind": "soon"})
    return out


def rooms_all_tasks_done(session: Session) -> List[Dict[str, Any]]:
    """扫出**任务全部完成**的频道（归档催办用）。

    返回 [{"room_id", "total", "last_update_ts"}]：该频道有任务、且没有一条非 done；
    last_update_ts = 该频道任务的最近一次更新时刻（epoch 秒）——催办扫描用它实现
    「完成后 24h 没动静才开始催」（刚完成时 AI 已在对话里口头问过归档，别立刻叠着催）。
    只挑挂在真实频道上的任务（room_id 非空）；已归档与否由调用方读房间 state 判断
    （归档标记在 Matrix state event 里，DB 这边不知道）。
    """
    from sqlalchemy import case

    rows = session.execute(
        select(
            Task.room_id,
            func.count().label("total"),
            func.max(Task.updated_at).label("last_update"),
        )
        .where(Task.room_id != "")
        .group_by(Task.room_id)
        .having(func.sum(case((Task.status != "done", 1), else_=0)) == 0)
    ).all()
    out: List[Dict[str, Any]] = []
    for room_id, total, last_update in rows:
        ts = 0
        try:
            ts = int(last_update.timestamp()) if last_update is not None else 0
        except Exception:
            ts = 0
        out.append({"room_id": room_id, "total": int(total), "last_update_ts": ts})
    return out


def mark_reminded(session: Session, task_id: int, bit: int) -> None:
    """给某任务打上"已发某档提醒"的位（按位或），防止下次扫描重复提醒。"""
    t = session.get(Task, task_id)
    if t is None:
        return
    t.reminded = (t.reminded or 0) | int(bit)
    session.flush()
