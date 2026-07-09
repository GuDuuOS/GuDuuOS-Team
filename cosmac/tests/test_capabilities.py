"""能力名册（模块3.5 档1）单元测试：聚合 真人/Agent/Skill/知识库 + 各自能力备注。

内存 SQLite、零 key；用假控制室 state event 喂 people/agents/skills。
运行：.venv/bin/python -m unittest cosmac.tests.test_capabilities
"""

from __future__ import annotations

import unittest

from cosmac.ai.tools import ToolContext
from cosmac.config import (
    AGENTS_EVENT_TYPE,
    PEOPLE_EVENT_TYPE,
    SKILLS_EVENT_TYPE,
)
from cosmac.db import init_engine


class FakeClient:
    """假 client：按 event_type 返回不同控制室 state event 内容。"""

    def __init__(self, states):
        self._states = states

    def resolve_alias(self, alias):
        return "!ctrl:h"

    def get_state_event(self, room_id, etype, state_key=""):
        return self._states.get(etype)

    def set_displayname(self, *a, **k):
        pass

    def send_text(self, *a, **k):
        return "$e"


def _bot(states):
    from cosmac.bots.appservice_bot import CosmacBot
    from cosmac.config import CosmacConfig

    # server_name 与测试里的人员/房间域名(:h)对齐——能力名册按 server_name 过滤外域假号,
    # 不对齐会把 @xiaoyu:h 这类正常测试人员当外域滤掉。
    bot = CosmacBot(CosmacConfig(llm_provider="echo", server_name="h"))
    bot.client = FakeClient(states)
    return bot


class TestCapabilityRegistry(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)

    def test_aggregates_people_agents_skills(self) -> None:
        states = {
            PEOPLE_EVENT_TYPE: {"people": [
                {"user_id": "@xiaoyu:h", "name": "小雨", "role": "文案",
                 "expertise": "小红书种草", "enabled": True},
                {"user_id": "@off:h", "name": "停用的", "enabled": False},
            ]},
            AGENTS_EVENT_TYPE: {"agents": [
                {"slug": "copywriter", "name": "文案助手",
                 "description": "扩写分镜脚本", "skill_slugs": ["script"], "enabled": True},
            ]},
            SKILLS_EVENT_TYPE: {"skills": [
                {"slug": "weekly", "name": "周报", "description": "生成周报", "enabled": True},
            ]},
        }
        out = _bot(states)._list_capabilities_for_tool(ToolContext("!r:h", "@u:h"))
        # 真人
        self.assertIn("@xiaoyu:h", out)
        self.assertIn("小雨", out)
        self.assertIn("小红书种草", out)
        # 停用的人不列
        self.assertNotIn("停用的", out)
        # AI Agent
        self.assertIn("copywriter", out)
        self.assertIn("扩写分镜脚本", out)
        # Skill
        self.assertIn("weekly", out)
        # 分区标题
        self.assertIn("真人", out)
        self.assertIn("AI Agent", out)

    def test_presets_present_when_no_config(self) -> None:
        # 即使没配任何真人/控制室智能体，名册也含内置预置 Agent（开箱即用的 AI 班底）。
        out = _bot({})._list_capabilities_for_tool(ToolContext("!r:h", "@u:h"))
        self.assertIn("AI Agent", out)
        self.assertIn("copywriter", out)  # 预置之一：文案
        self.assertNotIn("空", out)        # 不再是"空名册"

    def test_people_reader_filters_disabled(self) -> None:
        states = {PEOPLE_EVENT_TYPE: {"people": [
            {"user_id": "@a:h", "enabled": True},
            {"user_id": "@b:h", "enabled": False},
            {"user_id": "@c:h"},  # 缺 enabled 默认启用
        ]}}
        people = _bot(states)._people_items()
        uids = {p["user_id"] for p in people}
        self.assertEqual(uids, {"@a:h", "@c:h"})


if __name__ == "__main__":
    unittest.main()
