"""GuDuu OS 自己的数据层。

存什么、不存什么见 CLAUDE.md §3「数据存储分层」——一句话：
**Synapse 已经存的（聊天记录/成员/房间状态）绝不在这里重存**；
这里只放「AI 层自己的结构化/派生数据」：Skill / Agent 定义、知识库、群级记忆、
工作流/交易/个人主页等。

设计要点：
- 同步 SQLAlchemy（bot 是同步的 ThreadingHTTPServer + requests，DB 层也保持同步）。
- 连接由 COSMAC_DATABASE_URL 决定：生产指向独立 PostgreSQL，本地默认回退 SQLite
  文件 run/cosmac.db（零基建即可跑测试），见 ``engine.py``。

对外只暴露需要的几个名字，业务代码用 ``from cosmac.db import ...``。
"""

from __future__ import annotations

from cosmac.db.engine import (
    database_url,
    get_engine,
    get_session,
    init_engine,
    session_scope,
)
from cosmac.db.models import Agent, Base, Skill

__all__ = [
    "Base",
    "Skill",
    "Agent",
    "database_url",
    "init_engine",
    "get_engine",
    "get_session",
    "session_scope",
]
