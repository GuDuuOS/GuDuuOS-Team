"""终身会员激活码与 OEM Token 购买申请测试。"""

from __future__ import annotations

import os
import unittest

from nexus import db, entitlements, fleet, oem, pay
from nexus.fleet import FleetError


class EntitlementTests(unittest.TestCase):
    def setUp(self) -> None:
        db.init_engine("sqlite:///:memory:")
        self.s = db.session()
        self.old_secret = os.environ.get("NEXUS_SECRET_KEY")
        os.environ["NEXUS_SECRET_KEY"] = "entitlement-test-secret-at-least-32-bytes"
        account = oem.register(
            self.s,
            "lifetime@example.com",
            "abc12345",
            inviter="GUDUU",
            company="终身会员测试企业",
            contact_name="测试人",
            phone="13800000000",
        )
        self.oem_id = int(account["id"])
        issued = fleet.issue_keys(self.s, 1)[0]
        self.node_key = issued["key"]
        oem.claim_key(self.s, self.oem_id, self.node_key)
        self.instance_id = int(
            fleet.redeem(self.s, self.node_key, "lifetime.example.com")["instance_id"]
        )
        self.s.commit()

    def tearDown(self) -> None:
        self.s.close()
        if self.old_secret is None:
            os.environ.pop("NEXUS_SECRET_KEY", None)
        else:
            os.environ["NEXUS_SECRET_KEY"] = self.old_secret

    def test_lifetime_code_is_node_bound_and_one_user_only(self) -> None:
        request = entitlements.request_lifetime_code(
            self.s, self.oem_id, self.instance_id, "给内部员工"
        )
        approved = entitlements.decide_lifetime_request(
            self.s, request["id"], True, "已审批"
        )
        self.assertEqual(approved["status"], "approved")
        revealed = entitlements.reveal_lifetime_code(
            self.s, self.oem_id, request["id"]
        )
        code = revealed["activation_code"]
        self.assertTrue(code.startswith("GLM-"))

        result = entitlements.activate_lifetime_code(
            self.s,
            raw_node_key=self.node_key,
            activation_code=code,
            user_id="@alice:lifetime.example.com",
        )
        self.assertEqual(result["membership"], "paid")
        self.assertEqual(result["expires_ts"], 0)
        self.assertFalse(result["already_activated"])

        again = entitlements.activate_lifetime_code(
            self.s,
            raw_node_key=self.node_key,
            activation_code=code,
            user_id="@alice:lifetime.example.com",
        )
        self.assertTrue(again["already_activated"])
        with self.assertRaises(FleetError) as raised:
            entitlements.activate_lifetime_code(
                self.s,
                raw_node_key=self.node_key,
                activation_code=code,
                user_id="@bob:lifetime.example.com",
            )
        self.assertEqual(raised.exception.code, "NEXUS_LIFETIME_CODE_USED")

    def test_token_request_only_credits_after_finance_confirms_payment(self) -> None:
        request = entitlements.request_token_purchase(
            self.s,
            self.oem_id,
            self.instance_id,
            12_000_000,
            "合同采购",
        )
        before = fleet.list_instances(self.s)[0]["balance_tokens"]
        self.assertEqual(before, 0)

        paid = entitlements.decide_token_purchase_request(
            self.s,
            request["id"],
            approve=True,
            amount_cents=88_000,
            decide_note="已核对银行到账",
        )
        self.assertEqual(paid["status"], "paid")
        self.assertEqual(
            fleet.list_instances(self.s)[0]["balance_tokens"], 12_000_000
        )
        ledger = pay.finance_ledger(self.s)
        self.assertEqual(ledger[0]["source"], "payment")
        self.assertEqual(ledger[0]["amount_cents"], 88_000)

    def test_desktop_scope_is_reserved_until_desktop_release(self) -> None:
        request = entitlements.request_lifetime_code(
            self.s, self.oem_id, self.instance_id
        )
        entitlements.decide_lifetime_request(self.s, request["id"], True)
        code = entitlements.reveal_lifetime_code(
            self.s, self.oem_id, request["id"]
        )["activation_code"]
        with self.assertRaises(FleetError) as raised:
            entitlements.activate_lifetime_code(
                self.s,
                raw_node_key=self.node_key,
                activation_code=code,
                user_id="@alice:lifetime.example.com",
                device_kind="desktop",
            )
        self.assertEqual(raised.exception.code, "NEXUS_DESKTOP_NOT_RELEASED")


if __name__ == "__main__":
    unittest.main()
