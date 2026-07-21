# -*- coding: utf-8 -*-
"""频道知识库文档全文端点单测(右侧「关于此频道」点开文档看内容,频道成员可用)。

运行:.venv/bin/python -m unittest cosmac.tests.test_kb_room_doc
"""

from __future__ import annotations

import unittest
from typing import Optional

from cosmac.bots.appservice_bot import CosmacBot
from cosmac.config import CosmacConfig
from cosmac.db import init_engine, session_scope, kb
from cosmac.db.models import SCOPE_ROOM, SCOPE_USER

ROOM = "!team:h"
U = "@u:h"


class _C:
    def __init__(self) -> None:
        self.members = {ROOM: [U]}

    def whoami(self, token: str) -> Optional[str]:
        return U if token == "tok" else None

    def is_joined_member(self, room: str, user: str) -> bool:
        return user in self.members.get(room, [])

    def resolve_alias(self, alias):
        return None

    def get_state_event(self, *a, **k):
        return None

    def set_displayname(self, *a, **k):
        pass


class TestKbRoomDoc(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)
        self.bot = CosmacBot(CosmacConfig(llm_provider="echo", server_name="h"))
        self.bot.client = _C()
        with session_scope() as s:
            d1 = kb.ingest_document(s, scope=SCOPE_ROOM, scope_id=ROOM,
                                    title="拍摄手册", source="t",
                                    text="第一章:分镜。\n第二章:设备。")
            d2 = kb.ingest_document(s, scope=SCOPE_ROOM, scope_id="!other:h",
                                    title="别家文档", source="t", text="机密内容")
            d3 = kb.ingest_document(s, scope=SCOPE_USER, scope_id=U,
                                    title="个人笔记", source="t", text="个人内容")
            self.doc_id, self.other_id, self.user_id_doc = d1.id, d2.id, d3.id

    def test_member_reads_full_text(self) -> None:
        code, p = self.bot.handle_kb_room_doc("tok", ROOM, str(self.doc_id))
        self.assertEqual(code, 200)
        self.assertEqual(p["title"], "拍摄手册")
        self.assertIn("第一章:分镜", p["text"])
        self.assertIn("第二章:设备", p["text"])

    def test_non_member_403(self) -> None:
        self.bot.client.members[ROOM] = []
        code, _ = self.bot.handle_kb_room_doc("tok", ROOM, str(self.doc_id))
        self.assertEqual(code, 403)

    def test_cross_room_doc_404(self) -> None:
        """拿任意 doc_id 跨频道读别家文档 → 404(文档必须真挂在本频道)。"""
        code, _ = self.bot.handle_kb_room_doc("tok", ROOM, str(self.other_id))
        self.assertEqual(code, 404)

    def test_user_scope_doc_404(self) -> None:
        """个人库文档不属于频道 → 404(scope 校验,不只比 scope_id)。"""
        code, _ = self.bot.handle_kb_room_doc("tok", ROOM, str(self.user_id_doc))
        self.assertEqual(code, 404)

    def test_bad_ids(self) -> None:
        self.assertEqual(self.bot.handle_kb_room_doc("tok", "notroom", "1")[0], 400)
        self.assertEqual(self.bot.handle_kb_room_doc("tok", ROOM, "abc")[0], 400)
        self.assertEqual(self.bot.handle_kb_room_doc("bad", ROOM, "1")[0], 401)


if __name__ == "__main__":
    unittest.main()
