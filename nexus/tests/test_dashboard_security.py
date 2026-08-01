"""Nexus 大屏鉴权与浏览器安全策略回归测试。

本文件专门防止两类高风险回归：动态大屏重新接受管理员令牌，以及静态页面丢失 CSP。
前端 XSS 的 DOM 写入规则另由 ``console/dashboard/scripts/check-security.mjs`` 做静态检查。
"""

from __future__ import annotations

import json
import os
import threading
import unittest
from http.server import ThreadingHTTPServer
from typing import Optional
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from nexus.service import NexusHandler


class DashboardSecurityTests(unittest.TestCase):
    """用真实 HTTP 处理器验证大屏最小权限和安全响应头。"""

    @classmethod
    def setUpClass(cls) -> None:
        """启动仅监听本机随机端口的 Nexus 测试服务。"""
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), NexusHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        """关闭测试服务，避免端口和后台线程泄漏到后续测试。"""
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self) -> None:
        """为每条用例配置互不相同的管理/只读令牌。"""
        self.original_admin = os.environ.get("NEXUS_ADMIN_TOKEN")
        self.original_dash = os.environ.get("NEXUS_DASH_TOKEN")
        self.original_admin_url = os.environ.get("NEXUS_ADMIN_PUBLIC_URL")
        os.environ["NEXUS_ADMIN_TOKEN"] = "test-admin-write-token"
        os.environ["NEXUS_DASH_TOKEN"] = "test-dashboard-read-token"

    def tearDown(self) -> None:
        """恢复调用测试前的环境变量，避免污染其它 Nexus 用例。"""
        self._restore_env("NEXUS_ADMIN_TOKEN", self.original_admin)
        self._restore_env("NEXUS_DASH_TOKEN", self.original_dash)
        self._restore_env("NEXUS_ADMIN_PUBLIC_URL", self.original_admin_url)

    @staticmethod
    def _restore_env(name: str, value: Optional[str]) -> None:
        """把单个环境变量恢复成测试前的值。"""
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value

    def test_dashboard_rejects_admin_token(self) -> None:
        """写权限管理员令牌不能直接读取大屏接口。"""
        request = Request(
            f"{self.base_url}/nexus/dash/summary",
            headers={"Authorization": "Bearer test-admin-write-token"},
        )
        with self.assertRaises(HTTPError) as raised:
            urlopen(request, timeout=3)
        self.assertEqual(raised.exception.code, 401)
        payload = json.loads(raised.exception.read().decode("utf-8"))
        self.assertEqual(payload["errcode"], "NEXUS_FORBIDDEN")

    def test_admin_exchanges_for_read_only_dashboard_token(self) -> None:
        """管理员通过受保护端点只能取得只读大屏令牌。"""
        request = Request(
            f"{self.base_url}/nexus/admin/dashboard-token",
            headers={"Authorization": "Bearer test-admin-write-token"},
        )
        with urlopen(request, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(payload, {"token": "test-dashboard-read-token"})
            self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_dashboard_page_has_strict_csp(self) -> None:
        """生产同款静态处理器必须限制脚本来源并禁止页面套壳。"""
        with urlopen(f"{self.base_url}/", timeout=3) as response:
            policy = response.headers["Content-Security-Policy"]
            self.assertIn("script-src 'self'", policy)
            self.assertIn("object-src 'none'", policy)
            self.assertIn("frame-ancestors 'none'", policy)
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
            self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")

    def test_portal_page_has_strict_script_csp(self) -> None:
        """控制台持有管理会话，必须禁止任何内联或第三方脚本执行。"""
        with urlopen(f"{self.base_url}/portal/", timeout=3) as response:
            policy = response.headers["Content-Security-Policy"]
            self.assertIn("script-src 'self'", policy)
            self.assertNotIn("script-src 'self' 'unsafe-inline'", policy)
            self.assertIn("frame-ancestors 'none'", policy)

    def test_admin_has_independent_noindex_entry(self) -> None:
        """独立超管深链必须可刷新直达，同时明确禁止搜索引擎收录。"""
        with urlopen(f"{self.base_url}/portal/admin/", timeout=3) as response:
            html = response.read().decode("utf-8")
            self.assertEqual(response.status, 200)
            self.assertEqual(
                response.headers["X-Robots-Tag"],
                "noindex, nofollow, noarchive",
            )
            self.assertIn('id="form-admin"', html)
            self.assertNotIn('data-tab="admin"', html)

    def test_admin_api_is_rejected_on_oem_host_after_domain_cutover(self) -> None:
        """启用管理域名后，OEM 主机不能绕过 Cloudflare Access 直接调用管理 API。"""
        os.environ["NEXUS_ADMIN_PUBLIC_URL"] = "https://admin-nexus.guduu.co"
        ordinary = Request(
            f"{self.base_url}/nexus/admin/dashboard-token",
            headers={
                "Authorization": "Bearer test-admin-write-token",
                "Host": "dev-nexus.guduu.co",
            },
        )
        with self.assertRaises(HTTPError) as raised:
            urlopen(ordinary, timeout=3)
        self.assertEqual(raised.exception.code, 404)

        protected = Request(
            f"{self.base_url}/nexus/admin/dashboard-token",
            headers={
                "Authorization": "Bearer test-admin-write-token",
                "Host": "admin-nexus.guduu.co",
            },
        )
        with urlopen(protected, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["token"], "test-dashboard-read-token")


if __name__ == "__main__":
    unittest.main()
