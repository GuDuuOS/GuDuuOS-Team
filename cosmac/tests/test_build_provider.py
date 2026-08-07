"""build_provider（多模型工厂）的单元测试。

验证按 provider 名 + 显式 key 能拿到正确后端、base_url 指对地方、缺 key/未知名的
降级与报错。构造 client 不联网，不需要真 key。

运行：.venv/bin/python -m unittest cosmac.tests.test_build_provider
"""

from __future__ import annotations

import os
import unittest

from cosmac.ai import build_provider
from cosmac.ai.claude import ClaudeProvider
from cosmac.ai.echo import EchoProvider
from cosmac.ai.openai_compat import OpenAICompatProvider


class TestBuildProvider(unittest.TestCase):
    def test_echo(self) -> None:
        self.assertIsInstance(build_provider("echo"), EchoProvider)

    def test_unknown_raises(self) -> None:
        with self.assertRaises(ValueError):
            build_provider("不存在的厂商", api_key="k")

    def test_missing_key_falls_back_to_echo(self) -> None:
        saved = os.environ.pop("ARK_API_KEY", None)
        try:
            # 既没显式 key、环境变量也没有 → echo
            self.assertIsInstance(build_provider("deepseek"), EchoProvider)
        finally:
            if saved is not None:
                os.environ["ARK_API_KEY"] = saved

    def test_saved_direct_mode_can_disable_environment_fallback(self) -> None:
        """网页配置已接管后，空 key 表示禁用，不再重新拾取旧 env。"""
        saved = os.environ.get("ARK_API_KEY")
        os.environ["ARK_API_KEY"] = "legacy-environment-key"
        try:
            self.assertIsInstance(
                build_provider("deepseek", allow_env_fallback=False), EchoProvider
            )
        finally:
            if saved is None:
                os.environ.pop("ARK_API_KEY", None)
            else:
                os.environ["ARK_API_KEY"] = saved

    def test_claude_with_explicit_key(self) -> None:
        p = build_provider("claude", api_key="test-key", model="claude-x")
        self.assertIsInstance(p, ClaudeProvider)
        self.assertEqual(p.model, "claude-x")

    def test_deepseek_uses_ark_base_url(self) -> None:
        p = build_provider("deepseek", api_key="test-key")
        self.assertIsInstance(p, OpenAICompatProvider)
        self.assertIn("volces.com", str(p._client.base_url))

    def test_gemini_uses_gemini_base_url(self) -> None:
        p = build_provider("gemini", api_key="test-key")
        self.assertIsInstance(p, OpenAICompatProvider)
        self.assertIn("googleapis.com", str(p._client.base_url))

    def test_openai_uses_official_base_url(self) -> None:
        p = build_provider("openai", api_key="test-key")
        self.assertIsInstance(p, OpenAICompatProvider)
        self.assertIn("openai.com", str(p._client.base_url))

    def test_default_model_applied(self) -> None:
        # 不指定 model → 用该 provider 的默认
        p = build_provider("openai", api_key="test-key")
        self.assertEqual(p.model, "gpt-4o")


if __name__ == "__main__":
    unittest.main()
