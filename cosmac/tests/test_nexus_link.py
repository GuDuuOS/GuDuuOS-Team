"""实例→母舰心跳（cosmac.nexus_link）的回归测试。

覆盖：启用开关（env 齐备才启动）、消息计数与跨天归零、
心跳载荷（真打到本地假母舰，断言字段与余额缓存）、无管理员令牌时不伪造用户数，
以及 Synapse 分页账号列表能正确拆分业务用户、管理员、AI 和异常状态账号。
"""

from __future__ import annotations

import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch

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
        """拿不到管理员令牌时不上报人数——统计缺项好过伪造。"""
        config = CosmacConfig()
        stats = nexus_link.build_stats(config)
        self.assertIn("messages_today", stats)
        self.assertFalse(any(key.startswith("users_") for key in stats))

    def test_user_breakdown_paginates_and_classifies_exclusively(self):
        """账号分类必须跨页完成，且每个账号只落入一个口径。"""
        os.environ["COSMAC_ADMIN_TOKEN"] = "admin-token"
        users = [
            {"name": "@alice:node.test", "admin": False},
            {"name": "@admin:node.test", "admin": True},
            {"name": "@guduu:node.test", "admin": False},
            {"name": "@guduu-ai-writer:node.test", "admin": False},
            {"name": "@guest:node.test", "is_guest": True},
            {"name": "@old:node.test", "deactivated": True, "admin": True},
            {"name": "@locked:node.test", "locked": True},
        ]

        def response_for_page(*_args, **kwargs):
            """假 Synapse 故意每页只返回 4 条，验证 from 续页。"""
            start = int(kwargs["params"]["from"])
            response = Mock()
            response.ok = True
            response.json.return_value = {
                "total": len(users),
                "users": users[start:start + 4],
            }
            return response

        config = CosmacConfig(
            homeserver_url="http://synapse:8008",
            bot_user_id="@guduu:node.test",
        )
        with patch("cosmac.nexus_link.requests.get", side_effect=response_for_page) as get:
            stats = nexus_link.build_stats(config)

        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args_list[0].kwargs["params"]["from"], 0)
        self.assertEqual(get.call_args_list[1].kwargs["params"]["from"], 4)
        self.assertEqual(stats["users_total"], 7)
        self.assertEqual(stats["users_business"], 1)
        self.assertEqual(stats["users_admin"], 1)
        self.assertEqual(stats["users_ai"], 2)
        self.assertEqual(stats["users_guest"], 1)
        self.assertEqual(stats["users_deactivated"], 1)
        self.assertEqual(stats["users_locked"], 1)
        self.assertEqual(
            stats["users_total"],
            sum(value for key, value in stats.items() if key.startswith("users_") and key != "users_total"),
        )

    def test_user_breakdown_drops_all_counts_when_a_page_fails(self):
        """分页失败时整组统计缺省，不展示似真的部分总数。"""
        os.environ["COSMAC_ADMIN_TOKEN"] = "admin-token"
        response = Mock()
        response.ok = False
        with patch("cosmac.nexus_link.requests.get", return_value=response):
            stats = nexus_link.build_stats(CosmacConfig())
        self.assertEqual(stats, {"messages_today": 0})

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
            srv.server_close()

    def test_beat_network_failure_returns_false(self):
        os.environ["COSMAC_NEXUS_URL"] = "http://127.0.0.1:1"  # 必然连不上
        os.environ["COSMAC_OEM_KEY"] = "CMK-AAAA-BBBB-CCCC-DDDD"
        self.assertFalse(nexus_link.beat(CosmacConfig()))


if __name__ == "__main__":
    unittest.main()
