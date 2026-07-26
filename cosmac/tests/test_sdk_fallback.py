"""#8 回归：SDK 引擎中途失败时的回退策略——

- 已执行过工具(reporter.steps 非空 → 建群/派单等副作用已落地)：**绝不**回退 legacy 从头重跑
  (会重复建房/重复派单/配额双扣)，而是停下、如实告知。
- 一个工具都没跑就失败(通常首个 LLM 调用失败)：回退 legacy 无副作用，正常兜底出回复。
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from cosmac.ai.tools import ToolContext
from cosmac.bots.appservice_bot import CosmacBot
from cosmac.config import CosmacConfig


class TestSdkFallback(unittest.TestCase):
    def _bot(self) -> CosmacBot:
        bot = CosmacBot(CosmacConfig(llm_provider="echo", server_name="h"))
        bot.client = SimpleNamespace(  # type: ignore
            send_text=lambda *a, **k: "$e",   # reporter 首个进度消息
            edit_text=lambda *a, **k: None,   # reporter 后续编辑/定格
            resolve_alias=lambda alias: None,  # 引擎回退告警里用（返回 None 即静默）
        )
        return bot

    @mock.patch("cosmac.ai.engine.sdk_engine_enabled", return_value=True)
    @mock.patch("cosmac.ai.engine.ClaudeSdkEngine")
    def test_no_legacy_rerun_after_tools_executed(self, MockEngine, _enabled) -> None:
        bot = self._bot()

        def run(user_text, ctx, extra_system="", history=None, progress_cb=None, stream_cb=None):
            # 模拟 SDK 已执行过一个副作用工具（建群），随后在后续轮次失败
            if progress_cb:
                progress_cb("create_room", {"name": "项目专班"})
            raise RuntimeError("boom at turn 3")
        MockEngine.return_value.run.side_effect = run
        MockEngine.return_value.last_usage_tokens = 0  # Token 计量：mock 引擎给个整数用量

        # legacy agent 绝不应被调用（否则会重复建群/派单）
        legacy = SimpleNamespace(
            system_prompt="s",
            run=mock.Mock(side_effect=AssertionError("已动过手，legacy 不应被再次调用")),
        )
        # 新契约：返回 (回复文本, 真实用量token数)
        reply, usage = bot._run_agent_engine(
            legacy, "组个专班", ToolContext("!r:h", "@u:h"), "", [])
        self.assertIn("部分操作", reply)      # 告知用户已做部分、已停下
        self.assertEqual(usage, 0)
        legacy.run.assert_not_called()        # 关键：没有整单重跑

    @mock.patch("cosmac.ai.engine.sdk_engine_enabled", return_value=True)
    @mock.patch("cosmac.ai.engine.ClaudeSdkEngine")
    def test_legacy_fallback_when_no_tool_executed(self, MockEngine, _enabled) -> None:
        bot = self._bot()

        def run(user_text, ctx, extra_system="", history=None, progress_cb=None, stream_cb=None):
            raise RuntimeError("boom before any tool")  # 未调用 progress_cb
        MockEngine.return_value.run.side_effect = run

        legacy = SimpleNamespace(
            system_prompt="s", run=lambda *a, **k: "legacy 正常回复")
        reply, _usage = bot._run_agent_engine(
            legacy, "你好", ToolContext("!r:h", "@u:h"), "", [])
        self.assertEqual(reply, "legacy 正常回复")  # 无副作用 → 安全回退


if __name__ == "__main__":
    unittest.main()
