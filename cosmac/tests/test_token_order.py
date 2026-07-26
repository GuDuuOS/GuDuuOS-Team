"""Token 充值订单链路（模块4 Token 经济 1c）回归测试。

覆盖：充值包解析兜脏数据、token 下单建单（kind=token）、支付成功充钱包、**幂等**（重复
回调只充一次）、入账失败回滚订单、会员单不受影响。假 client + 内存 SQLite，不接真钱。
"""

from __future__ import annotations

import os
import unittest
from typing import Any, Dict, Optional

from cosmac.config import TOKEN_CONFIG_EVENT_TYPE
from cosmac.db import init_engine, session_scope
from cosmac.db.order_repo import get_by_order_no
from cosmac.members import MembersStore
from cosmac.trading.service import OrderError, OrderService
from cosmac.wallet import WalletStore, parse_token_config

CTRL = "!ctrl:guduu.local"
ALICE = "@alice:guduu.local"


def setUpModule() -> None:
    os.environ["COSMAC_PAY_MANUAL_SECRET"] = "test-manual-secret"


TOKEN_CFG = {
    "enabled": True,
    "markup": 1.0,
    "tokens_per_yuan": 1000,
    "packages": [
        {"slug": "t10", "name": "入门包", "tokens": 10000, "prices": {"cny": 990}},
        {"slug": "t50", "name": "畅用包", "tokens": 60000, "prices": {"cny": 4990, "usd": 799}},
    ],
}


class FakeClient:
    """假 client：内存存 event_type → content（同 test_trading 套路）。"""

    def __init__(self):
        self._state: Dict[Any, Dict[str, Any]] = {TOKEN_CONFIG_EVENT_TYPE: TOKEN_CFG}

    def resolve_alias(self, _alias: str) -> Optional[str]:
        return CTRL

    def get_state_event(self, _room, event_type, state_key=""):
        return self._state.get((event_type, state_key), self._state.get(event_type))

    def set_state_event(self, _room, event_type, content, state_key="") -> bool:
        self._state[(event_type, state_key)] = content
        return True


def _service(client: FakeClient) -> OrderService:
    members = MembersStore(client, "#ctrl:guduu.local")
    wallet = WalletStore(client, "#ctrl:guduu.local", ttl=0)
    return OrderService(members, client, "#ctrl:guduu.local", wallet=wallet)


class PackageParseTests(unittest.TestCase):
    def test_parse_valid_and_dirty(self):
        cfg = parse_token_config({"packages": [
            {"slug": "ok", "name": "OK", "tokens": 1000, "prices": {"cny": 990}},
            {"slug": "no-price", "tokens": 1000, "prices": {}},      # 无价 → 丢
            {"slug": "bad-tokens", "tokens": 0, "prices": {"cny": 1}},  # 非正 token → 丢
            {"slug": "ok", "tokens": 5, "prices": {"cny": 5}},       # 重复 slug → 丢
            {"tokens": 5, "prices": {"cny": 5}},                     # 无 slug → 丢
        ]})
        pkgs = cfg["packages"]
        self.assertEqual(len(pkgs), 1)
        self.assertEqual(pkgs[0]["slug"], "ok")
        self.assertEqual(pkgs[0]["tokens"], 1000)
        self.assertEqual(pkgs[0]["prices"], {"cny": 990})


class TokenOrderTests(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)
        self.client = FakeClient()
        self.svc = _service(self.client)

    def test_create_token_order(self):
        res = self.svc.create_token_order(
            user_id=ALICE, package_slug="t10", currency="cny", provider="manual",
        )
        self.assertEqual(res["tokens"], 10000)
        self.assertEqual(res["amount_cents"], 990)
        with session_scope() as s:
            order = get_by_order_no(s, res["order_no"])
            self.assertEqual(order.kind, "token")
            self.assertEqual(order.tokens, 10000)
            self.assertEqual(order.status, "created")
            self.assertEqual(order.tier, "")

    def test_unknown_package_or_currency(self):
        with self.assertRaises(OrderError):
            self.svc.create_token_order(
                user_id=ALICE, package_slug="nope", currency="cny")
        with self.assertRaises(OrderError):
            self.svc.create_token_order(
                user_id=ALICE, package_slug="t10", currency="usd")  # t10 无 usd 定价

    def test_no_wallet_rejects(self):
        members = MembersStore(self.client, "#ctrl:guduu.local")
        svc = OrderService(members, self.client, "#ctrl:guduu.local")  # 不注入 wallet
        with self.assertRaises(OrderError):
            svc.create_token_order(user_id=ALICE, package_slug="t10", currency="cny")

    def test_payment_success_credits_wallet_idempotent(self):
        res = self.svc.create_token_order(
            user_id=ALICE, package_slug="t10", currency="cny")
        no = res["order_no"]
        out = self.svc.on_payment_success(no, provider_ref="ref1",
                                          paid_amount_cents=990, paid_currency="cny")
        self.assertTrue(out["ok"])
        self.assertEqual(out["tokens"], 10000)
        self.assertEqual(out["balance"], 10000)
        # 钱包真的到账 + 流水记了 recharge
        wallet = self.svc._wallet
        self.assertEqual(wallet.balance(ALICE), 10000)
        rows = wallet.ledger(ALICE)
        self.assertEqual(rows[0]["reason"], "recharge")
        self.assertEqual(rows[0]["ref"], no)
        # 幂等：重复回调不重复充值
        out2 = self.svc.on_payment_success(no)
        self.assertTrue(out2.get("already"))
        self.assertEqual(wallet.balance(ALICE), 10000)
        with session_scope() as s:
            self.assertEqual(get_by_order_no(s, no).status, "paid")

    def test_amount_mismatch_rejected(self):
        res = self.svc.create_token_order(
            user_id=ALICE, package_slug="t10", currency="cny")
        with self.assertRaises(OrderError):
            self.svc.on_payment_success(
                res["order_no"], paid_amount_cents=1, paid_currency="cny")
        # 未开通：订单还在 created，钱包没到账
        with session_scope() as s:
            self.assertEqual(get_by_order_no(s, res["order_no"]).status, "created")
        self.assertEqual(self.svc._wallet.balance(ALICE), 0)

    def test_credit_failure_reverts_order(self):
        res = self.svc.create_token_order(
            user_id=ALICE, package_slug="t10", currency="cny")

        # 模拟入账挂掉（DB 抖动）：充值抛异常 → 订单必须回滚 created 待平台重试
        orig = self.svc._wallet.recharge
        self.svc._wallet.recharge = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down"))
        try:
            with self.assertRaises(OrderError):
                self.svc.on_payment_success(res["order_no"])
        finally:
            self.svc._wallet.recharge = orig
        with session_scope() as s:
            self.assertEqual(get_by_order_no(s, res["order_no"]).status, "created")
        # 平台重试后成功
        out = self.svc.on_payment_success(res["order_no"])
        self.assertTrue(out["ok"])
        self.assertEqual(self.svc._wallet.balance(ALICE), 10000)


if __name__ == "__main__":
    unittest.main()
