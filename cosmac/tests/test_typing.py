"""「正在输入…」流式体感（③）单元测试。

验证主 AI 回复慢路径：进入生成前 set_typing(True)、发完 set_typing(False)；
即使生成抛异常，也靠 try/finally 关掉输入指示（不卡住）。内存 SQLite、零 key。
"""

from __future__ import annotations

import unittest

from cosmac.db import init_engine


class FakeClient:
    """记录 set_typing / send_text 调用的假 client；其余按 DM 慢路径所需给最小实现。"""

    def __init__(self) -> None:
        self.typing: list = []          # [(room, bool), ...] 按顺序记录
        self.sent: list = []            # [(room, text), ...]

    def set_typing(self, room_id, typing, timeout_ms=30000):
        self.typing.append((room_id, typing))

    def send_text(self, room_id, text, txn_id=None):
        self.sent.append((room_id, text))
        return "$e"

    def joined_member_count(self, room_id):
        return 2  # ≤2 → 私聊：对每句都回（无需 @）

    def get_messages(self, room_id, limit=20):
        return []  # 无历史

    def resolve_alias(self, alias):
        return None  # 控制室解析不到 → 人设/规则/配置都优雅回退空

    def get_state_event(self, room_id, etype, state_key=""):
        return None


def _bot_with_fake():
    from cosmac.bots.appservice_bot import CosmacBot
    from cosmac.config import CosmacConfig

    bot = CosmacBot(CosmacConfig(llm_provider="echo"))
    bot.client = FakeClient()
    # 隔离慢路径里会打网络/控制室的环节，聚焦 typing 行为
    bot._try_handle_command = lambda *a, **k: False  # type: ignore
    bot._gate_allows = lambda u, c: True              # type: ignore
    bot._apply_runtime_config = lambda: None          # type: ignore
    return bot


_EVENT = {
    "type": "m.room.message",
    "content": {"msgtype": "m.text", "body": "你好"},
    "sender": "@u:h",
    "room_id": "!r:h",
    "event_id": "$evt",
}


class TestTypingIndicator(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)

    def test_typing_on_then_off_around_reply(self) -> None:
        bot = _bot_with_fake()
        bot._handle_event(dict(_EVENT))
        # 先开后关，且都针对该房间
        self.assertEqual(bot.client.typing, [("!r:h", True), ("!r:h", False)])
        # 确实发了回复（echo 后端会回显）
        self.assertEqual(len(bot.client.sent), 1)

    def test_typing_cleared_and_user_notified_if_generation_raises(self) -> None:
        bot = _bot_with_fake()

        class Boom:
            system_prompt = "s"

            def run(self, *a, **k):
                raise RuntimeError("boom")

        bot.agent = Boom()  # type: ignore  # 让生成抛异常
        bot._agent_for_model = lambda m: bot.agent  # type: ignore
        # #7：引擎/LLM 异常被就地兜住，**不再向上抛**（否则事务返回 False → Synapse 重发整批
        # → 整条 Agent run 重跑 → 已执行的工具副作用重复）。
        bot._handle_event(dict(_EVENT))
        # 关键：异常路径也必须把"正在输入…"关掉（finally）
        self.assertEqual(bot.client.typing, [("!r:h", True), ("!r:h", False)])
        # 用户收到明确失败提示（而非死寂或抛异常）
        self.assertEqual(len(bot.client.sent), 1)
        self.assertIn("暂时不可用", bot.client.sent[0][1])

    def test_edit_event_does_not_trigger_reply(self) -> None:
        # #10：编辑事件(m.replace)不是新消息，AI 不应对"* 新内容"再答一遍。
        bot = _bot_with_fake()
        edit_event = {
            "type": "m.room.message", "sender": "@u:h", "room_id": "!r:h",
            "event_id": "$edit",
            "content": {
                "msgtype": "m.text", "body": "* 新内容",
                "m.new_content": {"msgtype": "m.text", "body": "新内容"},
                "m.relates_to": {"rel_type": "m.replace", "event_id": "$orig"},
            },
        }
        bot._handle_event(edit_event)
        self.assertEqual(bot.client.sent, [])    # 没有任何回复
        self.assertEqual(bot.client.typing, [])  # 连"正在输入…"都不触发


if __name__ == "__main__":
    unittest.main()
