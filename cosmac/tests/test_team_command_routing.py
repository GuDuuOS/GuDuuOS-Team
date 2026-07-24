# -*- coding: utf-8 -*-
"""「建专班 <名字>」命令走向单测(负责人实报:建专班后 AI 同事没进频道、少 RULE)。

根因:该命令曾走 _launch_campaign——一张硬编码演示派单卡(选题/文案/数据 Agent 全是
假文本,不拉真傀儡、不派真任务、不写 RULE),抢在真 AI 编排(assemble_team)之前。
修复:命令门控通过后 **return False**,交回 AI 走 assemble_team 真编排。

本测验证:门控放行时命令**不自己处理**(return False→交 AI);无权限/超额时仍就地拦。
运行:.venv/bin/python -m unittest cosmac.tests.test_team_command_routing
"""

from __future__ import annotations

import unittest
from typing import List, Optional

from cosmac.bots.appservice_bot import CosmacBot
from cosmac.config import CosmacConfig
from cosmac.db import init_engine


class _C:
    def __init__(self) -> None:
        self.sent: List[str] = []

    def send_text(self, room_id, text, txn_id=None):
        self.sent.append(text)
        return "$e"

    def whoami(self, t):
        return "@u:h"

    def resolve_alias(self, a):
        return None

    def set_displayname(self, *a, **k):
        pass

    def get_state_event(self, *a, **k):
        return None


def _bot(gate_ok: bool = True, quota_over: Optional[str] = None) -> CosmacBot:
    bot = CosmacBot(CosmacConfig(llm_provider="echo", server_name="h"))
    bot.client = _C()  # type: ignore
    bot._gate_allows = lambda uid, cap: gate_ok  # type: ignore
    bot._rate_quota_blocked = lambda uid, m, consume=True: quota_over  # type: ignore
    # 确保没有 _launch_campaign(演示卡路径已删)
    assert not hasattr(bot, "_launch_campaign"), "演示派单卡 _launch_campaign 应已删除"
    return bot


class TestTeamCommandRouting(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)

    def test_passes_to_ai_when_allowed(self) -> None:
        # 门控放行 → 命令不自己处理,return False 交回 AI(走 assemble_team 真编排)
        bot = _bot(gate_ok=True)
        handled = bot._try_handle_command("!r:h", "@u:h", "建专班养生保健")
        self.assertFalse(handled)          # 交回 AI
        self.assertEqual(bot.client.sent, [])  # 不再发演示派单卡

    def test_blocks_when_no_permission(self) -> None:
        # 无权限 → 命令就地拦下并提示(不交 AI、不建群)
        bot = _bot(gate_ok=False)
        handled = bot._try_handle_command("!r:h", "@u:h", "建专班养生保健")
        self.assertTrue(handled)
        self.assertTrue(bot.client.sent)   # 发了升级/拒绝提示

    def test_blocks_when_over_quota(self) -> None:
        # 超额 → 命令就地拦(gate 放行但 teams 配额满)
        bot = _bot(gate_ok=True, quota_over="专班数已达上限,请升级")
        handled = bot._try_handle_command("!r:h", "@u:h", "建专班养生保健")
        self.assertTrue(handled)
        self.assertIn("上限", bot.client.sent[0])


if __name__ == "__main__":
    unittest.main()
