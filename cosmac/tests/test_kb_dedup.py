# -*- coding: utf-8 -*-
"""知识库同名去重/覆盖单测(负责人实报:同一份文件反复上传,既不去重也不覆盖,
列表堆出好几条一模一样的记录)。

语义:上传同名文档 = **覆盖更新**(delete_docs_by_title 删旧 → ingest 入新);
不同名文档互不影响。运行:.venv/bin/python -m unittest cosmac.tests.test_kb_dedup
"""

from __future__ import annotations

import unittest

from cosmac.db import init_engine, session_scope
from cosmac.db import kb
from cosmac.db.models import SCOPE_ROOM

ROOM = "!kb:h"


class TestKbDedup(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)

    def _upload(self, title: str, text: str) -> None:
        """模拟上传入口的「同名=覆盖」流程(与 handle_kb_room_add 同序)。"""
        with session_scope() as s:
            kb.delete_docs_by_title(s, scope=SCOPE_ROOM, scope_id=ROOM, title=title)
            kb.ingest_document(s, scope=SCOPE_ROOM, scope_id=ROOM,
                               title=title, source="upload", text=text)

    def test_same_title_overwrites_not_duplicates(self) -> None:
        self._upload("json.json", "第一版内容")
        self._upload("json.json", "第二版内容")
        self._upload("json.json", "第三版内容")
        with session_scope() as s:
            docs = kb.list_docs(s, scope=SCOPE_ROOM, scope_id=ROOM)
            self.assertEqual(len(docs), 1)  # 不再堆一串相同记录
            # 内容是最新一版(覆盖而非保旧)
            text = "".join(c.text for c in docs[0].chunks)
            self.assertIn("第三版", text)

    def test_different_titles_coexist(self) -> None:
        self._upload("产品线A.txt", "A")
        self._upload("产品线B.txt", "B")
        with session_scope() as s:
            self.assertEqual(len(kb.list_docs(s, scope=SCOPE_ROOM, scope_id=ROOM)), 2)

    def test_delete_by_title_scoped(self) -> None:
        # 只删本作用域的同名——别的频道/个人库同名文档不受波及
        self._upload("手册.md", "本频道")
        with session_scope() as s:
            kb.ingest_document(s, scope=SCOPE_ROOM, scope_id="!other:h",
                               title="手册.md", source="upload", text="别的频道")
        with session_scope() as s:
            n = kb.delete_docs_by_title(s, scope=SCOPE_ROOM, scope_id=ROOM, title="手册.md")
            self.assertEqual(n, 1)
            self.assertEqual(len(kb.list_docs(s, scope=SCOPE_ROOM, scope_id="!other:h")), 1)


if __name__ == "__main__":
    unittest.main()
