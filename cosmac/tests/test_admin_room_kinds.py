# -*- coding: utf-8 -*-
"""后台批量房型判定单测(负责人实报:频道管理把中枢AI会话/私信当频道统计)。

handle_admin_room_kinds:仅平台管理员;经 admin_room_state 读房型标记
(m.space / cosmac.ai_session / cosmac.dm),其余为 channel;永久缓存;
读不出 fail-open 按 channel(宁可多显示不藏房)。

运行:.venv/bin/python -m unittest cosmac.tests.test_admin_room_kinds
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, List, Optional

from cosmac.bots.appservice_bot import CosmacBot
from cosmac.config import CosmacConfig
from cosmac.db import init_engine, session_scope
from cosmac.db.models import Agent, KnowledgeChunk, KnowledgeDoc, Skill


class _C:
    def __init__(self) -> None:
        self.state_calls: List[str] = []
        # m.room.create 带 origin_server_ts:既判 space 也顺手取建房时间(后台按它倒序)
        self.states: Dict[str, List[Dict[str, Any]]] = {
            "!space:h": [{"type": "m.room.create", "origin_server_ts": 1000,
                          "content": {"type": "m.space"}}],
            "!ai:h": [{"type": "m.room.create", "origin_server_ts": 2000, "content": {}},
                      {"type": "cosmac.ai_session", "content": {"kind": "ai"}}],
            "!dm:h": [{"type": "m.room.create", "origin_server_ts": 3000, "content": {}},
                      {"type": "cosmac.dm", "content": {"direct": True}}],
            "!ch:h": [{"type": "m.room.create", "origin_server_ts": 4000, "content": {}},
                      {"type": "m.room.name", "content": {"name": "真频道"}}],
        }

    def admin_room_state(self, room_id: str) -> Optional[List[Dict[str, Any]]]:
        self.state_calls.append(room_id)
        return self.states.get(room_id)  # 未知房返回 None(读不出)

    def admin_list_room_ids(self) -> List[str]:
        """模拟 Synapse Admin API 返回完整房间清单。"""
        return list(self.states)

    def whoami(self, t):
        return "@admin:h"

    def resolve_alias(self, a):
        return None

    def set_displayname(self, *a, **k):
        pass

    def get_state_event(self, *a, **k):
        return None


def _bot(is_admin: bool = True) -> CosmacBot:
    bot = CosmacBot(CosmacConfig(llm_provider="echo", server_name="h"))
    bot.client = _C()  # type: ignore
    bot._is_platform_admin = lambda uid: is_admin  # type: ignore
    CosmacBot._admin_kind_cache = {}  # 类级缓存逐测重置
    CosmacBot._admin_created_cache = {}
    return bot


class TestAdminRoomKinds(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)

    def test_classifies_all_kinds(self) -> None:
        bot = _bot()
        code, out = bot.handle_admin_room_kinds("tok", {
            "room_ids": ["!space:h", "!ai:h", "!dm:h", "!ch:h", "!unknown:h"]})
        self.assertEqual(code, 200)
        k = out["kinds"]
        self.assertEqual(k["!space:h"], "space")
        self.assertEqual(k["!ai:h"], "ai")       # 中枢AI会话房——不是频道
        self.assertEqual(k["!dm:h"], "dm")       # 私信——不是频道
        self.assertEqual(k["!ch:h"], "channel")
        self.assertEqual(k["!unknown:h"], "channel")  # 读不出 fail-open
        # 同一趟带回建房时间(供后台按创建时间倒序):普通频道也能拿到(旧版判到标记就 break,
        # 普通频道走不到 create 行——本测锁死这个回归)。
        c = out["created"]
        self.assertEqual(c["!ch:h"], 4000)
        self.assertEqual(c["!ai:h"], 2000)
        self.assertEqual(c["!space:h"], 1000)
        self.assertEqual(c["!unknown:h"], 0)  # 读不出给 0(排序沉底)

    def test_cache_avoids_refetch(self) -> None:
        bot = _bot()
        bot.handle_admin_room_kinds("tok", {"room_ids": ["!ch:h", "!ai:h"]})
        calls_first = len(bot.client.state_calls)
        bot.handle_admin_room_kinds("tok", {"room_ids": ["!ch:h", "!ai:h"]})
        self.assertEqual(len(bot.client.state_calls), calls_first)  # 第二次零网络

    def test_admin_only(self) -> None:
        bot = _bot(is_admin=False)
        code, _ = bot.handle_admin_room_kinds("tok", {"room_ids": ["!ch:h"]})
        self.assertEqual(code, 403)

    def test_operating_stats_counts_real_room_kinds(self) -> None:
        """节点心跳沿用后台房型规则，业务频道不能混入空间、AI 会话或私聊。"""
        out = _bot().operating_stats()
        self.assertEqual(out["channels_total"], 1)
        self.assertEqual(out["spaces_total"], 1)
        self.assertEqual(out["ai_rooms_total"], 1)
        self.assertEqual(out["dm_rooms_total"], 1)

    def test_operating_stats_counts_database_assets(self) -> None:
        """知识库、分块和自建 Skill/Agent 全部来自真实 cosmac 数据表。"""
        with session_scope() as session:
            session.add_all([
                Skill(scope="global", scope_id="", slug="enabled", enabled=True),
                Skill(scope="global", scope_id="", slug="disabled", enabled=False),
                Agent(scope="global", scope_id="", slug="enabled", enabled=True),
                Agent(scope="global", scope_id="", slug="disabled", enabled=False),
            ])
            first = KnowledgeDoc(scope="room", scope_id="!ch:h", title="频道知识")
            second = KnowledgeDoc(scope="user", scope_id="@alice:h", title="个人知识")
            third = KnowledgeDoc(scope="room", scope_id="!ch:h", title="同库第二篇")
            session.add_all([first, second, third])
            session.flush()
            session.add_all([
                KnowledgeChunk(
                    doc_id=first.id, scope=first.scope, scope_id=first.scope_id,
                    ordinal=0, text="第一块",
                ),
                KnowledgeChunk(
                    doc_id=second.id, scope=second.scope, scope_id=second.scope_id,
                    ordinal=0, text="第二块",
                ),
            ])
        out = _bot().operating_stats()
        self.assertEqual(out["skills_custom_total"], 2)
        self.assertEqual(out["skills_custom_enabled"], 1)
        self.assertEqual(out["agents_custom_total"], 2)
        self.assertEqual(out["agents_custom_enabled"], 1)
        self.assertEqual(out["knowledge_bases_total"], 2)
        self.assertEqual(out["kb_docs"], 3)
        self.assertEqual(out["kb_chunks"], 2)

    def test_operating_stats_counts_workflow_definitions(self) -> None:
        """工作流定义来自控制室 state，停用项保留在总数但不计入启用数。"""
        bot = _bot()
        bot.client.resolve_alias = lambda alias: "!control:h"  # type: ignore
        bot.client.get_state_event = lambda *args: {  # type: ignore
            "workflows": [
                {"slug": "a", "enabled": True},
                {"slug": "b", "enabled": False},
                {"slug": "c"},
            ]
        }
        out = bot.operating_stats()
        self.assertEqual(out["workflows_total"], 3)
        self.assertEqual(out["workflows_enabled"], 2)


if __name__ == "__main__":
    unittest.main()
