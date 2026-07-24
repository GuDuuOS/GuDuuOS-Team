# -*- coding: utf-8 -*-
"""配额口径「频道资源计入建者额度」单测(负责人拍板:频道知识库计入频道创建者的配额)。

_kb_docs_used(user) = 个人库文档 + 该用户**创建的频道**的知识库文档。
「创建的频道」由 _rooms_created_by 经打桩 client 提供(create.sender==本人)。

运行:.venv/bin/python -m unittest cosmac.tests.test_quota_channel_scope
"""

from __future__ import annotations

import unittest
# (typing 未用)

from cosmac.bots.appservice_bot import CosmacBot
from cosmac.config import CosmacConfig
from cosmac.db import init_engine, session_scope
from cosmac.db import kb
from cosmac.db.models import SCOPE_ROOM, SCOPE_USER

CREATOR = "@boss:h"
OTHER = "@someone:h"
ROOM_MINE = "!mine:h"      # boss 建的频道
ROOM_OTHERS = "!theirs:h"  # 别人建的频道(boss 只是成员)


class _C:
    """打桩 client:boss 加入两个频道,只有 ROOM_MINE 的 create.sender 是 boss。"""

    def admin_user_joined_rooms(self, user_id):
        if user_id == CREATOR:
            return [ROOM_MINE, ROOM_OTHERS]
        return []

    def admin_room_state(self, room_id):
        creator = CREATOR if room_id == ROOM_MINE else OTHER
        return [
            {"type": "m.room.create", "sender": creator, "content": {}},
            {"type": "m.room.name", "content": {"name": room_id}},
        ]

    def whoami(self, t):
        return CREATOR

    def resolve_alias(self, a):
        return None

    def set_displayname(self, *a, **k):
        pass

    def get_state_event(self, *a, **k):
        return None


def _bot() -> CosmacBot:
    bot = CosmacBot(CosmacConfig(llm_provider="echo", server_name="h"))
    bot.client = _C()  # type: ignore
    return bot


class TestKbDocsCreatorScope(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)
        self.bot = _bot()
        with session_scope() as s:
            # boss 个人库 1 篇
            kb.ingest_document(s, scope=SCOPE_USER, scope_id=CREATOR,
                               title="个人笔记", source="t", text="私人")
            # boss 建的频道 2 篇
            kb.ingest_document(s, scope=SCOPE_ROOM, scope_id=ROOM_MINE,
                               title="A", source="t", text="频道A")
            kb.ingest_document(s, scope=SCOPE_ROOM, scope_id=ROOM_MINE,
                               title="B", source="t", text="频道B")
            # 别人建的频道 5 篇(boss 是成员但不该计入 boss 额度)
            for i in range(5):
                kb.ingest_document(s, scope=SCOPE_ROOM, scope_id=ROOM_OTHERS,
                                   title=f"X{i}", source="t", text="别人的")

    def test_rooms_created_by_only_own(self) -> None:
        self.assertEqual(self.bot._rooms_created_by(CREATOR), [ROOM_MINE])

    def test_kb_docs_used_counts_personal_plus_own_channels(self) -> None:
        with session_scope() as s:
            # 个人库 1 + 自建频道 2 = 3;别人建的 5 篇不计入
            self.assertEqual(self.bot._kb_docs_used(s, CREATOR), 3)

    def test_non_creator_channel_excluded(self) -> None:
        # 站在 OTHER 视角:他没建任何频道(打桩 joined_rooms 返回空)→ 只算他个人库(0)
        with session_scope() as s:
            self.assertEqual(self.bot._kb_docs_used(s, OTHER), 0)


if __name__ == "__main__":
    unittest.main()
