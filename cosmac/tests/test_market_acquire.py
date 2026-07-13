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
from cosmac.db import init_engine

CTRL = "!ctrl:h"
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
