"""#7 回归：引擎/LLM 本体调用抛异常时，_handle_event 必须就地兜住——

给用户发一条明确失败提示、正常返回，绝不把异常穿透到 handle_transaction（那会返回 False →
Synapse 重发整批 → 整条 Agent run 从头重跑 → 已执行的建群/发消息等工具无幂等键、重复副作用）。
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, List, Optional

from cosmac.bots.appservice_bot import CosmacBot
from cosmac.config import CosmacConfig


class _FakeClient:
    def __init__(self) -> None:
        self.sent: List[str] = []
        self.typing: List[bool] = []

    def joined_member_count(self, room_id: str) -> int:
        return 2  # ≤2 → 私聊，逐句回

    def set_typing(self, room_id: str, on: bool) -> None:
        self.typing.append(on)

    def send_text(self, room_id: str, text: str, txn_id: Optional[str] = None) -> str:
        self.sent.append(text)
        return "$sent"


class TestEngineErrorFallback(unittest.TestCase):
    def _bot(self) -> CosmacBot:
        bot = CosmacBot(CosmacConfig(
            llm_provider="echo", server_name="h", bot_user_id="@guduu:h"))
        bot.client = _FakeClient()  # type: ignore
        bot._reply_pool = None  # 同步模式:事件路径测试要立刻看到回复(并发修复后默认线程池)
        # 隔离出「引擎抛异常」这条通路：其余前置一律放行/空。
        bot._is_ai_session_room = lambda rid: False  # type: ignore
        bot._room_is_named_channel = lambda rid: False  # type: ignore
        bot._try_handle_command = lambda *a, **k: False  # type: ignore
        bot._gate_allows = lambda *a, **k: True  # type: ignore
        bot._rate_quota_blocked = lambda *a, **k: None  # type: ignore
        bot._apply_runtime_config = lambda: None  # type: ignore
        bot._group_context = lambda rid: {"model": ""}  # type: ignore
        bot._apply_worker_routing = lambda text, gctx, sender, mentioned_ids=None: gctx  # type: ignore
        bot._skill_addendum = lambda *a, **k: ""  # type: ignore
        bot._recent_history = lambda *a, **k: []  # type: ignore
        bot._agent_for_model = lambda m: object()  # type: ignore
        self._memory_called = False

        def _mem(*a: Any, **k: Any) -> None:
            self._memory_called = True
        bot._maybe_update_memory = _mem  # type: ignore
        return bot

    def _event(self) -> Dict[str, Any]:
        return {
            "type": "m.room.message", "sender": "@u:h", "room_id": "!r:h",
            "event_id": "$e1", "content": {"msgtype": "m.text", "body": "帮我建个群"},
        }

    def test_engine_exception_is_swallowed_and_user_notified(self) -> None:
        bot = self._bot()

        def boom(*a: Any, **k: Any) -> str:
            raise RuntimeError("模型端点 500")
        bot._run_agent_engine = boom  # type: ignore

        # 关键：绝不向上抛异常（否则事务返回 False → 整批重放 → 工具副作用重复）
        try:
            bot._handle_event(self._event())
        except Exception as exc:  # noqa: BLE001
            self.fail(f"_handle_event 不应把引擎异常抛出，却抛了：{exc!r}")

        # 用户收到明确失败提示（而非死寂转圈）
        self.assertTrue(any("暂时不可用" in m for m in bot.client.sent), bot.client.sent)
        # 失败不推进长期记忆（没有有效回复可摘要）
        self.assertFalse(self._memory_called)
        # "正在输入…" 一定被关掉（try/finally 保证）
        self.assertIn(False, bot.client.typing)

    def test_success_path_still_works(self) -> None:
        # 确认兜底没误伤正常路径：引擎正常返回 → 回复发出、记忆推进。
        bot = self._bot()
        bot._run_agent_engine = lambda *a, **k: "已为你建好群"  # type: ignore
        bot._handle_event(self._event())
        self.assertIn("已为你建好群", bot.client.sent)
        self.assertTrue(self._memory_called)


if __name__ == "__main__":
    unittest.main()
