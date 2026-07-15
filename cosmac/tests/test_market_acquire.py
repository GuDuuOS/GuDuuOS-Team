# -*- coding: utf-8 -*-
"""商城「已获取」链路(acquire/list 端点 + 主 AI 名册标注)的单元测试。

覆盖:获取/幂等/移除、服务端校验(不存在 404/未解锁 403/参数 400)、按人隔离、
已获取列表回显(含 stale 标注)、能力名册的 ★ 标注与前置排序、缓存主动失效。
DB 用内存 SQLite;Synapse 相关全打桩。

运行:.venv/bin/python -m unittest cosmac.tests.test_market_acquire
"""

from __future__ import annotations

import unittest
from typing import Optional

from cosmac.ai.tools import ToolContext
from cosmac.bots.appservice_bot import CosmacBot
from cosmac.config import CosmacConfig
from cosmac.config import CHANNEL_CONFIG_EVENT_TYPE
from cosmac.db import init_engine

CTRL = "!ctrl:h"
TEAM_ROOM = "!team:h"  # 绑定了 copywriter 当 worker 的"专班"频道
U = "@u:h"
OTHER = "@other:h"

AGENTS = [
    {"slug": "pub-agent", "name": "公共智能体", "description": "谁都能用",
     "system_prompt": "x", "enabled": True},
    {"slug": "paid-agent", "name": "付费智能体", "description": "付费+",
     "system_prompt": "x", "access": "paid", "enabled": True},
]


class _C:
    def whoami(self, token: str) -> Optional[str]:
        return {"tok": U, "tok2": OTHER}.get(token)

    def resolve_alias(self, alias):
        return CTRL

    def get_state_event(self, room_id, etype, state_key=""):
        if room_id == CTRL and etype == "cosmac.agents":
            return {"agents": AGENTS}
        if room_id == TEAM_ROOM and etype == CHANNEL_CONFIG_EVENT_TYPE:
            return {"agentSlugs": ["pub-agent"]}  # 专班绑定 pub-agent 当 worker
        return None

    def set_displayname(self, *a, **k):
        pass

    def get_members(self, room_id):
        return []


def _bot() -> CosmacBot:
    bot = CosmacBot(CosmacConfig(llm_provider="echo", server_name="h"))
    bot.client = _C()
    bot._is_platform_admin = lambda uid: False  # type: ignore
    bot.members.get_tier = lambda uid: "free"  # type: ignore
    bot._user_template = lambda uid: ""  # type: ignore
    return bot


class TestMarketAcquire(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)
        self.bot = _bot()

    def test_acquire_and_list_and_remove(self) -> None:
        # 获取一个真实存在且解锁的资源 → 成功且幂等
        for _ in range(2):
            code, p = self.bot.handle_market_acquire(
                "tok", {"kind": "agent", "slug": "pub-agent"})
            self.assertEqual(code, 200)
            self.assertTrue(p["acquired"])
        code, p = self.bot.handle_market_acquired_list("tok")
        self.assertEqual(code, 200)
        self.assertEqual([(i["kind"], i["slug"]) for i in p["items"]],
                         [("agent", "pub-agent")])
        self.assertEqual(p["items"][0]["name"], "公共智能体")
        self.assertFalse(p["items"][0]["stale"])
        # 目录端点回显 acquired 标注
        _, cat = self.bot.handle_market_catalog("tok")
        got = {i["slug"]: i for i in cat["items"] if i["kind"] == "agent"}
        self.assertTrue(got["pub-agent"]["acquired"])
        self.assertFalse(got["paid-agent"]["acquired"])
        # 移除 → 列表清空
        code, p = self.bot.handle_market_acquire(
            "tok", {"kind": "agent", "slug": "pub-agent", "acquired": False})
        self.assertEqual(code, 200)
        _, p = self.bot.handle_market_acquired_list("tok")
        self.assertEqual(p["items"], [])

    def test_server_side_validation(self) -> None:
        # 未登录
        self.assertEqual(self.bot.handle_market_acquire(
            "bad", {"kind": "agent", "slug": "pub-agent"})[0], 401)
        # 参数不合法
        self.assertEqual(self.bot.handle_market_acquire(
            "tok", {"kind": "prompt", "slug": "x"})[0], 400)
        # 货架上没有 → 404
        self.assertEqual(self.bot.handle_market_acquire(
            "tok", {"kind": "agent", "slug": "ghost"})[0], 404)
        # 未解锁(免费用户拿付费资源) → 403
        self.assertEqual(self.bot.handle_market_acquire(
            "tok", {"kind": "agent", "slug": "paid-agent"})[0], 403)

    def test_isolation_between_users(self) -> None:
        self.bot.handle_market_acquire("tok", {"kind": "agent", "slug": "pub-agent"})
        _, p = self.bot.handle_market_acquired_list("tok2")
        self.assertEqual(p["items"], [])  # 别人的账号看不到我的获取

    def test_stale_when_item_removed_from_shelf(self) -> None:
        self.bot.handle_market_acquire("tok", {"kind": "agent", "slug": "pub-agent"})
        AGENTS[0]["enabled"] = False  # 资源被后台停用(下架)
        try:
            _, p = self.bot.handle_market_acquired_list("tok")
            self.assertTrue(p["items"][0]["stale"])
        finally:
            AGENTS[0]["enabled"] = True

    def test_group_trigger_by_agent_mention(self) -> None:
        """群聊补充触发(_agent_mention_hit):点名可路由智能体才应答,防误触发。"""
        room = "!plain:h"  # 普通频道,没绑 worker
        # 未获取、非专班、无自建 → @copywriter 不触发(可路由集合为空)
        self.assertFalse(self.bot._agent_mention_hit(room, U, "@pub-agent 帮忙润色"))
        # 专班频道:绑定的 worker 按 @slug / slug开头 都触发
        self.assertTrue(self.bot._agent_mention_hit(TEAM_ROOM, U, "@pub-agent 帮忙润色"))
        self.assertTrue(self.bot._agent_mention_hit(TEAM_ROOM, U, "pub-agent 进度如何"))
        self.assertTrue(self.bot._agent_mention_hit(TEAM_ROOM, U, "@公共智能体 帮忙润色"))
        self.assertFalse(self.bot._agent_mention_hit(TEAM_ROOM, U, "今天天气不错"))
        # 商城获取后:任意频道 @点名 触发;但名字只出现在正文(不带@)不触发(防日常词乱入)
        self.bot.handle_market_acquire("tok", {"kind": "agent", "slug": "pub-agent"})
        self.assertTrue(self.bot._agent_mention_hit(room, U, "@pub-agent 帮忙润色"))
        self.assertTrue(self.bot._agent_mention_hit(room, U, "请 @公共智能体 帮忙润色"))
        self.assertFalse(self.bot._agent_mention_hit(room, U, "帮我找公共智能体聊聊"))
        # 别人没获取,同一条消息不触发
        self.assertFalse(self.bot._agent_mention_hit(room, OTHER, "@pub-agent 帮忙润色"))

    def test_routing_falls_back_to_acquired_agent(self) -> None:
        """路由(_apply_worker_routing):非专班频道里 @已获取的智能体 → 切到它的人设。"""
        self.bot.handle_market_acquire("tok", {"kind": "agent", "slug": "pub-agent"})
        gctx = {"worker_slugs": [], "persona": "", "skill_slugs": [], "model": ""}
        out = self.bot._apply_worker_routing("@pub-agent 帮忙润色", dict(gctx), sender=U)
        self.assertIn("公共智能体", out["persona"])  # 切到已获取智能体的人设
        # 不带 @ 只提到名字 → 不切(仍是 lead)
        out2 = self.bot._apply_worker_routing("帮我写个公共智能体介绍", dict(gctx), sender=U)
        self.assertEqual(out2["persona"], "")

    def test_trigger_and_route_share_inputs(self) -> None:
        """评审 #1 回归:触发命中的输入形态,路由必须同样命中(单一匹配源)。"""
        self.bot.handle_market_acquire("tok", {"kind": "agent", "slug": "pub-agent"})
        gctx = {"worker_slugs": [], "persona": "", "skill_slugs": [], "model": ""}
        # 场景一:句首 @(此前 handler 把剥过 @ 的文本传给路由 → 路由 miss);
        # 现在 handler 统一传原始正文,路由直接收原文即应命中。
        raw = "@pub-agent 帮忙润色这段"
        self.assertTrue(self.bot._agent_mention_hit("!plain:h", U, raw))
        out = self.bot._apply_worker_routing(raw, dict(gctx), sender=U)
        self.assertIn("公共智能体", out["persona"])
        # 场景二:mention pill(正文只有显示名、MXID 在 m.mentions)——触发与路由都吃 mentions。
        pill_body, mentions = "公共智能体 帮忙润色", ["@guduu-ai-pub-agent:h"]
        self.assertTrue(self.bot._agent_mention_hit("!plain:h", U, pill_body, mentions))
        out2 = self.bot._apply_worker_routing(
            pill_body, dict(gctx), sender=U, mentioned_ids=mentions)
        self.assertIn("公共智能体", out2["persona"])

    def test_acquired_rechecks_access_on_use(self) -> None:
        """评审 #2 回归:已获取的受限智能体,使用时刻仍要过 access——会员到期即失效。"""
        from cosmac.db import session_scope
        from cosmac.db.market_repo import add_acquired

        # 模拟"付费期内获取过 paid-agent"(直插 DB,绕过端点的获取时校验)
        with session_scope() as s:
            add_acquired(s, user_id=U, kind="agent", slug="paid-agent")
        gctx = {"worker_slugs": [], "persona": "", "skill_slugs": [], "model": ""}
        # 现在 tier=free(见 _bot 桩):@ 它不触发、不路由——不再"获取一次终身可用"
        self.assertFalse(self.bot._agent_mention_hit("!plain:h", U, "@paid-agent 干活"))
        out = self.bot._apply_worker_routing("@paid-agent 干活", dict(gctx), sender=U)
        self.assertEqual(out["persona"], "")
        # 会员恢复付费 → 立即可用(access 每次实时判定)
        self.bot.members.get_tier = lambda uid: "paid"  # type: ignore
        self.assertTrue(self.bot._agent_mention_hit("!plain:h", U, "@paid-agent 干活"))
        out2 = self.bot._apply_worker_routing("@paid-agent 干活", dict(gctx), sender=U)
        self.assertIn("付费智能体", out2["persona"])

    def test_word_boundary_prevents_casual_trigger(self) -> None:
        """评审 #4 回归:worker 名是日常词时,「名字+后续汉字」不算点名,不乱入人聊天。"""
        # TEAM_ROOM 绑定 pub-agent(名「公共智能体」)当 worker
        self.assertFalse(self.bot._agent_mention_hit(
            TEAM_ROOM, U, "公共智能体们最近都很忙"))   # 名字后跟汉字=词头,不触发
        self.assertTrue(self.bot._agent_mention_hit(
            TEAM_ROOM, U, "公共智能体 请出个方案"))     # 成词(后跟空白)→ 触发
        self.assertTrue(self.bot._agent_mention_hit(
            TEAM_ROOM, U, "公共智能体，请出个方案"))    # 成词(后跟标点)→ 触发

    def test_roster_marks_acquired_with_star(self) -> None:
        ctx = ToolContext(room_id="!r:h", sender=U, is_dm=True)
        # 获取前:名册里无 ★
        text = self.bot._list_capabilities_for_tool(ctx)
        self.assertNotIn("★pub-agent", text)
        # 获取后:缓存被主动失效,名册立刻带 ★ 且有优先派单说明
        self.bot.handle_market_acquire("tok", {"kind": "agent", "slug": "pub-agent"})
        text = self.bot._list_capabilities_for_tool(ctx)
        self.assertIn("★pub-agent", text)
        self.assertIn("已获取", text)
        # 其他用户的名册不受影响
        ctx2 = ToolContext(room_id="!r:h", sender=OTHER, is_dm=True)
        self.assertNotIn("★pub-agent", self.bot._list_capabilities_for_tool(ctx2))


if __name__ == "__main__":
    unittest.main()
