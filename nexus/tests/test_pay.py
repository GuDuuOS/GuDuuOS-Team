"""Nexus 支付层回归测试（定价/订单/mock 履约/幂等/明文销毁）。

跑法（项目根）： .venv/bin/python -m unittest nexus.tests.test_pay -v
临时 SQLite,不碰真库;mock 渠道经 env 开关打开,不涉网络。
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from nexus import db, fleet, oem, pay
from nexus.fleet import FleetError


class PayTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        db.init_engine("sqlite:///" + self._tmp.name)
        self.s = db.session()
        os.environ["NEXUS_PAY_MOCK"] = "1"  # 打开模拟渠道
        self._old_secret = os.environ.get("NEXUS_SECRET_KEY")
        os.environ["NEXUS_SECRET_KEY"] = "test-license-payment-secret-at-least-32-bytes"
        self.buyer = oem.register(self.s, "buyer@x.com", "abc12345", inviter="GUDUU", company="测试公司", contact_name="张三", phone="13800000000")["id"]

    def tearDown(self):
        os.environ.pop("NEXUS_PAY_MOCK", None)
        if self._old_secret is None:
            os.environ.pop("NEXUS_SECRET_KEY", None)
        else:
            os.environ["NEXUS_SECRET_KEY"] = self._old_secret
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
        self.assertFalse(ch["stripe"])
        self.assertFalse(ch["paypal"])
        self.assertFalse(ch["usdt"])

    def test_overseas_credentials_do_not_open_real_payment(self):
        """凭据齐全只点亮总览状态；adapter 未联调前仍必须拒绝真钱下单。"""
        credentials = {
            "NEXUS_PAY_STRIPE_SECRET_KEY": "test",
            "NEXUS_PAY_STRIPE_WEBHOOK_SECRET": "test",
            "NEXUS_PAY_PAYPAL_CLIENT_ID": "test",
            "NEXUS_PAY_PAYPAL_CLIENT_SECRET": "test",
            "NEXUS_PAY_PAYPAL_WEBHOOK_ID": "test",
            "NEXUS_PAY_USDT_API_BASE": "https://provider.invalid",
            "NEXUS_PAY_USDT_API_KEY": "test",
            "NEXUS_PAY_USDT_WEBHOOK_SECRET": "test",
        }
        with patch.dict(os.environ, credentials, clear=False):
            states = pay.channels()
            for channel in ("stripe", "paypal", "usdt"):
                self.assertTrue(states[channel])
                with self.assertRaises(FleetError):
                    pay.create_order(self.s, self.buyer, "key", channel)

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

    def test_license_checkout_online_payment_auto_fulfills_once(self):
        """新购买流程要把申请和订单锁定，验签到账后只签发一把加密 KEY。"""
        pay.set_pricing(
            self.s,
            {"key_price_cents": 19_900, "key_token_grant": 88_000_000},
        )
        checkout = pay.create_license_checkout(
            self.s,
            self.buyer,
            "online",
            channel="mock",
            deployment_domain="paid.example.com",
            purpose="客户交付",
            source_ip="127.0.0.1",
        )
        request_id = checkout["request"]["id"]
        order_no = checkout["order"]["order_no"]
        self.assertEqual(checkout["request"]["payment_status"], "pending_payment")
        self.assertEqual(checkout["order"]["request_id"], request_id)

        paid = pay.mark_paid(
            self.s,
            order_no,
            "PAYMENT-TXN-1",
            paid_amount_cents=19_900,
            paid_currency="CNY",
        )
        request = oem.request_detail(self.s, request_id)
        self.assertEqual(request["status"], "approved")
        self.assertEqual(request["payment_status"], "fulfilled")
        self.assertEqual(request["delivery_status"], "ready")
        self.assertNotIn("key", paid)  # 订单结果绝不交付明文。
        self.assertEqual(len(oem.my_keys(self.s, self.buyer)), 1)

        again = pay.mark_paid(self.s, order_no, "DUPLICATE-CALLBACK")
        self.assertEqual(again["key_id"], paid["key_id"])
        self.assertEqual(len(oem.my_keys(self.s, self.buyer)), 1)

    def test_online_callback_amount_mismatch_never_issues_key(self):
        """支付回调金额不匹配时必须保持待支付，不得产生 KEY。"""
        pay.set_pricing(self.s, {"key_price_cents": 19_900})
        checkout = pay.create_license_checkout(
            self.s,
            self.buyer,
            "online",
            channel="mock",
            deployment_domain="amount.example.com",
            purpose="金额校验",
        )
        with self.assertRaises(FleetError) as raised:
            pay.mark_paid(
                self.s,
                checkout["order"]["order_no"],
                "BAD-AMOUNT",
                paid_amount_cents=1,
            )
        self.assertEqual(raised.exception.code, "NEXUS_PAY_AMOUNT_MISMATCH")
        self.assertEqual(oem.request_detail(self.s, checkout["request"]["id"])["status"], "pending")
        self.assertEqual(len(oem.my_keys(self.s, self.buyer)), 0)

    def test_cancelled_checkout_cannot_be_fulfilled_by_late_callback(self):
        """客户撤回后迟到的支付回调必须被拒绝，不能复活申请或签发 KEY。"""
        pay.set_pricing(self.s, {"key_price_cents": 19_900})
        checkout = pay.create_license_checkout(
            self.s,
            self.buyer,
            "online",
            channel="mock",
            deployment_domain="cancelled.example.com",
            purpose="撤回并发保护",
        )
        oem.cancel_request(self.s, self.buyer, checkout["request"]["id"])
        with self.assertRaises(FleetError) as raised:
            pay.mark_paid(self.s, checkout["order"]["order_no"], "LATE-CALLBACK")
        self.assertEqual(raised.exception.code, "NEXUS_ORDER_CLOSED")
        self.assertEqual(len(oem.my_keys(self.s, self.buyer)), 0)

    def test_corporate_transfer_requires_admin_confirmation(self):
        """企业转账凭证只是待审资料；超管核对到账前不计营收、不发 KEY。"""
        pay.set_pricing(
            self.s,
            {"key_price_cents": 29_900, "key_token_grant": 66_000_000},
        )
        image = b"\x89PNG\r\n\x1a\n" + b"license-transfer-receipt"
        checkout = pay.create_license_checkout(
            self.s,
            self.buyer,
            "corporate_transfer",
            deployment_domain="transfer.example.com",
            purpose="企业协作",
            image_data=image,
            content_type="image/png",
            filename="转账凭证.png",
            transfer_details={"payer_company": "测试企业"},
        )
        request_id = checkout["request"]["id"]
        pending = pay.finance_summary(self.s)
        self.assertEqual(pending["paid_revenue_cents"], 0)
        self.assertEqual(pending["pending_amount_cents"], 29_900)
        self.assertEqual(len(oem.my_keys(self.s, self.buyer)), 0)
        with self.assertRaises(FleetError) as raised:
            oem.decide_request(self.s, request_id, True, token_grant=1)
        self.assertEqual(raised.exception.code, "NEXUS_PAYMENT_CONFIRM_REQUIRED")

        confirmed = pay.decide_license_transfer(
            self.s,
            request_id,
            True,
            "已核对银行到账",
            source_ip="127.0.0.1",
        )
        self.assertEqual(confirmed["request"]["status"], "approved")
        self.assertEqual(confirmed["request"]["payment_status"], "fulfilled")
        self.assertEqual(len(oem.my_keys(self.s, self.buyer)), 1)
        finance = pay.finance_summary(self.s)
        self.assertEqual(finance["paid_revenue_cents"], 29_900)
        self.assertEqual(finance["pending_amount_cents"], 0)

        # 超管双击确认或首次响应丢失后重试，不得重复记收入或发码。
        pay.decide_license_transfer(self.s, request_id, True, "重试")
        self.assertEqual(len(oem.my_keys(self.s, self.buyer)), 1)
        self.assertEqual(pay.finance_summary(self.s)["paid_revenue_cents"], 29_900)

    def test_corporate_transfer_requires_payer_company(self):
        """接口不能只依赖前端 required，缺付款主体时整笔申请必须回滚。"""
        pay.set_pricing(self.s, {"key_price_cents": 29_900})
        with self.assertRaises(FleetError) as raised:
            pay.create_license_checkout(
                self.s,
                self.buyer,
                "corporate_transfer",
                deployment_domain="transfer.example.com",
                purpose="缺少付款主体",
                image_data=b"\x89PNG\r\n\x1a\nreceipt",
                content_type="image/png",
                filename="receipt.png",
                transfer_details={},
            )
        self.assertEqual(raised.exception.code, "NEXUS_TRANSFER_PAYER_REQUIRED")
        # 单元测试直接调用 service 函数时没有 HTTP 自动回滚，因此显式回滚，
        # 再证明没有任何申请、转账或 KEY 被错误提交。
        self.s.rollback()
        self.assertEqual(oem.my_requests(self.s, self.buyer), [])
        self.assertEqual(len(oem.my_keys(self.s, self.buyer)), 0)

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

    def test_finance_summary_only_counts_paid_orders(self):
        """资金总览只把已支付订单算收入，并正确拆分授权码与充值。"""
        empty = pay.finance_summary(self.s)
        self.assertEqual(empty["paid_revenue_cents"], 0)
        self.assertEqual(empty["pending_amount_cents"], 0)

        pay.set_pricing(
            self.s,
            {
                "key_price_cents": 19_900,
                "key_token_grant": 1_000,
                "topup_packs": [{"cents": 9_900, "tokens": 50_000_000}],
            },
        )
        key_order = pay.create_order(self.s, self.buyer, "key", "mock")["order"]
        pending = pay.finance_summary(self.s)
        self.assertEqual(pending["paid_revenue_cents"], 0)
        self.assertEqual(pending["pending_amount_cents"], 19_900)
        self.assertEqual(pending["pending_order_count"], 1)

        paid_key = pay.mark_paid(self.s, key_order["order_no"], "TXN-FIN-KEY")
        instance_id = fleet.redeem(
            self.s, paid_key["key"], "finance-site.com"
        )["instance_id"]
        topup_order = pay.create_order(
            self.s,
            self.buyer,
            "topup",
            "mock",
            instance_id=instance_id,
            pack_index=0,
        )["order"]
        pay.mark_paid(self.s, topup_order["order_no"], "TXN-FIN-TOPUP")

        summary = pay.finance_summary(self.s)
        self.assertEqual(summary["paid_revenue_cents"], 29_800)
        self.assertEqual(summary["paid_revenue_30d_cents"], 29_800)
        self.assertEqual(summary["pending_amount_cents"], 0)
        self.assertEqual(summary["paid_order_count"], 2)
        self.assertEqual(summary["key_revenue_cents"], 19_900)
        self.assertEqual(summary["topup_revenue_cents"], 9_900)
        self.assertEqual(summary["key_paid_count"], 1)
        self.assertEqual(summary["topup_paid_count"], 1)
        self.assertEqual(summary["topup_tokens"], 50_000_000)

    # ---- 渠道占位 ----

    def test_placeholder_channels_rejected(self):
        pay.set_pricing(self.s, {"key_price_cents": 100})
        with self.assertRaises(FleetError):
            pay.create_order(self.s, self.buyer, "key", "alipay")  # 凭据未配 → 503
        for channel in ("stripe", "paypal", "usdt"):
            with self.assertRaises(FleetError):
                pay.create_order(self.s, self.buyer, "key", channel)
        with self.assertRaises(FleetError):
            pay.create_order(self.s, self.buyer, "key", "nonsense")  # 未知渠道


if __name__ == "__main__":
    unittest.main()
