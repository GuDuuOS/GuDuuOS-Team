"""实例→母舰心跳（cosmac.nexus_link）的回归测试。

覆盖：启用开关（env 齐备才启动）、消息计数与跨天归零、
心跳载荷（真打到本地假母舰，断言字段与余额缓存）、无管理员令牌时不伪造用户数。
"""

from __future__ import annotations

import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cosmac import nexus_link
from cosmac.config import CosmacConfig


class _FakeNexus(BaseHTTPRequestHandler):
    """假母舰：记录收到的心跳载荷，回余额。"""

    last_payload: dict = {}

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        _FakeNexus.last_payload = json.loads(self.rfile.read(n) or b"{}")
        body = json.dumps(
            {"instance_id": 1, "status": "active", "balance_tokens": 4321}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # 静音
        pass


class NexusLinkTest(unittest.TestCase):
    def setUp(self):
        # 清干净计数器与相关 env，避免用例间串扰
        nexus_link._COUNTS.update({"day": "", "messages": 0})
        nexus_link._last_balance = None
        for k in ("COSMAC_NEXUS_URL", "COSMAC_OEM_KEY", "COSMAC_ADMIN_TOKEN",
                  "GUDUU_NEXUS_URL", "GUDUU_OEM_KEY", "GUDUU_ADMIN_TOKEN"):
            os.environ.pop(k, None)

    tearDown = setUp

    def test_enabled_requires_both_envs(self):
        self.assertFalse(nexus_link.enabled())
        os.environ["COSMAC_NEXUS_URL"] = "http://x"
        self.assertFalse(nexus_link.enabled())  # 只有 URL 不算接入
        os.environ["COSMAC_OEM_KEY"] = "CMK-AAAA-BBBB-CCCC-DDDD"
        self.assertTrue(nexus_link.enabled())

    def test_counter_and_day_rollover(self):
        nexus_link.note_message()
        nexus_link.note_message()
        self.assertEqual(nexus_link._messages_today(), 2)
        # 模拟跨天：把计数器的 day 拨到昨天 → 读数归零，再记从 1 开始
        nexus_link._COUNTS["day"] = "2000-01-01"
        self.assertEqual(nexus_link._messages_today(), 0)
        nexus_link.note_message()
        self.assertEqual(nexus_link._messages_today(), 1)

    def test_build_stats_no_admin_token_no_users(self):
        """拿不到管理员令牌时不上报 users——统计缺项好过伪造。"""
        config = CosmacConfig()
        stats = nexus_link.build_stats(config)
        self.assertIn("messages_today", stats)
        self.assertNotIn("users", stats)

    def test_beat_posts_payload_and_caches_balance(self):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), _FakeNexus)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            os.environ["COSMAC_NEXUS_URL"] = f"http://127.0.0.1:{srv.server_address[1]}"
            os.environ["COSMAC_OEM_KEY"] = "CMK-AAAA-BBBB-CCCC-DDDD"
            nexus_link.note_message()
            ok = nexus_link.beat(CosmacConfig())
            self.assertTrue(ok)
            p = _FakeNexus.last_payload
            self.assertEqual(p["key"], "CMK-AAAA-BBBB-CCCC-DDDD")
            self.assertTrue(p["version"])  # 上报了版本号
            self.assertEqual(p["stats"]["messages_today"], 1)
            self.assertEqual(nexus_link.get_last_balance(), 4321)
        finally:
            srv.shutdown()

    def test_beat_network_failure_returns_false(self):
        os.environ["COSMAC_NEXUS_URL"] = "http://127.0.0.1:1"  # 必然连不上
        os.environ["COSMAC_OEM_KEY"] = "CMK-AAAA-BBBB-CCCC-DDDD"
        self.assertFalse(nexus_link.beat(CosmacConfig()))


if __name__ == "__main__":
    unittest.main()
