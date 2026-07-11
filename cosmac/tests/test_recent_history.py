"""#M15 回归：_recent_history 剔除"当前触发消息"时，必须从**最新端**剔除那一条，

而不是历史里更早的同文本消息——否则用户重复发"继续/好的"时，当前输入会被喂给模型两遍。
"""

from __future__ import annotations

import unittest

from cosmac.bots.appservice_bot import CosmacBot
from cosmac.config import CosmacConfig


def _bot() -> CosmacBot:
    return CosmacBot(CosmacConfig(llm_provider="echo", server_name="h", bot_user_id="@guduu:h"))


class TestRecentHistory(unittest.TestCase):
    def test_drops_current_from_newest_end_on_duplicate(self) -> None:
        bot = _bot()
        # 旧→新：用户先发过一次"继续"，bot 回了话，用户又发"继续"(这条是当前触发消息)
        msgs = [
            {"sender": "@u:h", "body": "继续"},
            {"sender": "@guduu:h", "body": "好的，我接着讲"},
            {"sender": "@u:h", "body": "继续"},   # 当前这条（最新）
        ]
        bot.client = type("C", (), {"get_messages": lambda self, r, limit=20: list(msgs)})()
        hist = bot._recent_history("!r:h", "@u:h", "继续")
        # 历史应是【第一条"继续" + bot 回复】，末尾**不再**残留当前的"继续"
        self.assertEqual([(m.role, m.content) for m in hist],
                         [("user", "继续"), ("assistant", "好的，我接着讲")])
        # 当前触发消息由 Agent.run 另行追加，这里绝不能重复保留 → user 角色只 1 条
        self.assertEqual(sum(1 for m in hist if m.role == "user"), 1)

    def test_non_duplicate_history_intact(self) -> None:
        bot = _bot()
        msgs = [
            {"sender": "@u:h", "body": "你好"},
            {"sender": "@guduu:h", "body": "你好，有什么可以帮你"},
            {"sender": "@u:h", "body": "帮我建个群"},   # 当前
        ]
        bot.client = type("C", (), {"get_messages": lambda self, r, limit=20: list(msgs)})()
        hist = bot._recent_history("!r:h", "@u:h", "帮我建个群")
        # 当前这条被剔，前面两条原样保留
        self.assertEqual([(m.role, m.content) for m in hist],
                         [("user", "你好"), ("assistant", "你好，有什么可以帮你")])


if __name__ == "__main__":
    unittest.main()
