"""普通用户 OEM 归属本地队列与 Nexus 同步回归测试。"""

from __future__ import annotations

import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import select

from cosmac import nexus_link
from cosmac.db import get_session, init_engine
from cosmac.db.models import OemUserAttribution


class _ReferralNexus(BaseHTTPRequestHandler):
    """同时模拟分享码校验和用户归属接收。"""

    payloads = []

    def do_GET(self):  # noqa: N802
        code = (parse_qs(urlsplit(self.path).query).get("code") or [""])[0]
        status = 200 if code == "VALIDCODE" else 404
        body = (
            {"code": code, "oem_id": 9, "name": "星辰 OEM"}
            if status == 200
            else {"error": "邀请链接已失效"}
        )
        self._json(status, body)

    def do_POST(self):  # noqa: N802
        size = int(self.headers.get("Content-Length") or 0)
        self.__class__.payloads.append(json.loads(self.rfile.read(size) or b"{}"))
        self._json(200, {"id": 1, "already": False, "oem_id": 9})

    def _json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class OemAttributionTest(unittest.TestCase):
    """注册关系先落本地，再幂等同步母舰。"""

    def setUp(self):
        init_engine("sqlite://")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _ReferralNexus)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        os.environ["COSMAC_NEXUS_URL"] = (
            f"http://127.0.0.1:{self.server.server_address[1]}"
        )
        os.environ["COSMAC_OEM_KEY"] = "CMK-AAAA-BBBB-CCCC-DDDD"
        _ReferralNexus.payloads = []

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        os.environ.pop("COSMAC_NEXUS_URL", None)
        os.environ.pop("COSMAC_OEM_KEY", None)

    def test_referral_validation_and_reliable_sync(self):
        info = nexus_link.referral_info("VALIDCODE")
        self.assertEqual(info["name"], "星辰 OEM")
        with self.assertRaises(nexus_link.ReferralError):
            nexus_link.referral_info("BAD")

        self.assertTrue(
            nexus_link.queue_user_attribution(
                "@alice:oem.example.com", "VALIDCODE"
            )
        )
        self.assertEqual(nexus_link.sync_pending_attributions(), 1)
        with get_session() as session:
            row = session.execute(select(OemUserAttribution)).scalar_one()
            self.assertEqual(row.status, "synced")
            self.assertIsNotNone(row.synced_at)
        self.assertEqual(_ReferralNexus.payloads[0]["user_id"], "@alice:oem.example.com")
        self.assertEqual(
            _ReferralNexus.payloads[0]["key"], "CMK-AAAA-BBBB-CCCC-DDDD"
        )


if __name__ == "__main__":
    unittest.main()
