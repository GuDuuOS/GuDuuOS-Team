# -*- coding: utf-8 -*-
"""方案B「AI 同事傀儡账号」单测:注册/进频道/路由带身份/触发识别/回环防护。

负责人拍板方案B:每个协作 Agent 一个独立 Matrix 账号(@guduu-ai-<slug>),像真成员
一样出现在频道里、以自己的名字发消息。Synapse 交互全打桩,聚焦 bot 侧逻辑。

运行:.venv/bin/python -m unittest cosmac.tests.test_worker_puppet
"""

from __future__ import annotations

import unittest
from typing import List, Optional

from cosmac.bots.appservice_bot import CosmacBot
from cosmac.config import CosmacConfig
from cosmac.db import init_engine

ROOM = "!team:h"
U = "@u:h"

AGENTS = {
    "copywriter": {"slug": "copywriter", "name": "文案", "system_prompt": "你是文案", "model": ""},
}


class _C:
    """打桩 Matrix client:记录傀儡相关调用;可配置注册失败。"""

    def __init__(self) -> None:
        self.registered: List[str] = []
        self.displaynames: List[tuple] = []
        self.invited: List[tuple] = []
        self.joined: List[tuple] = []
        self.sent_as: List[tuple] = []
        self.register_ok = True

    def register_appservice_user(self, localpart: str) -> bool:
        self.registered.append(localpart)
        return self.register_ok

    def set_displayname_as(self, user_id: str, name: str) -> bool:
        self.displaynames.append((user_id, name))
        return True

    def invite_user(self, room_id: str, user_id: str) -> bool:
        self.invited.append((room_id, user_id))
        return True

    def join_room_as(self, room_id: str, user_id: str) -> bool:
        self.joined.append((room_id, user_id))
        return True

    def send_text_as(self, room_id, text, user_id, txn_id=None):
        self.sent_as.append((room_id, text, user_id))
        return "$evt"

    def whoami(self, token: str) -> Optional[str]:
        return U

    def resolve_alias(self, alias):
        return None

    def get_state_event(self, *a, **k):
        return None

    def set_displayname(self, *a, **k):
        pass


def _bot() -> CosmacBot:
    bot = CosmacBot(CosmacConfig(llm_provider="echo", server_name="h"))
    bot.client = _C()
    bot._find_global_agent = lambda slug: AGENTS.get(slug)  # type: ignore
    return bot


class TestWorkerPuppet(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)
        self.bot = _bot()

    def test_ensure_account_and_room_idempotent(self) -> None:
        uid = self.bot._ensure_worker_in_room(ROOM, "copywriter")
        self.assertEqual(uid, "@guduu-ai-copywriter:h")
        c = self.bot.client
        self.assertEqual(c.registered, ["guduu-ai-copywriter"])
        self.assertEqual(c.displaynames, [(uid, "文案")])  # 显示名=智能体名
        self.assertIn((ROOM, uid), c.invited)
        self.assertIn((ROOM, uid), c.joined)
        # 再来一次:账号注册/设名走缓存不重复,邀请+join 幂等重跑无害
        self.bot._ensure_worker_in_room(ROOM, "copywriter")
        self.assertEqual(c.registered, ["guduu-ai-copywriter"])
        self.assertEqual(len(c.displaynames), 1)

    def test_in_room_cached_after_first_ensure(self) -> None:
        """评审 #7 回归:「已在房」缓存——第二次起零 HTTP;发送前确保在房由 handler 调。"""
        self.bot._ensure_worker_in_room(ROOM, "copywriter")
        self.bot._ensure_worker_in_room(ROOM, "copywriter")
        c = self.bot.client
        self.assertEqual(len(c.invited), 1)  # 邀请/join 只发生一次
        self.assertEqual(len(c.joined), 1)
        # 另一个房间 → 重新确保(缓存按 (room, slug))
        self.bot._ensure_worker_in_room("!other:h", "copywriter")
        self.assertEqual(len(c.joined), 2)

    def test_register_failure_falls_back(self) -> None:
        self.bot.client.register_ok = False
        self.assertEqual(self.bot._ensure_worker_in_room(ROOM, "copywriter"), "")
        # 失败结果被缓存:不会每次都去打注册接口
        self.bot._ensure_worker_in_room(ROOM, "copywriter")
        self.assertEqual(self.bot.client.registered, ["guduu-ai-copywriter"])

    def test_routing_carries_puppet_identity(self) -> None:
        gctx = {"worker_slugs": ["copywriter"], "persona": "", "skill_slugs": [], "model": ""}
        # 文本点名 → 人设切换且带傀儡身份(as_user),回复将以它的名字发
        out = self.bot._apply_worker_routing("copywriter 交个稿", dict(gctx), sender=U)
        self.assertIn("文案", out["persona"])
        self.assertEqual(out["as_user"], "@guduu-ai-copywriter:h")
        # @傀儡 MXID(pill fallback 形态)同样命中
        out2 = self.bot._apply_worker_routing(
            "@guduu-ai-copywriter:h 交个稿", dict(gctx), sender=U
        )
        self.assertEqual(out2["as_user"], "@guduu-ai-copywriter:h")

    def test_mention_hit_by_puppet_id(self) -> None:
        # m.mentions 里 @ 了傀儡 → 触发(最短路径,不依赖正文)
        self.assertTrue(self.bot._agent_mention_hit(
            ROOM, U, "帮忙润色", ["@guduu-ai-copywriter:h"]))
        # 正文含傀儡 MXID → 触发(哪怕该 agent 不在任何绑定集合里,MXID=最明确点名)
        self.assertFalse(self.bot._agent_mention_hit(ROOM, U, "今天天气不错", []))

    def test_worker_slug_of_and_loop_guard(self) -> None:
        # 反解:傀儡 MXID → slug(on_event 用它忽略傀儡自己的消息,防自触发循环)
        self.assertEqual(self.bot._worker_slug_of("@guduu-ai-copywriter:h"), "copywriter")
        self.assertEqual(self.bot._worker_slug_of("@guduu:h"), "")
        self.assertEqual(self.bot._worker_slug_of("@alice:h"), "")


if __name__ == "__main__":
    unittest.main()
