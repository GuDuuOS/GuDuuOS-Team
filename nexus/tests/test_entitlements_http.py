"""终身会员激活码与 Token 购买申请的真实 HTTP 流程测试。"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from typing import Any, Dict, Optional
from urllib.request import Request, urlopen

from nexus import admin_auth, db, fleet, oem
from nexus.service import NexusHandler


class EntitlementHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        db.init_engine("sqlite:///" + self._tmp.name)
        self._old_secret = os.environ.get("NEXUS_SECRET_KEY")
        os.environ["NEXUS_SECRET_KEY"] = (
            "entitlement-http-test-secret-at-least-32-bytes"
        )

        s = db.session()
        account = oem.register(
            s,
            "entitlement-http@example.com",
            "abc12345",
            inviter="GUDUU",
            company="终身会员接口测试企业",
            contact_name="测试人",
            phone="13800000000",
        )
        self.oem_id = int(account["id"])
        self.oem_token = oem.login(
            s, "entitlement-http@example.com", "abc12345"
        )["token"]
        issued = fleet.issue_keys(s, 1)[0]
        self.node_key = issued["key"]
        oem.claim_key(s, self.oem_id, self.node_key)
        self.instance_id = int(
            fleet.redeem(s, self.node_key, "entitlement-http.example.com")[
                "instance_id"
            ]
        )
        admin_auth.create_admin(
            s,
            "entitlement-owner",
            "Entitlement1234!",
            "权益测试管理员",
            actor_label="测试引导",
        )
        self.admin_token = admin_auth.login(
            s, "entitlement-owner", "Entitlement1234!"
        )["token"]
        s.commit()
        s.close()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), NexusHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        if self._old_secret is None:
            os.environ.pop("NEXUS_SECRET_KEY", None)
        else:
            os.environ["NEXUS_SECRET_KEY"] = self._old_secret
        os.unlink(self._tmp.name)

    def _json_request(
        self,
        path: str,
        token: str = "",
        body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        raw = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        request = Request(self.base_url + path, data=raw, headers=headers)
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_lifetime_request_approval_reveal_and_node_activation(self) -> None:
        created = self._json_request(
            "/nexus/oem/lifetime_request",
            self.oem_token,
            {"instance_id": self.instance_id, "note": "内部长期使用"},
        )["request"]
        self.assertEqual(created["status"], "pending")

        pending = self._json_request(
            "/nexus/admin/lifetime_requests", self.admin_token
        )["requests"]
        self.assertEqual(pending[0]["id"], created["id"])
        approved = self._json_request(
            "/nexus/admin/lifetime_request_decide",
            self.admin_token,
            {"request_id": created["id"], "approve": True},
        )["request"]
        self.assertEqual(approved["status"], "approved")

        revealed = self._json_request(
            "/nexus/oem/lifetime_action",
            self.oem_token,
            {"request_id": created["id"], "action": "reveal"},
        )
        self.assertTrue(revealed["activation_code"].startswith("GLM-"))
        activated = self._json_request(
            "/nexus/lifetime/activate",
            body={
                "key": self.node_key,
                "activation_code": revealed["activation_code"],
                "user_id": "@alice:entitlement-http.example.com",
                "device_kind": "node",
            },
        )
        self.assertEqual(activated["membership"], "paid")
        self.assertEqual(activated["expires_ts"], 0)

    def test_token_request_is_visible_and_credits_only_after_confirmation(self) -> None:
        created = self._json_request(
            "/nexus/oem/token_purchase_request",
            self.oem_token,
            {
                "instance_id": self.instance_id,
                "requested_tokens": 2_000_000,
                "note": "合同采购",
            },
        )["request"]
        self.assertEqual(created["status"], "pending")
        before = self._json_request("/nexus/oem/me", self.oem_token)
        self.assertEqual(before["instances"][0]["balance_tokens"], 0)

        pending = self._json_request(
            "/nexus/admin/token_purchase_requests", self.admin_token
        )["requests"]
        self.assertEqual(pending[0]["id"], created["id"])
        paid = self._json_request(
            "/nexus/admin/token_purchase_decide",
            self.admin_token,
            {
                "request_id": created["id"],
                "approve": True,
                "amount_cents": 15_800,
                "decide_note": "已核实到账",
            },
        )["request"]
        self.assertEqual(paid["status"], "paid")
        after = self._json_request("/nexus/oem/me", self.oem_token)
        self.assertEqual(after["instances"][0]["balance_tokens"], 2_000_000)


if __name__ == "__main__":
    unittest.main()
