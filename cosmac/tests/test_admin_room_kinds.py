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
from cosmac.db import init_engine


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


if __name__ == "__main__":
    unittest.main()
