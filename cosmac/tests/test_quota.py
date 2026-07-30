"""用量配额（变现第二步）单元测试：repo / QuotaStore / bot 强制。零 key、内存 SQLite。"""

from __future__ import annotations

import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from cosmac.db import init_engine, session_scope
from cosmac.db.quota_repo import consume_if_below, get_count, incr, period_key
from cosmac.quotas import QuotaStore, parse_quota_limits


class TestQuotaRepo(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)

    def test_incr_and_get(self) -> None:
        with session_scope() as s:
            self.assertEqual(get_count(s, "@a:h", "ai_msg_daily", "2026-06-26"), 0)
            self.assertEqual(incr(s, "@a:h", "ai_msg_daily", "2026-06-26"), 1)
            self.assertEqual(incr(s, "@a:h", "ai_msg_daily", "2026-06-26"), 2)
        with session_scope() as s:
            self.assertEqual(get_count(s, "@a:h", "ai_msg_daily", "2026-06-26"), 2)
            # 不同周期键互不影响
            self.assertEqual(get_count(s, "@a:h", "ai_msg_daily", "2026-06-27"), 0)

    def test_period_key(self) -> None:
        self.assertEqual(len(period_key("day")), 10)   # YYYY-MM-DD
        self.assertEqual(len(period_key("month")), 7)  # YYYY-MM
        self.assertEqual(period_key("total"), "")

    def test_concurrent_last_quota_only_one_consumer_wins(self) -> None:
        """两个线程同时争最后一次额度时，只允许一个成功，数据库计数不能写穿上限。"""
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        try:
            init_engine("sqlite:///" + tmp.name, create_all=True)
            ready = threading.Barrier(2)

            def consume() -> object:
                """在独立事务里同时消费，模拟两个跨房间 AI 回复线程。"""
                ready.wait(timeout=3)
                with session_scope() as s:
                    return consume_if_below(
                        s, "@race:h", "ai_msg_daily", "2026-07-31", 1,
                    )

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: consume(), range(2)))

            self.assertEqual(sum(value is not None for value in results), 1)
            with session_scope() as s:
                self.assertEqual(
                    get_count(s, "@race:h", "ai_msg_daily", "2026-07-31"),
                    1,
                )
        finally:
            os.unlink(tmp.name)


class TestQuotaStore(unittest.TestCase):
    def test_defaults_and_override(self) -> None:
        # 默认：免费 AI 对话 30/天，知识库 5 篇
        limits = parse_quota_limits(None)
        self.assertEqual(limits["ai_msg_daily"]["free"], 30)
        self.assertEqual(limits["ai_msg_daily"]["paid"], -1)
        self.assertEqual(limits["kb_docs"]["free"], 5)
        # admin 覆盖
        ev = {"limits": {"ai_msg_daily": {"free": 5}}}
        limits2 = parse_quota_limits(ev)
        self.assertEqual(limits2["ai_msg_daily"]["free"], 5)
        self.assertEqual(limits2["ai_msg_daily"]["paid"], -1)  # 没覆盖的回退默认

    def test_store_reads_control_room(self) -> None:
        class C:
            def resolve_alias(self, a):
                return "!ctrl:h"

            def get_state_event(self, room, etype, key=""):
                return {"limits": {"ai_msg_daily": {"free": 3}}}

        st = QuotaStore(C(), "#ctrl:h")
        self.assertEqual(st.limit("ai_msg_daily", "free"), 3)
        self.assertEqual(st.limit("kb_docs", "free"), 5)  # 默认


def _bot():
    from cosmac.bots.appservice_bot import CosmacBot
    from cosmac.config import CosmacConfig

    bot = CosmacBot(CosmacConfig(llm_provider="echo"))
    bot._is_platform_admin = lambda u: False  # type: ignore  # 默认非管理员
    return bot


class TestBotQuotaEnforce(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)

    def test_rate_quota_blocks_after_limit(self) -> None:
        bot = _bot()
        bot.members.get_tier = lambda u: "free"  # type: ignore
        # 配额配成免费 2 条/天
        bot.quotas.limit = lambda metric, tier: 2 if metric == "ai_msg_daily" else -1  # type: ignore
        self.assertIsNone(bot._rate_quota_blocked("@u:h", "ai_msg_daily"))  # 1
        self.assertIsNone(bot._rate_quota_blocked("@u:h", "ai_msg_daily"))  # 2
        blocked = bot._rate_quota_blocked("@u:h", "ai_msg_daily")           # 第3次超额
        self.assertIsNotNone(blocked)
        self.assertIn("额度已用完", blocked)
        self.assertIn("2/2", blocked)

    def test_admin_unlimited(self) -> None:
        bot = _bot()
        bot._is_platform_admin = lambda u: True  # type: ignore
        self.assertEqual(bot._quota_limit("@admin:h", "ai_msg_daily"), -1)
        for _ in range(50):
            self.assertIsNone(bot._rate_quota_blocked("@admin:h", "ai_msg_daily"))

    def test_paid_unlimited_not_counted(self) -> None:
        bot = _bot()
        bot.members.get_tier = lambda u: "paid"  # type: ignore
        bot.quotas.limit = lambda metric, tier: (30 if tier == "free" else -1)  # type: ignore
        for _ in range(50):
            self.assertIsNone(bot._rate_quota_blocked("@p:h", "ai_msg_daily"))

    def test_tool_quota_teams(self) -> None:
        # assemble_team 工具 → teams 配额：免费 1 个。新契约：check **只查不扣**（失败/纯查询
        # 不消耗额度），工具做成事后调 consume 才计数——之后第 2 次 check 才被拦。
        bot = _bot()
        bot.members.get_tier = lambda u: "free"  # type: ignore
        bot.quotas.limit = lambda m, t: 1 if m == "teams" else -1  # type: ignore
        self.assertIsNone(bot._tool_quota_check("@u:h", "assemble_team"))   # 查：未用 → 放行
        self.assertIsNone(bot._tool_quota_check("@u:h", "assemble_team"))   # 只查不扣：仍放行
        bot._tool_quota_consume("@u:h", "assemble_team")                    # 专班真建成 → 扣 1
        over = bot._tool_quota_check("@u:h", "assemble_team")               # 1/1 → 拦
        self.assertIsNotNone(over)
        self.assertIn("专班/频道数", over)  # 文案:teams 覆盖建群(create_room)后改名
        # 不在配额表里的工具不计量（check/consume 都无操作）
        self.assertIsNone(bot._tool_quota_check("@u:h", "send_message_to_room"))
        bot._tool_quota_consume("@u:h", "send_message_to_room")  # 应无操作不报错

    def test_usage_mine(self) -> None:
        bot = _bot()
        bot.members.get_tier = lambda u: "free"  # type: ignore
        bot.quotas.limit = lambda m, t: {"ai_msg_daily": 30, "kb_docs": 5, "teams": 1, "workflow_runs": 0}.get(m, -1)  # type: ignore
        bot.client.whoami = lambda t: "@u:h" if t == "good" else None  # type: ignore
        self.assertEqual(bot.handle_usage_mine("")[0], 401)
        code, p = bot.handle_usage_mine("good")
        self.assertEqual(code, 200)
        keys = {u["key"]: u for u in p["usage"]}
        self.assertEqual(keys["ai_msg_daily"]["limit"], 30)
        self.assertEqual(keys["kb_docs"]["used"], 0)
        self.assertEqual(keys["teams"]["limit"], 1)


if __name__ == "__main__":
    unittest.main()
