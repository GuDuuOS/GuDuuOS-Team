"""OEM 统一收款、直属价差、Token 转账充值与提现测试。"""

from __future__ import annotations

import os
import unittest

from nexus import db, fleet, oem, oem_finance, pay
from nexus.db import (
    NexusOemIncomeLedger,
    NexusOemWithdrawal,
    NexusOrder,
    NexusOrderCommercial,
    NexusWallet,
)


class OemFinanceTests(unittest.TestCase):
    """销售收益只能归直属上级，提现必须由只追加账本防止重复支出。"""

    def setUp(self) -> None:
        """建立平台主管、父 OEM、子 OEM 和可用 mock 支付环境。"""
        self.old_mock = os.environ.get("NEXUS_PAY_MOCK")
        self.old_secret = os.environ.get("NEXUS_SECRET_KEY")
        os.environ["NEXUS_PAY_MOCK"] = "1"
        os.environ["NEXUS_SECRET_KEY"] = "oem-finance-test-secret-at-least-32-bytes"
        db.init_engine("sqlite:///:memory:")
        self.s = db.session()
        parent = oem.register(
            self.s,
            "parent@example.com",
            "abc12345",
            inviter="GUDUU",
            company="父级销售企业",
            contact_name="父级联系人",
            phone="13800000001",
        )
        parent_share = oem.share_links(self.s, parent["id"], "https://nexus.test")
        child = oem.register(
            self.s,
            "child@example.com",
            "abc12345",
            inviter=parent_share["code"],
            company="下级购买企业",
            contact_name="子级联系人",
            phone="13800000002",
        )
        self.parent_id = int(parent["id"])
        self.child_id = int(child["id"])
        pay.set_pricing(
            self.s,
            {
                "key_price_cents": 10_000,
                "key_oem_cost_cents": 7_000,
                "key_token_grant": 1_000,
                "topup_packs": [
                    {
                        "cents": 5_000,
                        "oem_cost_cents": 2_000,
                        "tokens": 50_000,
                    }
                ],
                "settlement_days": 0,
                "withdraw_min_cents": 100,
            },
        )
        self.s.commit()

    def tearDown(self) -> None:
        """关闭会话并恢复测试修改过的环境变量。"""
        self.s.close()
        if self.old_mock is None:
            os.environ.pop("NEXUS_PAY_MOCK", None)
        else:
            os.environ["NEXUS_PAY_MOCK"] = self.old_mock
        if self.old_secret is None:
            os.environ.pop("NEXUS_SECRET_KEY", None)
        else:
            os.environ["NEXUS_SECRET_KEY"] = self.old_secret

    def _buy_child_key(self):
        """让子 OEM 付款购买一把 KEY，并返回支付成功订单。"""
        created = pay.create_order(self.s, self.child_id, "key", "mock")
        return pay.mark_paid(self.s, created["order"]["order_no"], "MOCK-KEY")

    def test_paid_order_credits_direct_parent_once(self) -> None:
        """客户实付与结算价之差只记直属上级，重复回调保持幂等。"""
        paid = self._buy_child_key()
        pay.mark_paid(self.s, paid["order_no"], "MOCK-DUPLICATE")
        parent = oem_finance.finance_snapshot(self.s, self.parent_id)
        child = oem_finance.finance_snapshot(self.s, self.child_id)
        self.assertEqual(parent["summary"]["earned_cents"], 3_000)
        self.assertEqual(parent["summary"]["available_cents"], 3_000)
        self.assertEqual(child["summary"]["earned_cents"], 0)
        rows = self.s.query(NexusOemIncomeLedger).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].buyer_oem_id, self.child_id)
        self.assertEqual(rows[0].gross_cents, 10_000)
        self.assertEqual(rows[0].settlement_cents, 7_000)

    def test_parent_specific_terms_override_global_cost_for_new_orders(self) -> None:
        """超管可给指定销售 OEM 单独设置授权成本和 Token 成本比例。"""
        oem_finance.set_commercial_terms(
            self.s,
            self.parent_id,
            {"key_cost_cents": 6_000, "topup_cost_bps": 5_000},
        )
        paid = self._buy_child_key()
        snapshot = oem_finance.finance_snapshot(self.s, self.parent_id)
        self.assertEqual(snapshot["summary"]["earned_cents"], 4_000)
        self.assertEqual(snapshot["terms"]["key_settlement_cents"], 6_000)
        self.assertEqual(snapshot["terms"]["topup_packs"][0]["settlement_cents"], 2_500)
        order = self.s.query(NexusOrder).filter_by(order_no=paid["order_no"]).one()
        commercial = self.s.get(NexusOrderCommercial, int(order.id))
        self.assertEqual(commercial.settlement_cents, 6_000)
        # 恢复默认后只影响后续订单，已付款订单的快照保持原样。
        oem_finance.set_commercial_terms(
            self.s, self.parent_id, {"use_default": True}
        )
        self.assertEqual(
            oem_finance.finance_snapshot(self.s, self.parent_id)["terms"][
                "key_settlement_cents"
            ],
            7_000,
        )

    def test_platform_direct_buyer_creates_no_oem_income(self) -> None:
        """挂在平台根下的父 OEM 自购不会凭空给任何 OEM 返佣。"""
        created = pay.create_order(self.s, self.parent_id, "key", "mock")
        pay.mark_paid(self.s, created["order"]["order_no"], "MOCK-ROOT")
        self.assertEqual(self.s.query(NexusOemIncomeLedger).count(), 0)

    def test_t_plus_seven_stays_pending_before_available_date(self) -> None:
        """默认结算等待期内收益只能显示待结算，不能提现。"""
        pay.set_pricing(self.s, {"settlement_days": 7})
        self._buy_child_key()
        summary = oem_finance.finance_snapshot(self.s, self.parent_id)["summary"]
        self.assertEqual(summary["pending_cents"], 3_000)
        self.assertEqual(summary["available_cents"], 0)

    def test_topup_transfer_fulfills_and_credits_margin(self) -> None:
        """Token 企业转账只有超管确认到账后才充值并产生直属价差。"""
        paid_key = self._buy_child_key()
        redeemed = fleet.redeem(
            self.s,
            str(paid_key["key"]),
            "child-node.example.com",
            "admin@example.com",
        )
        instance_id = int(redeemed["instance_id"])
        before = int(self.s.get(NexusWallet, instance_id).balance_tokens)
        checkout = pay.create_topup_transfer(
            self.s,
            self.child_id,
            instance_id,
            0,
            image_data=b"\x89PNG\r\n\x1a\nreceipt",
            content_type="image/png",
            filename="receipt.png",
            transfer_details={
                "payer_company": "下级购买企业",
                "transaction_id": "BANK-001",
            },
        )
        self.assertEqual(
            int(self.s.get(NexusWallet, instance_id).balance_tokens), before
        )
        pay.decide_topup_transfer(
            self.s, checkout["order"]["order_no"], True, "银行到账"
        )
        self.assertEqual(
            int(self.s.get(NexusWallet, instance_id).balance_tokens),
            before + 50_000,
        )
        snapshot = oem_finance.finance_snapshot(self.s, self.parent_id)
        self.assertEqual(snapshot["summary"]["earned_cents"], 6_000)
        platform = pay.finance_summary(self.s)
        self.assertEqual(platform["paid_revenue_cents"], 15_000)
        self.assertEqual(platform["manual_transfer_revenue_cents"], 0)

    def test_withdrawal_locks_balance_and_rejection_restores_it(self) -> None:
        """提现提交立即扣减可用余额，驳回以正向流水退回，批准后才能打款。"""
        self._buy_child_key()
        first = oem_finance.request_withdrawal(
            self.s,
            self.parent_id,
            2_000,
            {
                "method": "bank",
                "account_name": "父级销售企业",
                "account_no": "6222000012345678",
                "bank_name": "测试银行",
            },
        )
        self.assertEqual(
            oem_finance.finance_snapshot(self.s, self.parent_id)["summary"][
                "available_cents"
            ],
            1_000,
        )
        stored = self.s.get(NexusOemWithdrawal, int(first["id"]))
        self.assertNotIn(b"6222000012345678", bytes(stored.encrypted_payout))
        oem_finance.decide_withdrawal(
            self.s, int(first["id"]), "reject", "账户资料需要重填"
        )
        self.assertEqual(
            oem_finance.finance_snapshot(self.s, self.parent_id)["summary"][
                "available_cents"
            ],
            3_000,
        )
        second = oem_finance.request_withdrawal(
            self.s,
            self.parent_id,
            3_000,
            {
                "method": "alipay",
                "account_name": "父级销售企业",
                "account_no": "finance@example.com",
            },
        )
        oem_finance.decide_withdrawal(self.s, int(second["id"]), "approve")
        paid = oem_finance.decide_withdrawal(
            self.s, int(second["id"]), "paid", "BANK-PAYOUT-002"
        )
        self.assertEqual(paid["status"], "paid")
        self.assertEqual(
            oem_finance.finance_snapshot(self.s, self.parent_id)["summary"][
                "available_cents"
            ],
            0,
        )


if __name__ == "__main__":
    unittest.main()
