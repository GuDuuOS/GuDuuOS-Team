"""创作者认证流程（Token 经济 P3：申请/付费/审核）回归测试。

覆盖：申请状态机（提交→待付费→付费→待审→通过/拒绝→免费重提）、认证费订单履约
（幂等、失败回滚）、审核后授予创作者会员。零 key、内存 SQLite、假控制室。
"""

from __future__ import annotations

import os
import unittest
from typing import Any, Dict, Optional

from cosmac.config import TOKEN_CONFIG_EVENT_TYPE
from cosmac.db import cert_repo, init_engine, session_scope
from cosmac.db.order_repo import get_by_order_no
from cosmac.members import MembersStore
from cosmac.trading.service import OrderService
from cosmac.wallet import WalletStore

APPLICANT = "@dave:guduu.local"


def setUpModule() -> None:
    os.environ["COSMAC_PAY_MANUAL_SECRET"] = "test-manual-secret"


class FakeClient:
    def __init__(self):
        self._state: Dict[Any, Dict[str, Any]] = {
            TOKEN_CONFIG_EVENT_TYPE: {"enabled": True, "creator_cert_fee_cents": 30000},
        }

    def resolve_alias(self, _a) -> Optional[str]:
        return "!ctrl:h"

    def get_state_event(self, _room, etype, key=""):
        return self._state.get((etype, key), self._state.get(etype))

    def set_state_event(self, _room, etype, content, state_key="") -> bool:
        self._state[(etype, state_key)] = content
        return True


def _svc(client: FakeClient) -> OrderService:
    members = MembersStore(client, "#ctrl:h")
    wallet = WalletStore(client, "#ctrl:h", ttl=0)
    return OrderService(members, client, "#ctrl:h", wallet=wallet)


def _submit(user: str = APPLICANT):
    with session_scope() as s:
        return cert_repo.submit(
            s, user_id=user, name="老戴", contact="dave@x.com",
            intro="资深文案", portfolio="作品若干",
        )


class CertRepoTests(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)

    def test_submit_new_is_pending_payment(self) -> None:
        row = _submit()
        self.assertEqual(row.status, "pending_payment")
        self.assertFalse(row.paid)

    def test_paid_flow_and_review_approve(self) -> None:
        _submit()
        with session_scope() as s:
            self.assertTrue(cert_repo.mark_paid(s, APPLICANT, "o1"))
            self.assertEqual(cert_repo.get_application(s, APPLICANT).status, "pending_review")
            row = cert_repo.review(s, APPLICANT, approve=True)
            self.assertEqual(row.status, "approved")

    def test_reject_then_free_resubmit(self) -> None:
        _submit()
        with session_scope() as s:
            cert_repo.mark_paid(s, APPLICANT, "o1")
            cert_repo.review(s, APPLICANT, approve=False, reason="资料不全")
            self.assertEqual(cert_repo.get_application(s, APPLICANT).reason, "资料不全")
        # 已付过费 → 重提直接回待审（免费重提，定稿口径）
        row = _submit()
        self.assertEqual(row.status, "pending_review")
        self.assertEqual(row.reason, "")

    def test_reject_unpaid_resubmit_still_needs_payment(self) -> None:
        _submit()
        with session_scope() as s:
            # 没付费就被拒（管理员只审 pending_review，这里直接改状态模拟异常路径）
            row = cert_repo.get_application(s, APPLICANT)
            row.status = "rejected"
        row = _submit()
        self.assertEqual(row.status, "pending_payment")  # 没付过仍要付

    def test_review_only_pending_review(self) -> None:
        _submit()  # pending_payment
        with session_scope() as s:
            self.assertIsNone(cert_repo.review(s, APPLICANT, approve=True))


class CertOrderTests(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)
        self.client = FakeClient()
        self.svc = _svc(self.client)

    def test_cert_order_and_fulfillment_idempotent(self) -> None:
        _submit()
        res = self.svc.create_cert_order(user_id=APPLICANT)
        self.assertEqual(res["amount_cents"], 30000)   # 后台配的 300 元
        no = res["order_no"]
        with session_scope() as s:
            self.assertEqual(get_by_order_no(s, no).kind, "creator_cert")
        out = self.svc.on_payment_success(no, paid_amount_cents=30000, paid_currency="cny")
        self.assertTrue(out.get("cert"))
        with session_scope() as s:
            self.assertEqual(cert_repo.get_application(s, APPLICANT).status, "pending_review")
            self.assertTrue(cert_repo.get_application(s, APPLICANT).paid)
        # 幂等：重复回调不重复流转
        out2 = self.svc.on_payment_success(no)
        self.assertTrue(out2.get("already"))

    def test_fee_zero_rejects_order(self) -> None:
        self.client._state[TOKEN_CONFIG_EVENT_TYPE] = {"creator_cert_fee_cents": 0}
        from cosmac.trading.service import OrderError
        with self.assertRaises(OrderError):
            self.svc.create_cert_order(user_id=APPLICANT)

    def test_fulfill_without_application_reverts(self) -> None:
        # 没有申请记录却收到认证费回调（异常路径）→ 订单回滚待重试
        res_no = None
        _submit("@other:guduu.local")   # 别人的申请，不影响
        res = self.svc.create_cert_order(user_id=APPLICANT)  # dave 没提交过申请
        res_no = res["order_no"]
        from cosmac.trading.service import OrderError
        with self.assertRaises(OrderError):
            self.svc.on_payment_success(res_no)
        with session_scope() as s:
            self.assertEqual(get_by_order_no(s, res_no).status, "created")


if __name__ == "__main__":
    unittest.main()
