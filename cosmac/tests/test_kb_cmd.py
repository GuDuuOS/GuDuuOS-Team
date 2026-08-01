"""「知识」聊天命令单元测试（内存 SQLite + 哈希嵌入，零 key）。

运行：.venv/bin/python -m unittest cosmac.tests.test_kb_cmd
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

from cosmac.db import init_engine, session_scope
from cosmac.db import kb
from cosmac.db.kb_cmd import handle_kb_command, looks_like_kb_command
from cosmac.db.models import SCOPE_ROOM, SCOPE_USER

ROOM = "!ops:example.invalid"
USER = "@alice:example.invalid"


def run(text: str, *, is_dm: bool = False, can_write: bool = True) -> str:
    with session_scope() as s:
        return handle_kb_command(
            s, is_dm=is_dm, room_id=ROOM, user_id=USER, text=text, can_write=can_write
        )


class TestKbCommandDetect(unittest.TestCase):
    def test_looks_like(self) -> None:
        self.assertTrue(looks_like_kb_command("知识 列表"))
        self.assertTrue(looks_like_kb_command("知识列表"))
        self.assertTrue(looks_like_kb_command("kb add x"))
        self.assertFalse(looks_like_kb_command("知道了"))  # 不以「知识」开头
        self.assertFalse(looks_like_kb_command("帮我建群"))


def _force_hashing_embedder(case: unittest.TestCase) -> None:
    """清掉环境里的 embedding key，让 get_embedder() 降级哈希词袋——
    避免测试因机器上真有 OPENAI_API_KEY/ARK_API_KEY 而发起真实网络请求。"""
    p = mock.patch.dict(os.environ, {}, clear=False)
    p.start()
    case.addCleanup(p.stop)
    for k in ("COSMAC_EMBED_API_KEY", "OPENAI_API_KEY", "ARK_API_KEY"):
        os.environ.pop(k, None)


class TestKbCommand(unittest.TestCase):
    def setUp(self) -> None:
        _force_hashing_embedder(self)
        init_engine("sqlite://", create_all=True)

    def test_help(self) -> None:
        self.assertIn("知识库命令", run("知识"))

    def test_add_then_list_and_search(self) -> None:
        out = run("知识 添加 报价规则 ｜ 商单报价按粉丝量和均播定价，对外报价需筱雨确认。")
        self.assertIn("已把", out)
        with session_scope() as s:
            docs = kb.list_docs(s, scope=SCOPE_ROOM, scope_id=ROOM)
            self.assertEqual(len(docs), 1)
            self.assertEqual(docs[0].title, "报价规则")
        self.assertIn("报价规则", run("知识 列表"))
        # 试搜命中
        self.assertIn("报价规则", run("知识 搜 商单报价"))

    def test_add_requires_body(self) -> None:
        self.assertIn("缺正文", run("知识 添加 只有标题"))

    def test_delete_only_own_scope(self) -> None:
        run("知识 添加 文档A ｜ 正文一二三")
        with session_scope() as s:
            did = kb.list_docs(s, scope=SCOPE_ROOM, scope_id=ROOM)[0].id
        # 删别的编号 → 没找到
        self.assertIn("没找到", run("知识 删除 999999"))
        # 删本群的 → 成功
        self.assertIn("已删除", run(f"知识 删除 {did}"))
        with session_scope() as s:
            self.assertEqual(len(kb.list_docs(s, scope=SCOPE_ROOM, scope_id=ROOM)), 0)

    def test_non_admin_cannot_write_room(self) -> None:
        self.assertIn("只有群管理员", run("知识 添加 x ｜ 正文", can_write=False))
        self.assertIn("只有群管理员", run("知识 删除 1", can_write=False))
        self.assertNotIn("只有群管理员", run("知识 列表", can_write=False))  # 查看放行

    def test_dm_scope_is_user(self) -> None:
        run("知识 添加 我的笔记 ｜ 私聊里的个人知识", is_dm=True, can_write=False)
        with session_scope() as s:
            self.assertEqual(len(kb.list_docs(s, scope=SCOPE_USER, scope_id=USER)), 1)
            self.assertEqual(len(kb.list_docs(s, scope=SCOPE_ROOM, scope_id=ROOM)), 0)


class TestKbSearchTool(unittest.TestCase):
    """search_knowledge 工具的 bot 侧检索（_kb_search_for_tool）集成测试。"""

    def setUp(self) -> None:
        _force_hashing_embedder(self)
        init_engine("sqlite://", create_all=True)

    def _bot(self):
        from cosmac.bots.appservice_bot import CosmacBot
        from cosmac.config import CosmacConfig

        return CosmacBot(CosmacConfig(llm_provider="echo"))  # 纯离线，不连网

    def test_tool_retrieves_ingested_doc(self) -> None:
        from cosmac.ai.tools import ToolContext

        # 先往本群知识库入一篇文档
        run("知识 添加 报价规则 ｜ 商单报价按粉丝量和均播定价，对外报价需筱雨确认。")
        bot = self._bot()
        out = bot._kb_search_for_tool("商单报价", ToolContext(ROOM, USER))
        self.assertIn("报价规则", out)
        self.assertIn("检索结果", out)

    def test_tool_reports_no_hit(self) -> None:
        from cosmac.ai.tools import ToolContext

        bot = self._bot()
        out = bot._kb_search_for_tool("完全不相关的查询", ToolContext(ROOM, USER))
        self.assertIn("没找到", out)


class TestKbHttpHandlers(unittest.TestCase):
    """个人知识库管理 HTTP 端点（add/list/delete）+ 越权防护。"""

    def setUp(self) -> None:
        _force_hashing_embedder(self)
        init_engine("sqlite://", create_all=True)

    def _bot(self):
        from cosmac.bots.appservice_bot import CosmacBot
        from cosmac.config import CosmacConfig

        bot = CosmacBot(CosmacConfig(llm_provider="echo"))
        # 假身份：token "alice"→@alice，"bob"→@bob，其它→未登录；门控放行
        bot.client.whoami = lambda t: {  # type: ignore
            "alice": "@alice:h", "bob": "@bob:h"
        }.get(t)
        bot._gate_allows = lambda u, c: True  # type: ignore
        return bot

    def test_add_requires_login(self) -> None:
        code, _ = self._bot().handle_kb_add("", {"content": "x"})
        self.assertEqual(code, 401)

    def test_add_rejects_empty_content(self) -> None:
        code, p = self._bot().handle_kb_add("alice", {"title": "t", "content": "  "})
        self.assertEqual(code, 400)
        self.assertIn("正文", p["error"])

    def test_add_then_list_with_id(self) -> None:
        bot = self._bot()
        code, p = bot.handle_kb_add("alice", {"title": "报价规则", "content": "商单按粉丝量定价。"})
        self.assertEqual(code, 200)
        self.assertTrue(p["ok"])
        self.assertGreaterEqual(p["chunks"], 1)
        code, p = bot.handle_kb_list_mine("alice")
        self.assertEqual(code, 200)
        self.assertEqual(len(p["docs"]), 1)
        self.assertIn("id", p["docs"][0])  # 列表带 id，供删除用
        self.assertEqual(p["docs"][0]["title"], "报价规则")

    def test_delete_blocks_other_user(self) -> None:
        bot = self._bot()
        _, p = bot.handle_kb_add("alice", {"title": "私密", "content": "alice 的资料"})
        did = p["id"]
        # bob 删 alice 的文档 → 404（越权防护）
        code, _ = bot.handle_kb_delete("bob", {"id": did})
        self.assertEqual(code, 404)
        # alice 自己删 → 200
        code, _ = bot.handle_kb_delete("alice", {"id": did})
        self.assertEqual(code, 200)
        _, p = bot.handle_kb_list_mine("alice")
        self.assertEqual(len(p["docs"]), 0)

    def test_add_gate_denied(self) -> None:
        bot = self._bot()
        bot._gate_allows = lambda u, c: False  # type: ignore
        bot._gate_denied_text = lambda c, ui=False: "需升级会员"  # type: ignore
        code, p = bot.handle_kb_add("alice", {"title": "t", "content": "正文"})
        self.assertEqual(code, 403)
        self.assertIn("升级", p["error"])


class TestKbCommandPersonalQuota(unittest.TestCase):
    """M4：个人库「知识 添加」命令必须过会员配额守卫（与 UI handle_kb_add 同口径）。"""

    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)
        _force_hashing_embedder(self)

    def test_guard_blocks_personal_add(self) -> None:
        with session_scope() as s:
            out = handle_kb_command(
                s, is_dm=True, room_id=ROOM, user_id=USER,
                text="知识 添加 标题 ｜ 正文内容",
                personal_add_guard=lambda cur, blen: "配额满了，升级会员",
            )
        self.assertIn("配额满了", out)
        with session_scope() as s:  # 被拦下，没真入库
            self.assertEqual(len(kb.list_docs(s, scope=SCOPE_USER, scope_id=USER)), 0)

    def test_guard_not_applied_to_room_add(self) -> None:
        # 群库(is_dm=False)不走个人配额守卫——即便传了 guard 也不生效，正常入库
        with session_scope() as s:
            out = handle_kb_command(
                s, is_dm=False, room_id=ROOM, user_id=USER, can_write=True,
                text="知识 添加 标题 ｜ 正文内容",
                personal_add_guard=lambda cur, blen: "不该触发",
            )
        self.assertIn("已把", out)


if __name__ == "__main__":
    unittest.main()
