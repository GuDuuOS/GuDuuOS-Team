"""交易系统（模块4 P1）回归测试。

覆盖：套餐解析兜脏数据、下单算价建单、支付成功开/续会员、**幂等**（重复回调不重复续期）、
**续费从原到期日顺延**、会员到期回落免费、手动渠道验签。用假 client + 内存 SQLite，不接真钱。
"""

from __future__ import annotations

import os
import unittest
from typing import Any, Dict, Optional

from cosmac.config import PLANS_EVENT_TYPE
from cosmac.db import init_engine, session_scope
from cosmac.db.order_repo import get_by_order_no
from cosmac.members import MembersStore, active_tier
from cosmac.trading.manual import ManualProvider
from cosmac.trading.plans import parse_plans
from cosmac.trading.service import OrderError, OrderService

CTRL = "!ctrl:guduu.local"
ALICE = "@alice:guduu.local"
DAY = 86400


def setUpModule() -> None:
    # manual 渠道现在 fail-closed：没配密钥就不可用。给测试配一个，才能验签跑通业务链。
    os.environ["COSMAC_PAY_MANUAL_SECRET"] = "test-manual-secret"

PLANS = {"plans": [
    {"slug": "paid-monthly", "name": "付费月卡", "tier": "paid",
     "period_days": 30, "prices": {"usd": 999, "cny": 6800}},
    {"slug": "creator-year", "name": "创作者年卡", "tier": "creator",
     "period_days": 365, "prices": {"usd": 9900}},
]}


class FakeClient:
    """假 client：内存存 (event_type, state_key) → content。"""

    def __init__(self, alias_room: Optional[str] = CTRL):
        self._alias_room = alias_room
        self._state: Dict[Any, Dict[str, Any]] = {}

    def resolve_alias(self, _alias: str) -> Optional[str]:
        return self._alias_room

    def get_state_event(self, _room, event_type, state_key=""):
        return self._state.get((event_type, state_key), self._state.get(event_type))

    def get_room_state(self):
        out = []
        for key, content in self._state.items():
            et, sk = key if isinstance(key, tuple) else (key, "")
            out.append({"type": et, "state_key": sk, "content": content})
        return out

    def set_state_event(self, _room, event_type, content, state_key="") -> bool:
        self._state[(event_type, state_key)] = content
        return True


def _service(client: FakeClient) -> OrderService:
    members = MembersStore(client, "#cosmac-ctrl:guduu.local")
    return OrderService(members, client, "#cosmac-ctrl:guduu.local")


class PlanParseTests(unittest.TestCase):
    def test_parse_valid_and_dirty(self):
        content = {"plans": [
            {"slug": "ok", "name": "OK", "tier": "paid", "period_days": 30,
             "prices": {"usd": 999}},
            {"slug": "free-cant-buy", "tier": "free", "period_days": 30,
             "prices": {"usd": 1}},          # 免费等级不可购买 → 丢
            {"slug": "no-price", "tier": "paid", "period_days": 30, "prices": {}},  # 无价 → 丢
            {"slug": "bad-period", "tier": "paid", "period_days": 0,
             "prices": {"usd": 1}},          # 非正时长 → 丢
            {"slug": "ok", "tier": "creator", "period_days": 1,
             "prices": {"usd": 2}},          # 重复 slug → 丢
        ]}
        plans = parse_plans(content)
        self.assertEqual([p.slug for p in plans], ["ok"])
        self.assertEqual(plans[0].tier, "paid")
        self.assertEqual(plans[0].price_cents("usd"), 999)
        self.assertIsNone(plans[0].price_cents("eur"))

    def test_parse_empty(self):
        self.assertEqual(parse_plans(None), [])
        self.assertEqual(parse_plans({"plans": "x"}), [])


class ManualProviderTests(unittest.TestCase):
    def test_sign_verify(self):
        p = ManualProvider()
        co = p.create_checkout(order_no="o1", amount_cents=999, currency="usd", title="X")
        self.assertEqual(co.kind, "manual")
        # 安全:签名不再出现在 checkout 返回里(防客户端拿到自助白嫖),只能服务端算
        self.assertNotIn("confirm_token", co.extra)
        from cosmac.trading.manual import manual_sign
        token = manual_sign("o1")
        ev = p.parse_callback(headers={}, body=f'{{"order_no":"o1","token":"{token}"}}'.encode())
        self.assertTrue(ev.paid)
        self.assertEqual(ev.order_no, "o1")

    def test_bad_token_rejected(self):
        p = ManualProvider()
        with self.assertRaises(ValueError):
            p.parse_callback(headers={}, body=b'{"order_no":"o1","token":"wrong"}')


class OrderServiceTests(unittest.TestCase):
    def setUp(self):
        init_engine("sqlite://", create_all=True)
        self.client = FakeClient()
        self.client._state[(PLANS_EVENT_TYPE, "")] = PLANS
        self.svc = _service(self.client)

    def test_create_order_prices_and_persists(self):
        out = self.svc.create_order(user_id=ALICE, plan_slug="paid-monthly", currency="usd")
        self.assertEqual(out["amount_cents"], 999)
        self.assertEqual(out["tier"], "paid")
        self.assertEqual(out["checkout"].kind, "manual")
        with session_scope() as s:
            order = get_by_order_no(s, out["order_no"])
            self.assertEqual(order.status, "created")
            self.assertEqual(order.user_id, ALICE)

    def test_create_order_unknown_plan_or_currency(self):
        with self.assertRaises(OrderError):
            self.svc.create_order(user_id=ALICE, plan_slug="nope", currency="usd")
        with self.assertRaises(OrderError):
            self.svc.create_order(user_id=ALICE, plan_slug="creator-year", currency="cny")

    def test_payment_grants_membership_with_expiry(self):
        t0 = 1_700_000_000
        out = self.svc.create_order(user_id=ALICE, plan_slug="paid-monthly", currency="usd")
        res = self.svc.on_payment_success(out["order_no"], now_ts=t0)
        self.assertTrue(res["ok"])
        self.assertEqual(res["tier"], "paid")
        self.assertEqual(res["expires_ts"], t0 + 30 * DAY)
        # 当下生效
        self.assertEqual(active_tier(self.svc._members.get_record(ALICE), t0), "paid")
        # 到期后回落免费
        self.assertEqual(
            active_tier(self.svc._members.get_record(ALICE), t0 + 31 * DAY), "free"
        )

    def test_payment_idempotent(self):
        t0 = 1_700_000_000
        out = self.svc.create_order(user_id=ALICE, plan_slug="paid-monthly", currency="usd")
        r1 = self.svc.on_payment_success(out["order_no"], now_ts=t0)
        r2 = self.svc.on_payment_success(out["order_no"], now_ts=t0 + 5)
        self.assertFalse(r1.get("already"))
        self.assertTrue(r2.get("already"))  # 重复回调幂等
        # 到期日没有被重复续期
        self.assertEqual(
            int(self.svc._members.get_record(ALICE)["expires_ts"]), t0 + 30 * DAY
        )

    def test_underpay_rejected(self):
        # 平台回传的实收金额 < 下单金额 → 拒绝开通（防"少付拿全权益"），且不开会员。
        t0 = 1_700_000_000
        out = self.svc.create_order(user_id=ALICE, plan_slug="paid-monthly", currency="usd")
        with self.assertRaises(OrderError):
            self.svc.on_payment_success(
                out["order_no"], paid_amount_cents=1, paid_currency="usd", now_ts=t0
            )
        self.assertEqual(active_tier(self.svc._members.get_record(ALICE), t0), "free")
        with session_scope() as s:
            self.assertEqual(get_by_order_no(s, out["order_no"]).status, "created")

    def test_wrong_currency_rejected(self):
        t0 = 1_700_000_000
        out = self.svc.create_order(user_id=ALICE, plan_slug="paid-monthly", currency="usd")
        with self.assertRaises(OrderError):
            self.svc.on_payment_success(
                out["order_no"], paid_amount_cents=999, paid_currency="cny", now_ts=t0
            )
        self.assertEqual(active_tier(self.svc._members.get_record(ALICE), t0), "free")

    def test_matching_amount_grants(self):
        # 金额一致 → 正常开通（确认校验没误伤正常单）。
        t0 = 1_700_000_000
        out = self.svc.create_order(user_id=ALICE, plan_slug="paid-monthly", currency="usd")
        res = self.svc.on_payment_success(
            out["order_no"], paid_amount_cents=999, paid_currency="usd", now_ts=t0
        )
        self.assertTrue(res["ok"])
        self.assertEqual(active_tier(self.svc._members.get_record(ALICE), t0), "paid")

    def test_renewal_extends_from_current_expiry(self):
        t0 = 1_700_000_000
        o1 = self.svc.create_order(user_id=ALICE, plan_slug="paid-monthly", currency="usd")
        self.svc.on_payment_success(o1["order_no"], now_ts=t0)  # 到期 t0+30d
        # 还在有效期内(t0+10d)再买一单 → 从原到期日顺延，不是从现在重算
        o2 = self.svc.create_order(user_id=ALICE, plan_slug="paid-monthly", currency="usd")
        res = self.svc.on_payment_success(o2["order_no"], now_ts=t0 + 10 * DAY)
        self.assertEqual(res["expires_ts"], t0 + 60 * DAY)

    def test_create_order_rejects_downgrade_purchase(self):
        # #2 资损修复：创作者会员不允许下单更低档的付费套餐（避免支付后被降级清零）。
        t0 = 1_700_000_000
        self.svc._members.grant(ALICE, "creator", source="admin", now_ts=t0)
        with self.assertRaises(OrderError):
            self.svc.create_order(user_id=ALICE, plan_slug="paid-monthly", currency="usd")
        # 会员没被动过，仍是创作者
        self.assertEqual(active_tier(self.svc._members.get_record(ALICE), t0), "creator")

    def test_payment_does_not_downgrade_on_race(self):
        # #2 防御：下单时是免费(放行)，支付前被管理员升到创作者，支付成功不得降级为 paid。
        t0 = 1_700_000_000
        out = self.svc.create_order(user_id=ALICE, plan_slug="paid-monthly", currency="usd")
        self.svc._members.grant(ALICE, "creator", source="admin", now_ts=t0)  # 竞态升级
        res = self.svc.on_payment_success(out["order_no"], now_ts=t0)
        self.assertTrue(res.get("kept"))
        self.assertEqual(res["tier"], "creator")
        # 仍是创作者（永久），没被降成 paid
        self.assertEqual(
            active_tier(self.svc._members.get_record(ALICE), t0 + 999 * DAY), "creator"
        )

    def test_upgrade_paid_to_creator_allowed(self):
        # 升级（付费→创作者）应放行、正常开通创作者（确认降级保护没误伤升级）。
        t0 = 1_700_000_000
        self.svc._members.grant(ALICE, "paid", source="admin", now_ts=t0)
        out = self.svc.create_order(user_id=ALICE, plan_slug="creator-year", currency="usd")
        res = self.svc.on_payment_success(out["order_no"], now_ts=t0)
        self.assertEqual(res["tier"], "creator")
        self.assertEqual(res["expires_ts"], t0 + 365 * DAY)

    def test_permanent_membership_not_downgraded_by_purchase(self):
        # #1 资损修复：管理员授予的永久同档会员（expires_ts=0）购买一单限期套餐后，
        # 绝不能被改写成"30 天后到期"——保持永久。
        t0 = 1_700_000_000
        self.svc._members.grant(ALICE, "paid", source="admin", now_ts=t0)  # 永久
        out = self.svc.create_order(user_id=ALICE, plan_slug="paid-monthly", currency="usd")
        res = self.svc.on_payment_success(out["order_no"], now_ts=t0)
        self.assertEqual(res["expires_ts"], 0)  # 仍是永久（0=永久）
        # 远期（一年后）依然生效，不会到期回落免费
        self.assertEqual(
            active_tier(self.svc._members.get_record(ALICE), t0 + 999 * DAY), "paid"
        )


if __name__ == "__main__":
    unittest.main()
