"""Nexus 支付层回归测试（定价/订单/mock 履约/幂等/明文销毁）。

跑法（项目根）： .venv/bin/python -m unittest nexus.tests.test_pay -v
临时 SQLite,不碰真库;mock 渠道经 env 开关打开,不涉网络。
"""

from __future__ import annotations

import os
import tempfile
import unittest

from nexus import db, fleet, oem, pay
from nexus.fleet import FleetError


class PayTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        db.init_engine("sqlite:///" + self._tmp.name)
        self.s = db.session()
        os.environ["NEXUS_PAY_MOCK"] = "1"  # 打开模拟渠道
        self.buyer = oem.register(self.s, "buyer@x.com", "abc12345", inviter="GUDUU", company="测试公司", contact_name="张三", phone="13800000000")["id"]

    def tearDown(self):
        os.environ.pop("NEXUS_PAY_MOCK", None)
        self.s.close()
        os.unlink(self._tmp.name)

    # ---- 定价 ----

    def test_pricing_default_and_set(self):
        p = pay.get_pricing(self.s)
        self.assertEqual(p["key_price_cents"], 0)  # 默认未定价
        out = pay.set_pricing(
            self.s,
            {"key_price_cents": 1990000, "topup_packs": [{"cents": 9900, "tokens": 50_000_000}]},
        )
        self.assertEqual(out["key_price_cents"], 1990000)
        self.assertEqual(pay.get_pricing(self.s)["topup_packs"][0]["tokens"], 50_000_000)
        with self.assertRaises(FleetError):
            pay.set_pricing(self.s, {"key_price_cents": -1})
        with self.assertRaises(FleetError):
            pay.set_pricing(self.s, {"topup_packs": [{"cents": 0, "tokens": 1}]})

    # ---- 渠道可用性 ----

    def test_channels(self):
        ch = pay.channels()
        self.assertTrue(ch["mock"])       # env 已开
        self.assertFalse(ch["alipay"])    # 凭据未配 → 占位不可用
        self.assertFalse(ch["wechat"])

    # ---- KEY 购买全链路 ----

    def test_buy_key_flow(self):
        # 未定价时不可买
        with self.assertRaises(FleetError):
            pay.create_order(self.s, self.buyer, "key", "mock")
        pay.set_pricing(self.s, {"key_price_cents": 1990000, "key_token_grant": 7777})
        out = pay.create_order(self.s, self.buyer, "key", "mock")
        self.assertEqual(out["order"]["status"], "pending")
        self.assertEqual(out["pay"]["type"], "mock")
        no = out["order"]["order_no"]
        # 支付成功 → 出码 + 自动归属
        paid = pay.mark_paid(self.s, no, "TXN1")
        self.assertEqual(paid["status"], "paid")
        self.assertTrue(paid["key"].startswith("CMK-"))
        self.assertEqual(oem.my_keys(self.s, self.buyer)[0]["token_grant"], 7777)
        # 幂等：渠道重复回调不重复发码
        again = pay.mark_paid(self.s, no, "TXN1-dup")
        self.assertEqual(again["key_id"], paid["key_id"])
        self.assertEqual(len(oem.my_keys(self.s, self.buyer)), 1)
        # 买家订单列表可见明文；超管列表不含
        self.assertEqual(pay.my_orders(self.s, self.buyer)[0]["key"], paid["key"])
        self.assertNotIn("key", pay.list_orders(self.s)[0])
        # 装机兑换 → 订单明文销毁
        fleet.redeem(self.s, paid["key"], "buyer-site.com")
        oem.clear_plain_by_key(self.s, paid["key"])
        self.assertIsNone(pay.my_orders(self.s, self.buyer)[0]["key"])

    # ---- token 充值全链路 ----

    def test_topup_flow(self):
        pay.set_pricing(self.s, {
            "key_price_cents": 100, "key_token_grant": 1000,
            "topup_packs": [{"cents": 9900, "tokens": 50_000_000}],
        })
        # 先买一把 KEY 并装机,得到可充值的实例
        k = pay.mark_paid(
            self.s, pay.create_order(self.s, self.buyer, "key", "mock")["order"]["order_no"]
        )
        inst = fleet.redeem(self.s, k["key"], "topup-site.com")["instance_id"]
        # 套餐越界/缺实例
        with self.assertRaises(FleetError):
            pay.create_order(self.s, self.buyer, "topup", "mock", instance_id=inst, pack_index=9)
        with self.assertRaises(FleetError):
            pay.create_order(self.s, self.buyer, "topup", "mock", pack_index=0)
        out = pay.create_order(self.s, self.buyer, "topup", "mock", instance_id=inst, pack_index=0)
        pay.mark_paid(self.s, out["order"]["order_no"], "TXN2")
        # 钱包到账：附赠 1000 + 充值 5000 万
        insts = oem.my_instances(self.s, self.buyer)
        self.assertEqual(insts[0]["balance_tokens"], 1000 + 50_000_000)

    # ---- 渠道占位 ----

    def test_placeholder_channels_rejected(self):
        pay.set_pricing(self.s, {"key_price_cents": 100})
        with self.assertRaises(FleetError):
            pay.create_order(self.s, self.buyer, "key", "alipay")  # 凭据未配 → 503
        with self.assertRaises(FleetError):
            pay.create_order(self.s, self.buyer, "key", "nonsense")  # 未知渠道


if __name__ == "__main__":
    unittest.main()
