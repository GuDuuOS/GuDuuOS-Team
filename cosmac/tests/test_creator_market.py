"""创作者商城（模块4 Token 经济 P2）回归测试。

覆盖：listing repo 上架/下架/banned 保护、charge_agent_use 分账（90/10、抽成向上取整、
余额不足不扣、自用不扣、平台用量开关关闭仍按创作者标价扣）、收益账本汇总/明细、
下架后不再计费。
零 key、内存 SQLite、假控制室。
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, Optional

from cosmac.config import TOKEN_CONFIG_EVENT_TYPE
from cosmac.db import init_engine, listing_repo, session_scope, wallet_repo
from cosmac.db.market_repo import add_acquired
from cosmac.db.models import SCOPE_USER
from cosmac.db.repo import upsert_agent
from cosmac.wallet import WalletStore

CREATOR = "@carol:guduu.local"
BUYER = "@bob:guduu.local"


class _FakeClient:
    def __init__(self, ev: Optional[Dict[str, Any]] = None):
        self._ev = ev or {"enabled": True, "platform_fee_pct": 10}

    def resolve_alias(self, a):
        return "!ctrl:h"

    def get_state_event(self, room, etype, key=""):
        return self._ev if etype == TOKEN_CONFIG_EVENT_TYPE else None


def _store(**cfg) -> WalletStore:
    base = {"enabled": True, "platform_fee_pct": 10}
    base.update(cfg)
    return WalletStore(_FakeClient(base), "#ctrl:h", ttl=0)


def _mk_listing(price: int = 300, *, approve: bool = True) -> int:
    """建一个创作者 Agent + 上架（默认顺手审核通过=在售），返回 listing id。

    P3 起 upsert 一律进 pending 待审，须 review_listing 通过才在售——测试默认帮审。
    """
    with session_scope() as s:
        upsert_agent(
            s, SCOPE_USER, CREATOR, "wenan",
            name="文案高手", description="写文案", system_prompt="你是文案高手",
        )
        row = listing_repo.upsert_listing(
            s, creator=CREATOR, agent_slug="wenan",
            name="文案高手", description="写爆款文案", price_tokens=price,
        )
        lid = row.id
        if approve:
            listing_repo.review_listing(s, lid, approve=True)
        return lid


class ListingRepoTests(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)

    def test_upsert_and_update(self) -> None:
        lid = _mk_listing(300)
        with session_scope() as s:
            row = listing_repo.get_listing(s, lid)
            self.assertEqual(row.price_tokens, 300)
            self.assertEqual(row.status, "on")   # _mk_listing 已帮审核通过
            # 重复上架=更新价格，且**任何更新都重审**（P3）：在售的立即回待审
            row2 = listing_repo.upsert_listing(
                s, creator=CREATOR, agent_slug="wenan",
                name="文案高手", description="d", price_tokens=500,
            )
            self.assertEqual(row2.id, lid)
            self.assertEqual(row2.price_tokens, 500)
            self.assertEqual(row2.status, "pending")

    def test_pending_needs_review_and_creator_cannot_self_on(self) -> None:
        lid = _mk_listing(300, approve=False)   # 不帮审：停在 pending
        with session_scope() as s:
            self.assertEqual(listing_repo.get_listing(s, lid).status, "pending")
            # 创作者不能自己置 on（上架必经审核）
            self.assertFalse(listing_repo.set_status(s, lid, "on", creator=CREATOR))
            # 管理员审核拒绝 → rejected + 原因
            row = listing_repo.review_listing(s, lid, approve=False, reason="文案夸大")
            self.assertEqual(row.status, "rejected")
            self.assertEqual(row.review_reason, "文案夸大")
            # 重提（upsert）→ 回 pending、原因清空 → 再审通过 → 在售
            listing_repo.upsert_listing(
                s, creator=CREATOR, agent_slug="wenan",
                name="文案高手", description="改好了", price_tokens=300,
            )
            self.assertEqual(listing_repo.get_listing(s, lid).status, "pending")
            self.assertEqual(listing_repo.get_listing(s, lid).review_reason, "")
            listing_repo.review_listing(s, lid, approve=True)
            self.assertEqual(listing_repo.get_listing(s, lid).status, "on")

    def test_pending_listing_not_charged(self) -> None:
        # 待审中的 listing 不可计费（charge 视为不在售）
        lid = _mk_listing(300, approve=False)
        st = _store()
        with session_scope() as s:
            wallet_repo.credit(s, BUYER, 1000, reason="grant")
        self.assertEqual(st.charge_agent_use(BUYER, lid)["charged"], 0)

    def test_creator_cannot_touch_banned(self) -> None:
        lid = _mk_listing()
        with session_scope() as s:
            self.assertTrue(listing_repo.set_status(s, lid, "banned"))  # 管理员封
            # 创作者不能改 banned 条目、也不能经 upsert 复活
            self.assertFalse(listing_repo.set_status(s, lid, "on", creator=CREATOR))
            self.assertIsNone(listing_repo.upsert_listing(
                s, creator=CREATOR, agent_slug="wenan",
                name="x", description="y", price_tokens=1,
            ))
            # 管理员可恢复
            self.assertTrue(listing_repo.set_status(s, lid, "on"))

    def test_creator_off_on_own_only(self) -> None:
        lid = _mk_listing()
        with session_scope() as s:
            self.assertTrue(listing_repo.set_status(s, lid, "off", creator=CREATOR))
            self.assertFalse(listing_repo.set_status(s, lid, "off", creator="@evil:h"))
            self.assertFalse(listing_repo.set_status(s, lid, "banned", creator=CREATOR))


class ChargeAgentUseTests(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)
        self.st = _store()

    def _fund(self, user: str, amount: int) -> None:
        with session_scope() as s:
            wallet_repo.credit(s, user, amount, reason="grant")

    def test_split_90_10(self) -> None:
        lid = _mk_listing(300)
        self._fund(BUYER, 1000)
        r = self.st.charge_agent_use(BUYER, lid, room_id="!r:h")
        self.assertEqual(r["charged"], 300)
        self.assertEqual(r["fee"], 30)     # 10% 抽成
        self.assertEqual(r["net"], 270)    # 创作者 90%
        self.assertEqual(r["balance"], 700)
        # 创作者钱包到账 + 收益账本 + listing 累计
        self.assertEqual(self.st.balance(CREATOR), 270)
        with session_scope() as s:
            summary = listing_repo.earnings_summary(s, CREATOR)
            self.assertEqual(summary, {"total_net": 270, "total_gross": 300, "count": 1})
            li = listing_repo.get_listing(s, lid)
            self.assertEqual(li.uses, 1)
            self.assertEqual(li.earned, 270)
        # 双方流水
        self.assertEqual(self.st.ledger(BUYER)[0]["reason"], "agent_use")
        self.assertEqual(self.st.ledger(CREATOR)[0]["reason"], "earning")

    def test_fee_ceil_protects_platform(self) -> None:
        lid = _mk_listing(15)   # 10% = 1.5 → 抽 2、创作者 13
        self._fund(BUYER, 100)
        r = self.st.charge_agent_use(BUYER, lid)
        self.assertEqual(r["fee"], 2)
        self.assertEqual(r["net"], 13)

    def test_insufficient_balance_no_charge(self) -> None:
        lid = _mk_listing(300)
        self._fund(BUYER, 100)  # 不够 300
        r = self.st.charge_agent_use(BUYER, lid)
        self.assertEqual(r["charged"], 0)
        self.assertEqual(self.st.balance(BUYER), 100)   # 没扣
        self.assertEqual(self.st.balance(CREATOR), 0)   # 没分成
        # 前拦提示
        msg = self.st.agent_use_precheck(BUYER, 300)
        self.assertIsNotNone(msg)
        self.assertIn("余额不足", msg)

    def test_self_use_free(self) -> None:
        lid = _mk_listing(300)
        self._fund(CREATOR, 1000)
        r = self.st.charge_agent_use(CREATOR, lid)
        self.assertEqual(r["charged"], 0)
        self.assertEqual(self.st.balance(CREATOR), 1000)

    def test_platform_usage_switch_does_not_make_listing_free(self) -> None:
        lid = _mk_listing(300)
        self._fund(BUYER, 1000)
        # enabled 只控制平台内置 AI 的真实用量计费；创作者审核价不能跟着变成免费。
        st_off = _store(enabled=False)
        self.assertIsNone(st_off.agent_use_precheck(BUYER, 300))
        self.assertEqual(st_off.charge_agent_use(BUYER, lid)["charged"], 300)
        self.assertEqual(st_off.balance(BUYER), 700)

    def test_off_listing_is_free(self) -> None:
        lid = _mk_listing(300)
        self._fund(BUYER, 1000)
        # 下架：不扣
        with session_scope() as s:
            listing_repo.set_status(s, lid, "off", creator=CREATOR)
        self.assertEqual(self.st.charge_agent_use(BUYER, lid)["charged"], 0)

    def test_free_price_listing(self) -> None:
        lid = _mk_listing(0)   # 免费用
        self._fund(BUYER, 100)
        self.assertIsNone(self.st.agent_use_precheck(BUYER, 0))
        r = self.st.charge_agent_use(BUYER, lid)
        self.assertEqual(r["charged"], 0)
        self.assertEqual(self.st.balance(BUYER), 100)

    def test_earnings_list_pagination(self) -> None:
        lid = _mk_listing(10)
        self._fund(BUYER, 100)
        for _ in range(3):
            self.st.charge_agent_use(BUYER, lid)
        with session_scope() as s:
            rows = listing_repo.list_earnings(s, CREATOR, limit=2)
            self.assertEqual(len(rows), 2)
            self.assertEqual(listing_repo.earnings_summary(s, CREATOR)["count"], 3)


class _ReplyClient(_FakeClient):
    """记录创作者 Agent 回复的最小 Matrix 客户端，避免端到端测试访问真实 Synapse。"""

    def __init__(self) -> None:
        super().__init__()
        self.sent = []
        self.typing = []

    def send_text(self, room_id, text, txn_id=None):
        """记录消息并模拟 Synapse 成功返回事件 ID。"""
        self.sent.append((room_id, text))
        return "$sent"

    def set_typing(self, room_id, typing, timeout_ms=30000):
        """记录输入状态，满足回复主链的 MatrixClient 契约。"""
        self.typing.append((room_id, typing))


class CreatorAgentReplyBillingTests(unittest.TestCase):
    """覆盖“商城获取 → @创作者 Agent → 回复成功 → 买家扣费/创作者分成”完整主链。"""

    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)

    def _bot(self, listing_id: int):
        """构建只保留路由与结算真实逻辑的 Bot；其余网络/LLM 环节全部本地打桩。"""
        from cosmac.bots.appservice_bot import CosmacBot
        from cosmac.config import CosmacConfig

        bot = CosmacBot(CosmacConfig(llm_provider="echo", server_name="guduu.local"))
        bot.client = _ReplyClient()
        # 故意关闭平台 AI 用量计费并把买家标成管理员：这是此前两个免费旁路的组合。
        bot.wallet = _store(enabled=False)
        bot._is_platform_admin = lambda user_id: True  # type: ignore
        bot._rate_quota_blocked = lambda *args, **kwargs: None  # type: ignore
        bot._wallet_precheck_blocked = lambda user_id: None  # type: ignore
        bot._apply_runtime_config = lambda: None  # type: ignore
        bot._group_context = lambda room_id: {  # type: ignore
            "worker_slugs": [], "persona": "", "skill_slugs": [], "model": "",
            "task_rule": "", "workflow_slugs": [], "kb_scopes": [],
            "channel_rules": "", "rule_doc": "",
        }
        bot._skill_addendum = lambda *args, **kwargs: ""  # type: ignore
        bot._recent_history = lambda *args, **kwargs: []  # type: ignore
        bot._run_agent_engine = lambda *args, **kwargs: ("已完成", 12)  # type: ignore
        bot._maybe_name_ai_session = lambda *args, **kwargs: None  # type: ignore
        bot._maybe_update_memory = lambda *args, **kwargs: None  # type: ignore
        with session_scope() as s:
            add_acquired(s, user_id=BUYER, kind="cagent", slug=str(listing_id))
        return bot

    def test_admin_still_pays_creator_price_when_platform_usage_is_off(self) -> None:
        """管理员豁免只适用于平台 AI；关闭平台用量计费也不能把创作者商品变免费。"""
        listing_id = _mk_listing(35)
        with session_scope() as s:
            wallet_repo.credit(s, BUYER, 100, reason="grant")
        bot = self._bot(listing_id)

        bot._reply_to_message(
            "!room:guduu.local", BUYER, "@文案高手 写一句", "写一句", {}, True,
            "$creator-use", [],
        )

        self.assertEqual(bot.wallet.balance(BUYER), 65)
        self.assertEqual(bot.wallet.balance(CREATOR), 31)  # 35 - ceil(10%) = 31
        self.assertEqual(bot.wallet.ledger(BUYER)[0]["reason"], "agent_use")
        self.assertEqual(bot.client.sent, [("!room:guduu.local", "已完成")])

    def test_billing_failure_blocks_before_llm(self) -> None:
        """付费商品计费层异常必须停止调用，不能 fail-open 送出一条免费回复。"""
        listing_id = _mk_listing(35)
        with session_scope() as s:
            wallet_repo.credit(s, BUYER, 100, reason="grant")
        bot = self._bot(listing_id)
        bot.wallet.agent_use_precheck = (  # type: ignore
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("wallet down"))
        )
        called = []
        bot._run_agent_engine = lambda *args, **kwargs: called.append(True)  # type: ignore

        bot._reply_to_message(
            "!room:guduu.local", BUYER, "@文案高手 写一句", "写一句", {}, True,
            "$creator-fail", [],
        )

        self.assertEqual(called, [])
        self.assertIn("计费服务暂时不可用", bot.client.sent[0][1])
        self.assertEqual(bot.wallet.balance(BUYER), 100)


def _mk_skill_listing(price: int = 500, *, approve: bool = True) -> int:
    """建一个创作者 Skill + 上架（默认审核通过=在售），返回 listing id。"""
    from cosmac.db.repo import upsert_skill

    with session_scope() as s:
        upsert_skill(
            s, SCOPE_USER, CREATOR, "recap",
            name="每日复盘法", description="结构化复盘", instructions="按 STAR 复盘…",
        )
        row = listing_repo.upsert_listing(
            s, creator=CREATOR, agent_slug="recap", kind="skill",
            name="每日复盘法", description="买断即永久用", price_tokens=price,
        )
        lid = row.id
        if approve:
            listing_repo.review_listing(s, lid, approve=True)
        return lid


class SkillBuyoutTests(unittest.TestCase):
    """Skill 一次性买断（P4 定稿口径）。"""

    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)
        self.st = _store()

    def _fund(self, user: str, amount: int) -> None:
        with session_scope() as s:
            wallet_repo.credit(s, user, amount, reason="grant")

    def test_buyout_splits_and_is_once_only(self) -> None:
        lid = _mk_skill_listing(500)
        self._fund(BUYER, 1000)
        r = self.st.charge_skill_purchase(BUYER, lid)
        self.assertTrue(r["ok"])
        self.assertEqual(r["charged"], 500)
        self.assertEqual(r["fee"], 50)     # 10%
        self.assertEqual(r["net"], 450)
        self.assertEqual(self.st.balance(BUYER), 500)
        self.assertEqual(self.st.balance(CREATOR), 450)
        # 再次购买（移除后重新获取）→ 已买断，不再扣钱
        r2 = self.st.charge_skill_purchase(BUYER, lid)
        self.assertTrue(r2["ok"])
        self.assertEqual(r2["charged"], 0)
        self.assertEqual(self.st.balance(BUYER), 500)

    def test_insufficient_balance_fails_hard(self) -> None:
        """买断是先付后得：扣不动必须失败（与 Agent 后付"扣到 0 为止"不同）。"""
        lid = _mk_skill_listing(500)
        self._fund(BUYER, 100)
        r = self.st.charge_skill_purchase(BUYER, lid)
        self.assertFalse(r["ok"])
        self.assertIn("余额不足", r["error"])
        self.assertEqual(self.st.balance(BUYER), 100)   # 分文未扣
        self.assertEqual(self.st.balance(CREATOR), 0)

    def test_free_and_self_and_offsale(self) -> None:
        # 免费技能：放行不扣
        lid_free = _mk_skill_listing(0)
        self.assertTrue(self.st.charge_skill_purchase(BUYER, lid_free)["ok"])
        self.assertEqual(self.st.balance(BUYER), 0)
        # 自己的：不扣
        lid = _mk_skill_listing(500)
        self._fund(CREATOR, 1000)
        self.assertEqual(self.st.charge_skill_purchase(CREATOR, lid)["charged"], 0)
        # 下架的：明确失败（不能买到下架货）
        with session_scope() as s:
            listing_repo.set_status(s, lid, "off", creator=CREATOR)
        r = self.st.charge_skill_purchase(BUYER, lid)
        self.assertFalse(r["ok"])

    def test_pending_skill_not_purchasable(self) -> None:
        lid = _mk_skill_listing(500, approve=False)   # 待审
        self._fund(BUYER, 1000)
        r = self.st.charge_skill_purchase(BUYER, lid)
        self.assertFalse(r["ok"])
        self.assertEqual(self.st.balance(BUYER), 1000)

    def test_platform_usage_switch_does_not_cancel_skill_price(self) -> None:
        lid = _mk_skill_listing(500)
        self._fund(BUYER, 1000)
        st_off = _store(enabled=False)
        r = st_off.charge_skill_purchase(BUYER, lid)
        self.assertTrue(r["ok"])
        self.assertEqual(r["charged"], 500)
        self.assertEqual(st_off.balance(BUYER), 500)

    def test_slug_collision_rejected(self) -> None:
        """同一创作者用同一 slug 上架另一类资源 → 显式拒绝（唯一键不含 kind）。"""
        from cosmac.db.repo import upsert_skill

        _mk_listing(300)   # agent slug=wenan
        with session_scope() as s:
            upsert_skill(s, SCOPE_USER, CREATOR, "wenan",
                         name="同名技能", description="d", instructions="i")
            with self.assertRaises(listing_repo.SlugTaken):
                listing_repo.upsert_listing(
                    s, creator=CREATOR, agent_slug="wenan", kind="skill",
                    name="同名技能", description="d", price_tokens=100,
                )


if __name__ == "__main__":
    unittest.main()
