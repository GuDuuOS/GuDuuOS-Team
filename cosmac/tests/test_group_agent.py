"""本群绑定智能体 / 自定义人设 → bot 注入的单元测试。

用假 MatrixClient 模拟「频道配置 + 控制室里的全局智能体/技能」三个 state event，
验证 bot 的 _skill_addendum 会按本群绑定注入对应人设与技能。不连真服务器、不需要 key。

运行：.venv/bin/python -m unittest cosmac.tests.test_group_agent
"""

from __future__ import annotations

import os
import unittest
from typing import Any, Optional
from unittest import mock

from cosmac.bots.appservice_bot import CosmacBot
from cosmac.config import (
    AGENTS_EVENT_TYPE,
    CHANNEL_CONFIG_EVENT_TYPE,
    RULES_EVENT_TYPE,
    SKILLS_EVENT_TYPE,
    CosmacConfig,
)
from cosmac.db import init_engine
from cosmac.members import GatingStore, MembersStore

CTRL = "!ctrl:host"
ROOM = "!grp:host"


class FakeClient:
    """按 (event_type) 返回不同 state event；其余调用给安全默认。"""

    def __init__(self, channel_cfg=None, agents=None, skills=None, rules=None, messages=None):
        self._by_type = {
            CHANNEL_CONFIG_EVENT_TYPE: channel_cfg,
            AGENTS_EVENT_TYPE: agents,
            SKILLS_EVENT_TYPE: skills,
            RULES_EVENT_TYPE: rules,
        }
        self._messages = messages or []

    def set_displayname(self, *_a, **_k): pass
    def send_text(self, *_a, **_k): return "$e"
    def resolve_alias(self, _alias: str) -> Optional[str]: return CTRL
    def joined_member_count(self, _room: str) -> int: return 5  # 群聊

    def get_state_event(self, _room_id: str, event_type: str, _state_key: str = "") -> Any:
        return self._by_type.get(event_type)

    def get_messages(self, _room_id: str, limit: int = 20):
        return self._messages[-limit:]


def _bot(channel_cfg=None, agents=None, skills=None, rules=None, messages=None) -> CosmacBot:
    bot = CosmacBot(CosmacConfig(llm_provider="echo"))
    bot.client = FakeClient(channel_cfg, agents, skills, rules, messages)
    # 所有读取都注入同一个假 client，避免测试触发真实 Matrix 网络请求。
    bot.members = MembersStore(bot.client, bot.config.control_room_alias)
    bot.gating = GatingStore(bot.client, bot.config.control_room_alias, ttl=0)
    return bot


class TestGroupAgent(unittest.TestCase):
    def setUp(self) -> None:
        # 清掉 embedding key → RAG 用哈希词袋、不发真实网络请求（测试隔离）
        p = mock.patch.dict(os.environ, {}, clear=False)
        p.start()
        self.addCleanup(p.stop)
        for k in ("COSMAC_EMBED_API_KEY", "OPENAI_API_KEY", "ARK_API_KEY"):
            os.environ.pop(k, None)
        init_engine("sqlite://", create_all=True)  # 隔离的空 DB（群/个人技能为空）

    def test_bound_agent_injects_persona_and_skills(self) -> None:
        bot = _bot(
            channel_cfg={"persona": {"agentSlug": "planner"}},
            agents={"agents": [
                {"slug": "planner", "name": "策划", "system_prompt": "你是资深策划",
                 "skill_slugs": ["s1"], "enabled": True},
            ]},
            skills={"skills": [
                {"slug": "s1", "name": "周报", "instructions": "三步生成周报", "enabled": True},
                {"slug": "s2", "name": "选题", "instructions": "选题方法", "enabled": True},
            ]},
        )
        out = bot._skill_addendum(ROOM, "@u:host")
        self.assertIn("已绑定智能体「策划」", out)
        self.assertIn("你是资深策划", out)
        self.assertIn("三步生成周报", out)  # 绑定的技能 s1 注入

    def test_disabled_agent_falls_back_to_nothing(self) -> None:
        bot = _bot(
            channel_cfg={"persona": {"agentSlug": "planner"}},
            agents={"agents": [{"slug": "planner", "name": "策划", "enabled": False}]},
            skills={"skills": []},
        )
        out = bot._skill_addendum(ROOM, "@u:host")
        self.assertNotIn("已绑定智能体", out)  # 停用 → 找不到 → 不注入人设

    def test_free_text_persona_when_no_agent(self) -> None:
        bot = _bot(
            channel_cfg={"persona": {"prompt": "本群只聊技术"}},
            agents={"agents": []},
            skills={"skills": []},
        )
        out = bot._skill_addendum(ROOM, "@u:host")
        self.assertIn("本群人设", out)
        self.assertIn("本群只聊技术", out)

    def test_no_config_only_interaction_policy(self) -> None:
        # 没有任何人设/规则/技能时，addendum 仍含内置「交互行为准则」基线（其它部分为空）。
        bot = _bot(channel_cfg=None, agents=None, skills=None)
        out = bot._skill_addendum(ROOM, "@u:host")
        self.assertIn("交互行为准则", out)
        # 除了准则不应再有别的内容块（用分隔符数量粗略验证：只有一段）
        self.assertNotIn("【必须严格遵守", out)

    def test_custom_persona_carries_model_and_skills(self) -> None:
        # 入驻模板 P2b：自定义人设里带 model/skill_slugs（引导写入），_group_context 应读出来
        bot = _bot(
            channel_cfg={"persona": {
                "prompt": "影视助手", "model": "claude-opus-4-8", "skill_slugs": ["weekly"],
            }},
            agents={"agents": []},
            skills={"skills": []},
        )
        gctx = bot._group_context(ROOM)
        self.assertEqual(gctx["model"], "claude-opus-4-8")
        self.assertEqual(gctx["skill_slugs"], ["weekly"])
        self.assertIn("影视助手", gctx["persona"])

    def test_group_model_override_picks_distinct_agent(self) -> None:
        bot = _bot(
            channel_cfg={"persona": {"agentSlug": "planner"}},
            agents={"agents": [
                {"slug": "planner", "name": "策划", "model": "deepseek-v3.2", "enabled": True},
            ]},
        )
        gctx = bot._group_context(ROOM)
        self.assertEqual(gctx["model"], "deepseek-v3.2")
        # 指定了模型 → 拿到一个不同于默认的 Agent，且会被缓存（同一对象复用）
        a1 = bot._agent_for_model(gctx["model"])
        self.assertIsNot(a1, bot.agent)
        self.assertIs(a1, bot._agent_for_model(gctx["model"]))
        # 没指定模型 → 用默认 Agent
        self.assertIs(bot._agent_for_model(""), bot.agent)

    def test_recent_history_maps_roles_and_drops_current(self) -> None:
        bot_id = "@guduu:guduu.local"  # 默认 config 的 bot_user_id
        msgs = [
            {"sender": "@u:host", "body": "第一句"},
            {"sender": bot_id, "body": "我的回答"},
            {"sender": "@u:host", "body": "当前这句"},  # 触发消息，应被排除
        ]
        bot = _bot(messages=msgs)
        hist = bot._recent_history(ROOM, "@u:host", "当前这句")
        self.assertEqual([(m.role, m.content) for m in hist],
                         [("user", "第一句"), ("assistant", "我的回答")])

    def test_global_rules_injected_and_filtered(self) -> None:
        bot = _bot(rules={"rules": [
            {"text": "对外报价必须经负责人确认", "enabled": True},
            {"text": "不得编造数据", "enabled": True},
            {"text": "这条停用的不该出现", "enabled": False},
        ]})
        out = bot._skill_addendum(ROOM, "@u:host", query="随便问")
        self.assertIn("必须严格遵守", out)
        self.assertIn("对外报价必须经负责人确认", out)
        self.assertIn("不得编造数据", out)
        self.assertNotIn("这条停用的不该出现", out)
        # 顺序：当前时间在最前，其后内置「交互行为准则」基线，平台硬规则紧随（仍高于人设/技能等）
        self.assertTrue(out.startswith("【当前时间"))
        self.assertLess(out.index("【当前时间"), out.index("【交互行为准则"))
        self.assertLess(out.index("【交互行为准则"), out.index("【必须严格遵守"))

    def test_rag_injects_relevant_kb_chunk(self) -> None:
        # 本群知识库里有文档 → 提问相关问题时，addendum 注入检索到的片段
        from cosmac.db import session_scope
        from cosmac.db.kb import ingest_document
        with session_scope() as s:
            ingest_document(s, scope="room", scope_id=ROOM, title="报价规则",
                            text="商单报价：口播报价高于植入，最终报价需筱雨确认。")
        bot = _bot(channel_cfg=None, agents=None, skills=None)
        out = bot._skill_addendum(ROOM, "@u:host", query="商单怎么报价")
        self.assertIn("知识库", out)
        self.assertIn("报价规则", out)

    def test_global_skills_still_inject_without_binding(self) -> None:
        # 没绑智能体，但有全局技能 → 全局技能照常注入（不依赖绑定）
        bot = _bot(
            channel_cfg=None,
            agents=None,
            skills={"skills": [{"slug": "g", "name": "全局技能", "instructions": "G正文", "enabled": True}]},
        )
        out = bot._skill_addendum(ROOM, "@u:host")
        self.assertIn("全局技能", out)
        self.assertIn("G正文", out)


if __name__ == "__main__":
    unittest.main()
