"""Skill / Agent 的数据访问层（repository）。

业务代码（主 AI、管理后台接口等）通过这里读写，不直接写 SQL/查询语句，
这样作用域键（scope, scope_id, slug）的语义集中在一处、好维护。

约定：
- 函数都接收一个 ``Session``，调用方用 ``session_scope()`` 管理事务边界，
  方便把「建技能 + 建智能体」等多步操作放进同一个事务。
- ``upsert_*`` 按 (scope, scope_id, slug) 三元组定位：存在则**部分更新**（只改传入的字段），
  不存在则新建。只允许改白名单字段，防手滑写错列名。
"""

from __future__ import annotations

from typing import Any, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from cosmac.db.models import Agent, Skill

# 允许通过 upsert 修改的字段白名单（scope/scope_id/slug 是定位键、不在内；时间戳自动维护）
_SKILL_EDITABLE = {"name", "description", "instructions", "enabled"}
_AGENT_EDITABLE = {"name", "description", "system_prompt", "model", "skill_slugs",
                   "workflow_slugs", "enabled"}


# ───────────────────────── Skill ─────────────────────────

def get_skill(
    session: Session, scope: str, scope_id: str, slug: str
) -> Optional[Skill]:
    """按作用域三元组取一个技能，没有返回 None。"""
    stmt = select(Skill).where(
        Skill.scope == scope, Skill.scope_id == scope_id, Skill.slug == slug
    )
    return session.scalars(stmt).one_or_none()


def list_skills(
    session: Session,
    *,
    scope: Optional[str] = None,
    scope_id: Optional[str] = None,
    enabled_only: bool = False,
) -> List[Skill]:
    """列出技能，可按作用域、是否启用过滤；按 slug 排序，结果稳定。"""
    stmt = select(Skill)
    if scope is not None:
        stmt = stmt.where(Skill.scope == scope)
    if scope_id is not None:
        stmt = stmt.where(Skill.scope_id == scope_id)
    if enabled_only:
        stmt = stmt.where(Skill.enabled.is_(True))
    stmt = stmt.order_by(Skill.scope, Skill.scope_id, Skill.slug)
    return list(session.scalars(stmt).all())


def upsert_skill(
    session: Session, scope: str, scope_id: str, slug: str, **fields: Any
) -> Skill:
    """新建或部分更新一个技能（定位键 scope/scope_id/slug，其余走白名单）。"""
    _check_fields(fields, _SKILL_EDITABLE)
    obj = get_skill(session, scope, scope_id, slug)
    if obj is None:
        obj = Skill(scope=scope, scope_id=scope_id, slug=slug)
        session.add(obj)
    for key, val in fields.items():
        setattr(obj, key, val)
    session.flush()  # 让自增 id / 默认值就位，方便调用方立刻拿来用
    return obj


def delete_skill(session: Session, scope: str, scope_id: str, slug: str) -> bool:
    """删除一个技能；删掉返回 True，本来就不存在返回 False。"""
    obj = get_skill(session, scope, scope_id, slug)
    if obj is None:
        return False
    session.delete(obj)
    session.flush()
    return True


# ───────────────────────── Agent ─────────────────────────

def get_agent(
    session: Session, scope: str, scope_id: str, slug: str
) -> Optional[Agent]:
    """按作用域三元组取一个智能体，没有返回 None。"""
    stmt = select(Agent).where(
        Agent.scope == scope, Agent.scope_id == scope_id, Agent.slug == slug
    )
    return session.scalars(stmt).one_or_none()


def list_agents(
    session: Session,
    *,
    scope: Optional[str] = None,
    scope_id: Optional[str] = None,
    enabled_only: bool = False,
) -> List[Agent]:
    """列出智能体，可按作用域、是否启用过滤；按 slug 排序。"""
    stmt = select(Agent)
    if scope is not None:
        stmt = stmt.where(Agent.scope == scope)
    if scope_id is not None:
        stmt = stmt.where(Agent.scope_id == scope_id)
    if enabled_only:
        stmt = stmt.where(Agent.enabled.is_(True))
    stmt = stmt.order_by(Agent.scope, Agent.scope_id, Agent.slug)
    return list(session.scalars(stmt).all())


def upsert_agent(
    session: Session, scope: str, scope_id: str, slug: str, **fields: Any
) -> Agent:
    """新建或部分更新一个智能体（定位键 scope/scope_id/slug，其余走白名单）。"""
    _check_fields(fields, _AGENT_EDITABLE)
    obj = get_agent(session, scope, scope_id, slug)
    if obj is None:
        obj = Agent(scope=scope, scope_id=scope_id, slug=slug)
        session.add(obj)
    for key, val in fields.items():
        setattr(obj, key, val)
    session.flush()
    return obj


def delete_agent(session: Session, scope: str, scope_id: str, slug: str) -> bool:
    """删除一个智能体；删掉返回 True，本来就不存在返回 False。"""
    obj = get_agent(session, scope, scope_id, slug)
    if obj is None:
        return False
    session.delete(obj)
    session.flush()
    return True


# ───────────────────────── 内部工具 ─────────────────────────

def _check_fields(fields: dict, allowed: set) -> None:
    """挡住写错的列名：传了白名单外的字段就直接报错，别静默写丢。"""
    bad = set(fields) - allowed
    if bad:
        raise ValueError(
            f"不允许通过 upsert 修改这些字段：{sorted(bad)}；可改字段：{sorted(allowed)}"
        )
