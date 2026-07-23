# -*- coding: utf-8 -*-
"""「已获取的商城资源」数据访问(AI Agent 商城点「获取」的账号级记录)。

写:前端点「获取/移除」→ bot 端点 /cosmac/market/acquire → 这里 upsert/删除。
读:① 前端商城/我的AI工坊回显(list_acquired);② 主 AI 每条消息按发起人标注
   "他获取了哪些 AI 同事"(acquired_slugs,bot 侧带缓存,见 appservice_bot)。
"""

from __future__ import annotations

from typing import List, Set, Tuple

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from cosmac.db.models import MarketAcquisition

# 每人「已获取」条数上限:防脚本刷接口把表灌爆(正常人从上百个资源里挑不出这么多)
MAX_ACQUIRED_PER_USER = 200


def add_acquired(session: Session, *, user_id: str, kind: str, slug: str) -> bool:
    """记一条「已获取」。幂等:已存在直接返回 True。超每人上限返回 False。"""
    row = session.execute(
        select(MarketAcquisition).where(
            MarketAcquisition.user_id == user_id,
            MarketAcquisition.kind == kind,
            MarketAcquisition.slug == slug,
        )
    ).scalar_one_or_none()
    if row is not None:
        return True
    count = len(list_acquired(session, user_id))
    if count >= MAX_ACQUIRED_PER_USER:
        return False
    session.add(MarketAcquisition(user_id=user_id, kind=kind, slug=slug))
    return True


def remove_acquired(session: Session, *, user_id: str, kind: str, slug: str) -> None:
    """移除一条「已获取」(取消收藏)。不存在也算成功(幂等)。"""
    session.execute(
        delete(MarketAcquisition).where(
            MarketAcquisition.user_id == user_id,
            MarketAcquisition.kind == kind,
            MarketAcquisition.slug == slug,
        )
    )


def list_acquired(session: Session, user_id: str) -> List[Tuple[str, str]]:
    """列某用户全部已获取项,返回 [(kind, slug), ...]，**最近获取的在最前**。

    倒序是「我的AI工坊 · 已获取」的展示需要(负责人建议:刚获取的排最前,不用往下翻)。
    另两个调用方只用它做 set 判定与计数(配额),与顺序无关,故直接在这里定序。
    """
    rows = session.execute(
        select(MarketAcquisition)
        .where(MarketAcquisition.user_id == user_id)
        .order_by(MarketAcquisition.id.desc())
    ).scalars()
    return [(r.kind, r.slug) for r in rows]


def acquired_agent_slugs(session: Session, user_id: str) -> Set[str]:
    """只取某用户已获取的**智能体** slug 集合(主 AI 名册标注用,最热路径)。"""
    rows = session.execute(
        select(MarketAcquisition.slug).where(
            MarketAcquisition.user_id == user_id,
            MarketAcquisition.kind == "agent",
        )
    ).scalars()
    return {s for s in rows}
