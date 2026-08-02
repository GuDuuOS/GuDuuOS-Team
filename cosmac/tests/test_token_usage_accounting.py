"""AI Token 计费口径回归测试。

覆盖 Claude Agent SDK、Anthropic 直连与 OpenAI 兼容后端的用量提取。
核心规则是：用户仅为模型输出 token 付费，平台注入的系统提示词、
历史上下文、工具定义与缓存输入不得计入用户钱包。
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from cosmac.ai.claude import _usage_output_tokens as claude_output_tokens
from cosmac.ai.engine import _result_usage_tokens
from cosmac.ai.openai_compat import _usage_output_tokens as openai_output_tokens
from cosmac.db import init_engine
from cosmac.wallet import WalletStore


class _TokenConfigClient:
    """为钱包端到端回归提供固定 Token 经济配置。"""

    def resolve_alias(self, alias: str) -> str:
        """模拟将控制室别名解析成 room id。"""
        return "!control:example.invalid"

    def get_state_event(
        self, room_id: str, event_type: str, state_key: str = ""
    ) -> dict:
        """返回已启用、无每日免费额度的 1:1 计费配置。"""
        return {
            "enabled": True,
            "markup": 1.0,
            "tokens_per_yuan": 1000,
            "free_daily": 0,
            "free_grant": 0,
            "min_balance": 1,
        }


class TestTokenUsageAccounting(unittest.TestCase):
    """确保超大输入上下文不会被当成用户消费。"""

    def test_openai_only_bills_completion_tokens(self) -> None:
        """OpenAI 即使报告 20,000 输入，用户也只结算 180 输出。"""
        response = SimpleNamespace(
            usage=SimpleNamespace(
                prompt_tokens=20_000,
                completion_tokens=180,
                total_tokens=20_180,
            )
        )
        self.assertEqual(openai_output_tokens(response), 180)

    def test_anthropic_only_bills_output_tokens(self) -> None:
        """Anthropic 直连后端不得将 input_tokens 计入用户余额。"""
        response = SimpleNamespace(
            usage=SimpleNamespace(input_tokens=18_000, output_tokens=240)
        )
        self.assertEqual(claude_output_tokens(response), 240)

    def test_agent_sdk_ignores_input_and_cache_tokens(self) -> None:
        """Agent SDK 的工具上下文和 cache 用量不向用户计费。"""
        message = SimpleNamespace(
            usage={
                "input_tokens": 18_000,
                "cache_creation_input_tokens": 9_000,
                "cache_read_input_tokens": 12_000,
                "output_tokens": 320,
            }
        )
        self.assertEqual(_result_usage_tokens(message), 320)

    def test_missing_or_invalid_usage_fails_closed_to_zero_charge(self) -> None:
        """供应商未返回可信输出用量时不猜测、不误扣用户余额。"""
        self.assertEqual(openai_output_tokens(SimpleNamespace(usage=None)), 0)
        self.assertEqual(
            claude_output_tokens(
                SimpleNamespace(usage=SimpleNamespace(output_tokens="bad"))
            ),
            0,
        )
        self.assertEqual(
            _result_usage_tokens(SimpleNamespace(usage={"output_tokens": -1})),
            0,
        )

    def test_large_context_chat_does_not_zero_funded_wallet(self) -> None:
        """一次大上下文咨询对 2,000 和 18,000 余额都只扣真实输出。"""
        response = SimpleNamespace(
            usage=SimpleNamespace(
                prompt_tokens=20_000,
                completion_tokens=180,
                total_tokens=20_180,
            )
        )
        billable = openai_output_tokens(response)

        for opening_balance in (2_000, 18_000):
            with self.subTest(opening_balance=opening_balance):
                # 每个子用例用全新内存库，避免前一个余额影响后一个。
                init_engine("sqlite://", create_all=True)
                wallet = WalletStore(
                    _TokenConfigClient(), "#control:example.invalid", ttl=0
                )
                wallet.recharge("@user:example.invalid", opening_balance)
                result = wallet.charge_usage(
                    "@user:example.invalid", real_tokens=billable
                )
                self.assertEqual(result["charged"], 180)
                self.assertEqual(result["balance"], opening_balance - 180)
                self.assertFalse(result["capped"])


if __name__ == "__main__":
    unittest.main()
