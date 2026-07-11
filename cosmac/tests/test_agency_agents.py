"""agency-agents 引入库（cosmac/ai/agency_agents.py）单测。

要点：全库字段齐全且中文(负责人要求:必须有中文备注)、slug 全局唯一(含与原生班底不冲突)、
preset_agents() 合并后两库都在、能力名册能列出引入的 Agent。
"""

from __future__ import annotations

import re
import unittest

from cosmac.ai.agency_agents import AGENCY_AGENTS, agency_agents
from cosmac.ai.presets import PRESET_AGENTS, preset_agents

_HAS_CJK = re.compile(r"[一-鿿]")


class TestAgencyAgents(unittest.TestCase):
    def test_fields_complete_and_chinese(self) -> None:
        # 每条必须有 slug/中文名/中文备注(description)/中文人设——负责人定的入库规则。
        for a in AGENCY_AGENTS:
            self.assertTrue(a.get("slug"), a)
            self.assertTrue(_HAS_CJK.search(a.get("name", "")), a.get("slug"))
            self.assertTrue(_HAS_CJK.search(a.get("description", "")), a.get("slug"))
            self.assertTrue(_HAS_CJK.search(a.get("system_prompt", "")), a.get("slug"))
            self.assertTrue(a.get("division"), a.get("slug"))

    def test_slugs_unique_and_no_collision_with_native(self) -> None:
        slugs = [a["slug"] for a in AGENCY_AGENTS]
        self.assertEqual(len(slugs), len(set(slugs)), "agency 库内 slug 重复")
        native = {a["slug"] for a in PRESET_AGENTS}
        clash = native & set(slugs)
        self.assertFalse(clash, f"与原生班底 slug 冲突: {clash}")

    def test_preset_agents_merges_both(self) -> None:
        merged = {a["slug"] for a in preset_agents()}
        self.assertTrue({a["slug"] for a in PRESET_AGENTS} <= merged)
        self.assertTrue({a["slug"] for a in AGENCY_AGENTS} <= merged)
        # 数量 = 原生 + agency(无冲突时)
        self.assertEqual(len(merged), len(PRESET_AGENTS) + len(AGENCY_AGENTS))

    def test_enabled_defaulted(self) -> None:
        for a in agency_agents():
            self.assertTrue(a["enabled"])
            self.assertIsInstance(a["skill_slugs"], list)

    def test_roster_lists_agency_agent(self) -> None:
        # 能力名册(拆任务派单入口)能列出引入的 Agent——上限已提到 200,不再被 50 截断。
        from cosmac.ai.tools import ToolContext
        from cosmac.bots.appservice_bot import CosmacBot
        from cosmac.config import CosmacConfig
        from cosmac.db import init_engine

        init_engine("sqlite://", create_all=True)

        class _C:
            def resolve_alias(self, alias):
                return None  # 无控制室:纯预置

            def get_state_event(self, *a, **k):
                return None

            def set_displayname(self, *a, **k):
                pass

        bot = CosmacBot(CosmacConfig(llm_provider="echo", server_name="h"))
        bot.client = _C()
        out = bot._list_capabilities_for_tool(ToolContext("!r:h", "@u:h"))
        self.assertIn("growth-hacker", out)        # 营销第一条
        self.assertIn("whimsy-injector", out)      # 设计最后一条(证明没被截断)
        self.assertIn("增长黑客", out)


if __name__ == "__main__":
    unittest.main()
