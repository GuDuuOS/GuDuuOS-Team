"""AI 会话标题自动概括 —— 单元测试。

此前左侧会话列表的标题是"首句砍前 24 字"，用户粘个 GitHub 链接进来，
列表里就是一串 URL，看不出这段会话在干嘛（负责人实报）。现在首轮回复后
让模型概括一句写进会话标记，前端优先读它。

运行：.venv/bin/python -m unittest cosmac.tests.test_session_title
"""

from __future__ import annotations

import unittest


def _bot(existing_state, llm_reply="导入 PPT 技能", *, is_session=True):
    """造一个 bot：假 client 返回给定的会话标记，假 llm 返回给定的标题。"""
    from cosmac.bots.appservice_bot import CosmacBot
    from cosmac.config import CosmacConfig

    bot = CosmacBot(CosmacConfig(llm_provider="echo"))
    written = {}

    class C:
        def resolve_alias(self, a):
            return "!ctrl:h"

        def get_state_event(self, room, etype, key=""):
            if etype == "cosmac.ai_session":
                return existing_state if is_session else None
            return None

        def set_state_event(self, room, etype, content, key=""):
            written[etype] = content

        def send_text(self, *a, **k):
            return "$e"

        def set_displayname(self, *a, **k):
            pass

    class L:
        def complete(self, messages):
            return llm_reply

    bot.client = C()
    bot.llm = L()
    bot._ai_session_room_cache.clear()
    return bot, written


class SessionTitleTest(unittest.TestCase):
    def test_writes_title_on_first_turn(self) -> None:
        bot, written = _bot({"v": 1})
        bot._maybe_name_ai_session("!r:h", "把这个装进来 https://github.com/x/y", "好的…")
        self.assertEqual(written["cosmac.ai_session"]["title"], "导入 PPT 技能")
        self.assertEqual(written["cosmac.ai_session"]["v"], 1, "原有字段必须保留")

    def test_skips_when_title_already_set(self) -> None:
        """标题只在首轮定一次——否则每轮都烧一次模型，标题还会随聊天漂移。"""
        bot, written = _bot({"v": 1, "title": "已有标题"})
        bot._maybe_name_ai_session("!r:h", "又说了点别的", "嗯")
        self.assertEqual(written, {}, "已有标题时不该再写")

    def test_skips_non_session_rooms(self) -> None:
        """普通频道/专班不该被改标记。"""
        bot, written = _bot({"v": 1}, is_session=False)
        bot._maybe_name_ai_session("!chan:h", "你好", "你好")
        self.assertEqual(written, {})

    def test_strips_quotes_and_truncates(self) -> None:
        """模型爱加引号/句号/解释，得清干净；超长要截断。"""
        bot, written = _bot({"v": 1}, llm_reply='「导入技能。」\n（这是标题）')
        bot._maybe_name_ai_session("!r:h", "x", "y")
        self.assertEqual(written["cosmac.ai_session"]["title"], "导入技能")

        bot2, w2 = _bot({"v": 1}, llm_reply="这是一个非常非常长的标题会超出上限需要被截断处理")
        bot2._maybe_name_ai_session("!r:h", "x", "y")
        self.assertLessEqual(len(w2["cosmac.ai_session"]["title"]), bot2._SESSION_TITLE_MAX)

    def test_empty_reply_writes_nothing(self) -> None:
        bot, written = _bot({"v": 1}, llm_reply="   ")
        bot._maybe_name_ai_session("!r:h", "x", "y")
        self.assertEqual(written, {})

    def test_llm_failure_is_silent(self) -> None:
        """标题是锦上添花：模型挂了也绝不能抛异常打断已发出的回复。"""
        bot, written = _bot({"v": 1})

        class Boom:
            def complete(self, messages):
                raise RuntimeError("模型炸了")

        bot.llm = Boom()
        bot._maybe_name_ai_session("!r:h", "x", "y")   # 不抛异常即通过
        self.assertEqual(written, {})


if __name__ == "__main__":
    unittest.main()
