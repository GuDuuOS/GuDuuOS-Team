"""用户自建 智能体/技能(scope=user)单测:CRUD/越权隔离/存储管控/名册与@路由生效。

负责人需求:用户可自建 AI Agent 与 Skill,归属本人账号权益,计入存储空间。
"""

from __future__ import annotations

import unittest
from typing import Optional

from cosmac.ai.tools import ToolContext
from cosmac.bots.appservice_bot import CosmacBot
from cosmac.config import CosmacConfig
from cosmac.db import init_engine

U = "@u:h"
OTHER = "@other:h"


class _C:
    def whoami(self, token: str) -> Optional[str]:
        return {"tok": U, "tok2": OTHER}.get(token)

    def resolve_alias(self, alias):
        return None

    def get_state_event(self, *a, **k):
        return None

    def set_displayname(self, *a, **k):
        pass


def _bot() -> CosmacBot:
    bot = CosmacBot(CosmacConfig(llm_provider="echo", server_name="h"))
    bot.client = _C()
    bot._quota_limit = lambda uid, key: -1  # 默认不限,存储管控单测里单独桩
    bot._gate_allows = lambda *a, **k: True  # 门控另有测试;这里聚焦 CRUD/存储/隔离,放行
    return bot


AGENT = {"slug": "my-writer", "name": "小说写手", "description": "帮我写连载小说章节,续写找它",
         "system_prompt": "你是我的连载小说写手,文风轻快。"}


class TestMyStudio(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)
        self.bot = _bot()

    def test_agent_crud_and_isolation(self) -> None:
        code, _ = self.bot.handle_my_agents_save("tok", dict(AGENT))
        self.assertEqual(code, 200)
        # 本人可见
        code, payload = self.bot.handle_my_agents_list("tok")
        self.assertEqual([a["slug"] for a in payload["agents"]], ["my-writer"])
        # 别人不可见(归属隔离)
        _, p2 = self.bot.handle_my_agents_list("tok2")
        self.assertEqual(p2["agents"], [])
        # 别人删不掉(定位键含 owner)
        code, _ = self.bot.handle_my_agents_delete("tok2", {"slug": "my-writer"})
        self.assertEqual(code, 404)
        # 本人可删
        code, _ = self.bot.handle_my_agents_delete("tok", {"slug": "my-writer"})
        self.assertEqual(code, 200)

    def test_agent_requires_description(self) -> None:
        # 备注(它是干嘛的)必填——主 AI 名册匹配靠它(负责人的入库铁律)
        bad = dict(AGENT, description="")
        code, payload = self.bot.handle_my_agents_save("tok", bad)
        self.assertEqual(code, 400)
        self.assertIn("备注", payload["error"])

    def test_bad_slug_rejected(self) -> None:
        code, _ = self.bot.handle_my_agents_save("tok", dict(AGENT, slug="大写 空格"))
        self.assertEqual(code, 400)

    def test_storage_guard(self) -> None:
        self.bot._quota_limit = lambda uid, key: 1 if key == "storage_mb" else -1
        self.bot._storage_bytes = lambda uid: 1048576 - 5  # 已逼近 1MB
        code, payload = self.bot.handle_my_agents_save("tok", dict(AGENT))
        self.assertEqual(code, 400)
        self.assertIn("存储空间不足", payload["error"])

    def test_skill_crud(self) -> None:
        code, _ = self.bot.handle_my_skills_save("tok", {
            "slug": "daily-recap", "name": "每日复盘", "description": "复盘格式",
            "instructions": "按 昨日进展/今日计划/风险 三段复盘。"})
        self.assertEqual(code, 200)
        _, payload = self.bot.handle_my_skills_list("tok")
        self.assertEqual(payload["skills"][0]["slug"], "daily-recap")
        code, _ = self.bot.handle_my_skills_delete("tok", {"slug": "daily-recap"})
        self.assertEqual(code, 200)

    def test_skill_save_enforces_custom_skill_gate(self) -> None:
        # M3：工坊自建技能端点必须过 custom_skill 门控（与聊天命令同一道闸），门控未过→403
        self.bot._gate_allows = lambda uid, cap: cap != "custom_skill"  # type: ignore
        code, _ = self.bot.handle_my_skills_save("tok", {
            "slug": "x", "name": "x", "description": "d",
            "instructions": "正文"})
        self.assertEqual(code, 403)

    def test_agent_save_enforces_custom_agent_gate(self) -> None:
        # 负责人报的缺口:自建智能体此前**没有**门控。现与自建技能对称,custom_agent 未过→403
        self.bot._gate_allows = lambda uid, cap: cap != "custom_agent"  # type: ignore
        code, _ = self.bot.handle_my_agents_save("tok", dict(AGENT))
        self.assertEqual(code, 403)
        # 门控放行则照常可建(回归)
        self.bot._gate_allows = lambda *a, **k: True  # type: ignore
        code, _ = self.bot.handle_my_agents_save("tok", dict(AGENT))
        self.assertEqual(code, 200)

    def test_roster_shows_my_agent_first(self) -> None:
        self.bot.handle_my_agents_save("tok", dict(AGENT))
        out = self.bot._list_capabilities_for_tool(ToolContext("!r:h", U))
        self.assertIn("我的·小说写手", out)
        self.assertIn("连载小说", out)
        # 别人的名册看不到我的自建
        out2 = self.bot._list_capabilities_for_tool(ToolContext("!r:h", OTHER))
        self.assertNotIn("小说写手", out2)

    def test_worker_routing_hits_my_agent(self) -> None:
        self.bot.handle_my_agents_save("tok", dict(AGENT))
        gctx = {"persona": "", "worker_slugs": []}
        out = self.bot._apply_worker_routing("小说写手 继续写第三章", gctx, sender=U)
        self.assertIn("小说写手", out["persona"])
        self.assertIn("连载小说写手", out["persona"])
        # 别人点同名不路由(不是他的智能体)
        out2 = self.bot._apply_worker_routing("小说写手 你好", gctx, sender=OTHER)
        self.assertEqual(out2.get("persona"), "")

    def test_storage_counts_my_content(self) -> None:
        self.bot.handle_my_agents_save("tok", dict(AGENT))
        self.bot._storage_cache = {}
        n = self.bot._storage_bytes(U)
        expect = len(AGENT["name"]) + len(AGENT["description"]) + len(AGENT["system_prompt"])
        self.assertGreaterEqual(n, expect)


if __name__ == "__main__":
    unittest.main()
