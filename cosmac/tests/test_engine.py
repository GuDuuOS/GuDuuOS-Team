# -*- coding: utf-8 -*-
"""Claude Agent SDK 引擎(cosmac/ai/engine.py)的单元测试。

只测 3.9 环境可跑的纯逻辑(开关/历史转换/无 SDK 时的失败路径)。
真跑 SDK 的 E2E 需要 Python 3.10+ + claude-agent-sdk + DeepSeek key,
在 CI/本地用 .venv312 手动跑 smoke 脚本验证(见 DEVLOG 2026-07-03)。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from cosmac.ai.base import Message  # noqa: E402
from cosmac.ai.engine import ClaudeSdkEngine, _history_text, sdk_engine_enabled  # noqa: E402
from cosmac.ai.tools import ToolContext  # noqa: E402


class EngineConfigTest(unittest.TestCase):
    """开关与配置解析。"""

    def tearDown(self) -> None:
        os.environ.pop("COSMAC_AGENT_ENGINE", None)

    def test_disabled_by_default(self) -> None:
        os.environ.pop("COSMAC_AGENT_ENGINE", None)
        self.assertFalse(sdk_engine_enabled())

    def test_enabled_by_env(self) -> None:
        os.environ["COSMAC_AGENT_ENGINE"] = "claude_sdk"
        self.assertTrue(sdk_engine_enabled())
        os.environ["COSMAC_AGENT_ENGINE"] = "CLAUDE_SDK"  # 大小写不敏感
        self.assertTrue(sdk_engine_enabled())

    def test_other_value_disabled(self) -> None:
        os.environ["COSMAC_AGENT_ENGINE"] = "legacy"
        self.assertFalse(sdk_engine_enabled())


class HistoryTextTest(unittest.TestCase):
    """history → 文本前缀的转换。"""

    def test_empty(self) -> None:
        self.assertEqual(_history_text(None), "")
        self.assertEqual(_history_text([]), "")

    def test_converts_user_and_assistant(self) -> None:
        h = [
            Message(role="user", content="我们刚建了群A"),
            Message(role="assistant", content="好的,已记录。"),
            Message(role="tool", content="内部工具输出不该出现"),
        ]
        text = _history_text(h)
        self.assertIn("用户: 我们刚建了群A", text)
        self.assertIn("你(AI): 好的,已记录。", text)
        self.assertNotIn("内部工具输出", text)
        self.assertTrue(text.endswith("### 用户这次说\n"))

    def test_limit_keeps_recent(self) -> None:
        h = [Message(role="user", content=f"第{i}句") for i in range(30)]
        text = _history_text(h, limit=5)
        self.assertNotIn("第0句", text)
        self.assertIn("第29句", text)


class EngineFailurePathTest(unittest.TestCase):
    """3.9 环境没装 claude-agent-sdk:run() 必须抛异常(bot 层据此回退 legacy),
    绝不能静默吞掉——那会让用户收到空回复还查不出原因。"""

    def test_run_raises_without_sdk(self) -> None:
        try:
            import claude_agent_sdk  # noqa: F401
            self.skipTest("本环境装了 SDK,失败路径不适用")
        except ImportError:
            pass
        eng = ClaudeSdkEngine(
            toolbox=None,  # 走不到用它的地方
            get_system=lambda: "sys",
        )
        ctx = ToolContext(room_id="!r:x", sender="@u:x")
        with self.assertRaises(Exception):
            eng.run("hi", ctx)


if __name__ == "__main__":
    unittest.main()
