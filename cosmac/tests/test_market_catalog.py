# -*- coding: utf-8 -*-
"""「AI Agent 商城」目录端点(handle_market_catalog)的单元测试。

覆盖:未登录 401、按发起人标注解锁状态(access 判定)、仅管理员资源对普通用户隐藏、
工作流按 workflow_run 门控整类显隐、敏感字段(system_prompt/instructions/url/cred)绝不下发。
不连 Synapse、不连 DB(管理员/等级/模板全打桩;平台知识库无 DB 时该分类安静跳过)。

运行:.venv/bin/python -m unittest cosmac.tests.test_market_catalog
"""

from __future__ import annotations

import unittest

from cosmac.bots.appservice_bot import CosmacBot
from cosmac.config import CosmacConfig

CTRL = "!ctrl:test"

# 控制室配置的智能体:公共/付费/仅管理员 各一个(system_prompt 是敏感字段,绝不能下发)
AGENTS = [
    {"slug": "pub-agent", "name": "公共智能体", "description": "谁都能用",
     "system_prompt": "秘密人设", "enabled": True},
    {"slug": "paid-agent", "name": "付费智能体", "description": "付费+",
     "system_prompt": "秘密人设2", "access": "paid", "enabled": True},
    {"slug": "adm-agent", "name": "管理员智能体", "description": "仅管理员",
     "system_prompt": "秘密人设3", "access": "admin", "enabled": True},
    {"slug": "off-agent", "name": "停用智能体", "description": "已停用",
     "system_prompt": "x", "enabled": False},
]
SKILLS = [
    {"slug": "pub-skill", "name": "公共技能", "description": "d",
     "instructions": "秘密套路", "enabled": True},
    {"slug": "paid-skill", "name": "付费技能", "description": "d",
     "instructions": "秘密套路2", "access": "paid", "enabled": True},
]
# 工作流连接器:url/cred 是密钥线索,绝不能下发
WORKFLOWS = [
    {"slug": "wf-1", "name": "测试工作流", "platform": "webhook",
     "url": "https://inner.example/hook", "cred": "SECRET_NAME", "enabled": True},
]


class FakeClient:
    """喂控制室 智能体/技能/工作流 state 的假 client;whoami 按 token 直译。"""

    def set_displayname(self, *_a, **_k):
        pass

    def whoami(self, token):
        # token 形如 "tok-@u:test" → 返回 "@u:test";空/不合法 → None(未登录)
        return token[4:] if token and token.startswith("tok-") else None

    def resolve_alias(self, _alias):
        return CTRL

    def get_state_event(self, room_id, etype, state_key=""):
        if room_id != CTRL:
            return None
        if etype == "cosmac.agents":
            return {"agents": AGENTS}
        if etype == "cosmac.skills":
            return {"skills": SKILLS}
        if etype == "cosmac.workflows":
            return {"workflows": WORKFLOWS}
        return None  # gating/members 等都走各自 store 的默认值


def _bot() -> CosmacBot:
    bot = CosmacBot(CosmacConfig(llm_provider="echo"))
    bot.client = FakeClient()
    bot._is_platform_admin = lambda uid: uid == "@adm:test"  # type: ignore
    bot.members.get_tier = lambda uid: {  # type: ignore
        "@paid:test": "paid",
    }.get(uid, "free")
    bot._user_template = lambda uid: ""  # type: ignore
    return bot


def _items(payload, kind=None):
    its = payload["items"]
    return [i for i in its if kind is None or i["kind"] == kind]


class TestMarketCatalog(unittest.TestCase):
    def setUp(self) -> None:
        self.bot = _bot()

    def test_requires_login(self) -> None:
        code, _ = self.bot.handle_market_catalog("")
        self.assertEqual(code, 401)

    def test_free_user_sees_lock_states_and_no_admin_items(self) -> None:
        code, payload = self.bot.handle_market_catalog("tok-@free:test")
        self.assertEqual(code, 200)
        agents = {i["slug"]: i for i in _items(payload, "agent")}
        # 公共=解锁;付费=列出但未解锁;仅管理员/停用=整条不出现
        self.assertTrue(agents["pub-agent"]["unlocked"])
        self.assertFalse(agents["paid-agent"]["unlocked"])
        self.assertEqual(agents["paid-agent"]["access"], "paid")
        self.assertNotIn("adm-agent", agents)
        self.assertNotIn("off-agent", agents)
        skills = {i["slug"]: i for i in _items(payload, "skill")}
        self.assertTrue(skills["pub-skill"]["unlocked"])
        self.assertFalse(skills["paid-skill"]["unlocked"])
        # workflow_run 默认门槛=仅管理员 → 普通用户整类隐藏
        self.assertEqual(_items(payload, "workflow"), [])
        self.assertEqual(payload["tier"], "free")
        self.assertFalse(payload["is_admin"])

    def test_paid_user_unlocks_paid_items(self) -> None:
        _, payload = self.bot.handle_market_catalog("tok-@paid:test")
        agents = {i["slug"]: i for i in _items(payload, "agent")}
        self.assertTrue(agents["paid-agent"]["unlocked"])
        skills = {i["slug"]: i for i in _items(payload, "skill")}
        self.assertTrue(skills["paid-skill"]["unlocked"])

    def test_admin_sees_admin_items_and_workflows(self) -> None:
        _, payload = self.bot.handle_market_catalog("tok-@adm:test")
        agents = {i["slug"]: i for i in _items(payload, "agent")}
        self.assertIn("adm-agent", agents)
        self.assertTrue(agents["adm-agent"]["unlocked"])
        wfs = {i["slug"]: i for i in _items(payload, "workflow")}
        self.assertIn("wf-1", wfs)
        self.assertTrue(wfs["wf-1"]["unlocked"])
        self.assertTrue(payload["is_admin"])

    def test_no_sensitive_fields_leak(self) -> None:
        # 解锁与否都不能带出 人设正文/技能正文/工作流 url 与凭据名
        for token in ("tok-@free:test", "tok-@adm:test"):
            _, payload = self.bot.handle_market_catalog(token)
            for it in payload["items"]:
                for banned in ("system_prompt", "instructions", "url", "cred", "graph"):
                    self.assertNotIn(banned, it, f"{it['kind']}:{it['slug']} 泄露 {banned}")


if __name__ == "__main__":
    unittest.main()
