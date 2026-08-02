"""模块4：支付端点的**端到端 HTTP 集成测试**。

不接真支付——起真实的 bot HTTP server(`_BoundedThreadingHTTPServer` + `_make_handler`)，用
``requests`` 打它，验证整条 HTTP 路径都对：路由 / CORS 预检 / Authorization 头解析 / body
解析 / 回调分发。证明 mock(manual)通道能端到端跑通。
"""

from __future__ import annotations

import json
import threading
import unittest
from functools import partial

import requests

from cosmac.bots.appservice_bot import _BoundedThreadingHTTPServer, _make_handler


class _FakeBot:
    """只实现支付端点要用到的几个方法，模拟 CosmacBot。"""

    def __init__(self) -> None:
        self.granted = None

    def handle_pay_plans(self):
        return [{"slug": "t", "name": "测试", "tier": "paid",
                 "period_days": 30, "prices": {"usd": 999}}]

    def handle_pay_me(self, token):
        if not token.startswith("@"):
            return 401, {"error": "no"}
        return 200, {"tier": "paid", "tier_label": "付费会员", "expires_ts": 0}

    def handle_pay_checkout(self, token, body):
        if not token.startswith("@"):
            return 401, {"error": "登录已失效"}
        return 200, {
            "order_no": "o1", "amount_cents": 999, "currency": "usd",
            "tier": "paid", "period_days": 30,
            "checkout": {"kind": "manual", "url": "", "address": "",
                         "extra": {"confirm_token": "tok"}},
        }

    def handle_pay_callback(self, provider, headers, body):
        self.granted = (provider, json.loads(body))
        return 200

    def handle_wallet_me(self, token):
        """模拟用户钱包总览，供缓存响应头集成测试。"""
        if not token.startswith("@"):
            return 401, {"error": "no"}
        return 200, {
            "enabled": True,
            "balance": 200,
            "free_daily": {"total": 0, "used": 0, "remaining": 0},
            "tokens_per_yuan": 1000,
            "exempt": False,
            "packages": [],
        }

    def handle_wallet_ledger(self, token, limit=50, offset=0):
        """模拟用户钱包流水，验证固定 GET URL 不允许浏览器缓存。"""
        if not token.startswith("@"):
            return 401, {"error": "no"}
        return 200, {"items": [{"id": 1, "delta": 200}]}


class PayHttpTests(unittest.TestCase):
    def setUp(self):
        self.bot = _FakeBot()
        handler = partial(_make_handler, bot=self.bot, hs_token="hs")
        self.srv = _BoundedThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.srv.server_address[1]
        self.t = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.t.start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def _u(self, p):
        return f"http://127.0.0.1:{self.port}{p}"

    def test_plans_public_with_cors(self):
        r = requests.get(self._u("/cosmac/pay/plans"), timeout=5)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get("Access-Control-Allow-Origin"), "*")
        self.assertEqual(r.json()["plans"][0]["slug"], "t")

    def test_options_preflight(self):
        r = requests.options(self._u("/cosmac/pay/checkout"), timeout=5)
        self.assertEqual(r.status_code, 204)
        self.assertIn("authorization",
                      r.headers.get("Access-Control-Allow-Headers", "").lower())

    def test_checkout_requires_valid_token(self):
        ok = requests.post(self._u("/cosmac/pay/checkout"),
                           json={"plan_slug": "t", "currency": "usd"},
                           headers={"Authorization": "Bearer @a:h"}, timeout=5)
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["order_no"], "o1")
        # 无 token → 401
        no = requests.post(self._u("/cosmac/pay/checkout"),
                           json={"plan_slug": "t", "currency": "usd"}, timeout=5)
        self.assertEqual(no.status_code, 401)

    def test_me_endpoint(self):
        r = requests.get(self._u("/cosmac/pay/me"),
                         headers={"Authorization": "Bearer @a:h"}, timeout=5)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["tier"], "paid")

    def test_wallet_gets_are_never_cached(self):
        """余额与流水跨浏览器变化，响应必须明确 no-store。"""
        headers = {"Authorization": "Bearer @a:h"}
        balance = requests.get(
            self._u("/cosmac/wallet/me"), headers=headers, timeout=5
        )
        ledger = requests.get(
            self._u("/cosmac/wallet/ledger"), headers=headers, timeout=5
        )
        self.assertEqual(balance.status_code, 200)
        self.assertEqual(balance.json()["balance"], 200)
        self.assertEqual(balance.headers.get("Cache-Control"), "no-store")
        self.assertEqual(ledger.status_code, 200)
        self.assertEqual(ledger.json()["items"][0]["delta"], 200)
        self.assertEqual(ledger.headers.get("Cache-Control"), "no-store")

    def test_manual_callback_dispatches(self):
        r = requests.post(self._u("/cosmac/pay/callback/manual"),
                          json={"order_no": "o1", "token": "tok"}, timeout=5)
        self.assertEqual(r.status_code, 200)
        # manual 回调是浏览器调的 → 响应必须带 CORS，否则前端 Failed to fetch
        self.assertEqual(r.headers.get("Access-Control-Allow-Origin"), "*")
        self.assertEqual(self.bot.granted[0], "manual")
        self.assertEqual(self.bot.granted[1]["order_no"], "o1")


if __name__ == "__main__":
    unittest.main()
