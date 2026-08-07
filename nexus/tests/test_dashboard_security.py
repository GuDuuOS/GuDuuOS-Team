"""Nexus 大屏鉴权与浏览器安全策略回归测试。

本文件专门防止两类高风险回归：动态大屏重新接受管理员令牌，以及静态页面丢失 CSP。
前端 XSS 的 DOM 写入规则另由 ``console/dashboard/scripts/check-security.mjs`` 做静态检查。
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from nexus import admin_auth, db
from nexus.service import NexusHandler


class DashboardSecurityTests(unittest.TestCase):
    """用真实 HTTP 处理器验证大屏最小权限和安全响应头。"""

    @classmethod
    def setUpClass(cls) -> None:
        """启动仅监听本机随机端口的 Nexus 测试服务。"""
        cls._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls._tmp.close()
        db.init_engine("sqlite:///" + cls._tmp.name)
        s = db.session()
        admin_auth.create_admin(
            s,
            "dashboard-owner",
            "Dashboard1234!",
            "大屏测试管理员",
            actor_label="测试引导",
        )
        cls.admin_session = admin_auth.login(
            s, "dashboard-owner", "Dashboard1234!"
        )["token"]
        s.commit()
        s.close()
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
        os.unlink(cls._tmp.name)

    def setUp(self) -> None:
        """为每条用例配置只读令牌，管理端使用具名短会话。"""
        self.original_dash = os.environ.get("NEXUS_DASH_TOKEN")
        self.original_admin_url = os.environ.get("NEXUS_ADMIN_PUBLIC_URL")
        os.environ["NEXUS_DASH_TOKEN"] = "test-dashboard-read-token"

    def tearDown(self) -> None:
        """恢复调用测试前的环境变量，避免污染其它 Nexus 用例。"""
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
        """写权限管理员会话不能直接读取大屏接口。"""
        request = Request(
            f"{self.base_url}/nexus/dash/summary",
            headers={"Authorization": "Bearer " + self.admin_session},
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
            headers={"Authorization": "Bearer " + self.admin_session},
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

    def test_dashboard_demo_mode_is_local_only(self) -> None:
        """生产域名不能用公开查询参数把虚构运营数据伪装成真实大屏。"""
        with urlopen(f"{self.base_url}/app.js", timeout=3) as response:
            script = response.read().decode("utf-8")
        self.assertIn('new Set(["localhost", "127.0.0.1", "::1"])', script)
        self.assertIn("DEMO_REQUESTED && DEMO_HOSTS.has", script)

    def test_dashboard_summary_contains_real_finance_shape(self) -> None:
        """只读大屏接口必须返回真实资金聚合，而不是由前端填写演示金额。"""
        request = Request(
            f"{self.base_url}/nexus/dash/summary",
            headers={"Authorization": "Bearer test-dashboard-read-token"},
        )
        with urlopen(request, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertIn("finance", payload)
        self.assertEqual(payload["finance"]["paid_revenue_cents"], 0)

    def test_portal_page_has_strict_script_csp(self) -> None:
        """控制台只允许同源脚本和固定的 Cloudflare Turnstile 来源。"""
        with urlopen(f"{self.base_url}/portal/", timeout=3) as response:
            policy = response.headers["Content-Security-Policy"]
            self.assertIn("script-src 'self'", policy)
            self.assertNotIn("script-src 'self' 'unsafe-inline'", policy)
            self.assertIn("https://challenges.cloudflare.com", policy)
            self.assertIn("frame-src https://challenges.cloudflare.com", policy)
            self.assertIn("frame-ancestors 'none'", policy)

    def test_portal_shows_turnstile_result_next_to_each_challenge(self) -> None:
        """长表单必须就地显示挑战/发码结果，不能只把错误放在页面顶部。"""
        with urlopen(f"{self.base_url}/portal/", timeout=3) as response:
            html = response.read().decode("utf-8")
        self.assertEqual(html.count("turnstile-message"), 3)
        self.assertEqual(
            html.count('class="hint turnstile-message" aria-live="polite"'), 3
        )

        with urlopen(f"{self.base_url}/portal/portal.js", timeout=3) as response:
            script = response.read().decode("utf-8")
        self.assertIn("function setTurnstileMessage", script)
        self.assertIn("验证码已发送；60 秒后可重新验证并发送。", script)

    def test_public_installer_is_safe_bootstrap_without_embedded_key(self) -> None:
        """公开安装器必须锁定严格版本，并且绝不携带客户 KEY。"""
        with urlopen(f"{self.base_url}/portal/install.sh", timeout=3) as response:
            script = response.read().decode("utf-8")
            self.assertEqual(
                response.headers["Content-Type"],
                "text/x-shellscript; charset=utf-8",
            )
        self.assertIn('RELEASE_TAG="v1.29.2"', script)
        self.assertIn("优先拉 Docker Hub", script)
        self.assertIn('exec ./install.sh "${FORWARD_ARGS[@]}"', script)
        self.assertIn('--reinstall', script)
        self.assertIn('mv -- "$INSTALL_ROOT" "$REINSTALL_BACKUP"', script)
        self.assertNotIn("CMK-", script)
        self.assertNotIn("--key", script)

        with urlopen(f"{self.base_url}/portal/host-tools.sh", timeout=3) as response:
            host_tools = response.read().decode("utf-8")
        self.assertIn('RELEASE_TAG="v1.29.2"', host_tools)
        self.assertIn("migrate_host_tools.sh", host_tools)

        root = Path(__file__).resolve().parents[2]
        compose = (root / "distro" / "docker-compose.yml").read_text()
        dotenv = (root / "distro" / "templates" / "dotenv.tpl").read_text()
        for obsolete in (
            "COSMAC_SMTP_PASSWORD", "COSMAC_LLM_PROVIDER", "COSMAC_LLM_MODEL",
            "ARK_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
            "COSMAC_AGENT_ENGINE", "COSMAC_SDK_API_KEY",
        ):
            self.assertNotIn(obsolete, compose)
            self.assertNotIn(obsolete, dotenv)

        # 门户只用审批域名组装命令；KEY 继续走 SSH 交互输入。
        with urlopen(f"{self.base_url}/portal/portal.js", timeout=3) as response:
            portal_script = response.read().decode("utf-8")
        self.assertIn("function installCommand(domain, reinstall)", portal_script)
        self.assertIn("data-copy-install-domain", portal_script)
        self.assertIn("data-copy-reinstall-domain", portal_script)
        self.assertIn("/portal/install.sh | sudo bash -s -- --domain ", portal_script)
        self.assertIn('(reinstall ? " --reinstall" : "")', portal_script)

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

    def test_admin_portal_has_copyable_security_guide(self) -> None:
        """超管教程必须有独立导航、正文容器和 Markdown 复制入口。"""
        with urlopen(f"{self.base_url}/portal/admin/", timeout=3) as response:
            html = response.read().decode("utf-8")
        self.assertIn('data-admin-page="guide"', html)
        self.assertIn('data-admin-view="guide"', html)
        self.assertIn('id="btn-copy-admin-guide"', html)
        self.assertIn('id="admin-guide-content"', html)

        with urlopen(f"{self.base_url}/portal/portal.js", timeout=3) as response:
            script = response.read().decode("utf-8")
        self.assertIn("function adminGuideMarkdown()", script)
        self.assertIn("copyText(adminGuideMarkdown())", script)

    def test_admin_api_is_rejected_on_oem_host_after_domain_cutover(self) -> None:
        """启用管理域名后，OEM 主机不能绕过 Cloudflare Access 直接调用管理 API。"""
        os.environ["NEXUS_ADMIN_PUBLIC_URL"] = "https://admin-nexus.guduu.co"
        ordinary = Request(
            f"{self.base_url}/nexus/admin/dashboard-token",
            headers={
                "Authorization": "Bearer " + self.admin_session,
                "Host": "dev-nexus.guduu.co",
            },
        )
        with self.assertRaises(HTTPError) as raised:
            urlopen(ordinary, timeout=3)
        self.assertEqual(raised.exception.code, 404)

        protected = Request(
            f"{self.base_url}/nexus/admin/dashboard-token",
            headers={
                "Authorization": "Bearer " + self.admin_session,
                "Host": "admin-nexus.guduu.co",
            },
        )
        with urlopen(protected, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["token"], "test-dashboard-read-token")


if __name__ == "__main__":
    unittest.main()
