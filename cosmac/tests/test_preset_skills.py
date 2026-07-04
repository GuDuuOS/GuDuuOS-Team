# -*- coding: utf-8 -*-
"""预置技能库 + Agent 绑定激活的单元测试。

验证:
  1. 预置技能库结构完整、单条不超注入预算、每个被预置 Agent 绑的 slug 都真实存在;
  2. _skill_library 合并(预置打底 + 控制室覆盖/追加);
  3. _agent_skill_items 能解析出预置技能(=预置 Agent 被激活时方法论随之注入);
  4. **关键隔离**:_global_skill_items(全局注入)**不含**预置技能——不撑爆 6000 字符预算。

不连 Synapse:控制室 state 打桩。
"""

from __future__ import annotations

import unittest

from cosmac.ai.preset_skills import preset_skills
from cosmac.ai.presets import preset_agents
from cosmac.bots.appservice_bot import CosmacBot
from cosmac.config import CosmacConfig
from cosmac.skills_text import MAX_TOTAL_PROMPT_CHARS

CTRL = "!ctrl:test"


class FakeClient:
    """按需喂控制室技能 state 的假 client(空=控制室没配技能)。"""

    def __init__(self, ctrl_skills=None):
        self._ctrl_skills = ctrl_skills or []

    def set_displayname(self, *_a, **_k):
        pass

    def resolve_alias(self, _alias):
        return CTRL

    def get_state_event(self, room_id, etype, state_key=""):
        if etype == "cosmac.skills" and room_id == CTRL:
            return {"skills": self._ctrl_skills}
        return None


def _bot(ctrl_skills=None) -> CosmacBot:
    bot = CosmacBot(CosmacConfig(llm_provider="echo"))
    bot.client = FakeClient(ctrl_skills)
    return bot


class TestPresetSkillsDefs(unittest.TestCase):
    def test_bindings_resolve(self) -> None:
        # 每个预置 Agent 绑的 skill_slugs 都在预置技能库里(没有悬空绑定)
        lib = {s["slug"] for s in preset_skills()}
        for a in preset_agents():
            for slug in a.get("skill_slugs", []):
                self.assertIn(slug, lib, f"Agent {a['slug']} 绑了不存在的技能 {slug}")

    def test_single_skill_within_budget(self) -> None:
        # 单条技能远小于总预算——Agent 激活时注入 1~2 个不会被截断
        for s in preset_skills():
            self.assertLess(len(s["instructions"]), MAX_TOTAL_PROMPT_CHARS // 3, s["slug"])

    def test_fields_present(self) -> None:
        for s in preset_skills():
            for k in ("slug", "name", "description", "instructions", "enabled"):
                self.assertIn(k, s)
            self.assertTrue(s["slug"] and s["instructions"])


class TestSkillLibraryMerge(unittest.TestCase):
    def test_library_has_presets_when_ctrl_empty(self) -> None:
        # 控制室没配技能时,技能库=全部预置
        bot = _bot([])
        lib = {s["slug"] for s in bot._skill_library()}
        self.assertEqual(lib, {s["slug"] for s in preset_skills()})

    def test_ctrl_overrides_and_appends(self) -> None:
        # 控制室同 slug 覆盖预置、新 slug 追加
        bot = _bot([
            {"slug": "marketing-campaign", "name": "改写版", "instructions": "X", "enabled": True},
            {"slug": "custom-one", "name": "自定义", "instructions": "Y", "enabled": True},
        ])
        lib = {s["slug"]: s for s in bot._skill_library()}
        self.assertEqual(lib["marketing-campaign"]["name"], "改写版")  # 覆盖
        self.assertIn("custom-one", lib)                               # 追加
        self.assertIn("content-calendar", lib)                        # 预置仍在

    def test_ctrl_can_disable_preset(self) -> None:
        # 控制室把某预置 slug enabled=false → 从库里消失
        bot = _bot([{"slug": "user-persona", "enabled": False}])
        self.assertNotIn("user-persona", {s["slug"] for s in bot._skill_library()})


class TestAgentActivatesPresetSkill(unittest.TestCase):
    def test_agent_skill_items_resolves_preset(self) -> None:
        # planner 绑了 marketing-campaign(预置)→ 激活时能解析出该技能字典
        bot = _bot([])
        items = bot._agent_skill_items(["marketing-campaign", "content-calendar"])
        slugs = {i["slug"] for i in items}
        self.assertEqual(slugs, {"marketing-campaign", "content-calendar"})
        self.assertTrue(any("受众" in i["instructions"] for i in items))

    def test_global_inject_excludes_presets(self) -> None:
        # 关键隔离:全局注入(_global_skill_items,只读控制室)绝不含预置技能——
        # 否则 9 个方法论每轮全塞,撑爆 6000 预算。控制室空 → 全局注入为空。
        bot = _bot([])
        self.assertEqual(bot._global_skill_items(), [])
        self.assertEqual(bot._global_skill_items(for_user="@u:test"), [])


if __name__ == "__main__":
    unittest.main()
