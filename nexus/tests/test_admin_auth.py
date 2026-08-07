"""Nexus 具名超级管理员账号、会话和审计回归测试。"""

from __future__ import annotations

import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from typing import Any, Dict, Optional, Tuple
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import json

from nexus import admin_auth, audit, db
from nexus.fleet import FleetError
from nexus.service import NexusHandler


class AdminAuthTests(unittest.TestCase):
    """直接验证账号领域规则，不通过浏览器隐藏任何权限问题。"""

    def setUp(self) -> None:
        """每条用例使用独立内存库。"""
        db.init_engine("sqlite:///:memory:")
        self.s = db.session()

    def tearDown(self) -> None:
        """释放数据库连接。"""
        self.s.close()

    def _create(self, username: str = "admin") -> Dict[str, Any]:
        """创建一个符合密码策略的测试管理员。"""
        return admin_auth.create_admin(
            self.s,
            username,
            "Secure1234!",
            "测试管理员",
            actor_label="服务器单次恢复",
            source_ip="127.0.0.1",
        )

    def test_named_login_session_and_logout(self) -> None:
        """登录令牌只能解析到有效管理员，退出后立即失效。"""
        created = self._create()
        result = admin_auth.login(self.s, "ADMIN", "Secure1234!", "127.0.0.1")
        self.s.commit()
        resolved = admin_auth.resolve_session(self.s, result["token"])
        self.assertEqual(resolved.id, created["id"])
        self.assertEqual(result["admin"]["display_name"], "测试管理员")
        admin_auth.logout(self.s, result["token"])
        self.s.commit()
        self.assertIsNone(admin_auth.resolve_session(self.s, result["token"]))

    def test_password_reset_revokes_every_session(self) -> None:
        """改密码必须使所有旧浏览器会话失效，旧密码也不能继续登录。"""
        created = self._create()
        first = admin_auth.login(self.s, "admin", "Secure1234!")["token"]
        second = admin_auth.login(self.s, "admin", "Secure1234!")["token"]
        admin_auth.reset_password(
            self.s,
            created["id"],
            "Changed5678!",
            actor_label="测试管理员",
        )
        self.s.commit()
        self.assertIsNone(admin_auth.resolve_session(self.s, first))
        self.assertIsNone(admin_auth.resolve_session(self.s, second))
        with self.assertRaises(FleetError):
            admin_auth.login(self.s, "admin", "Secure1234!")
        self.assertTrue(admin_auth.login(self.s, "admin", "Changed5678!")["token"])

    def test_cannot_disable_self_or_last_active_admin(self) -> None:
        """错误操作不能把平台最后一个入口一起关掉。"""
        created = self._create()
        with self.assertRaises(FleetError) as self_disable:
            admin_auth.set_status(
                self.s,
                created["id"],
                "disabled",
                actor_id=created["id"],
                actor_label="测试管理员",
            )
        self.assertEqual(self_disable.exception.code, "NEXUS_ADMIN_SELF_DISABLE")
        with self.assertRaises(FleetError) as last_disable:
            admin_auth.set_status(
                self.s,
                created["id"],
                "disabled",
                actor_id=0,
                actor_label="服务器单次恢复",
            )
        self.assertEqual(last_disable.exception.code, "NEXUS_ADMIN_LAST_ACTIVE")

    def test_global_audit_contains_real_actor(self) -> None:
        """账号创建与登录都能在全局审计页按真实操作人检索。"""
        self._create()
        admin_auth.login(self.s, "admin", "Secure1234!", "10.0.0.8")
        self.s.commit()
        events = audit.recent(self.s, actor="测试管理员")
        self.assertEqual(events[0]["action"], "login")
        self.assertEqual(events[0]["source_ip"], "10.0.0.8")

    def test_roles_enforce_scoped_permissions_and_protect_last_superadmin(self) -> None:
        """细分角色只能命中自己的职责域，且最后一个超级管理员不能被降权。"""
        owner = self._create()
        operator = admin_auth.create_admin(
            self.s,
            "operator",
            "Secure1234!",
            "运营同事",
            role="operations",
            actor_label="测试管理员",
        )
        self.assertTrue(admin_auth.has_permission("operations", "operations.write"))
        self.assertFalse(admin_auth.has_permission("operations", "finance.read"))
        self.assertTrue(admin_auth.has_permission("auditor", "finance.read"))
        self.assertFalse(admin_auth.has_permission("auditor", "finance.write"))
        with self.assertRaises(FleetError) as last_owner:
            admin_auth.set_role(
                self.s,
                owner["id"],
                "auditor",
                actor_id=0,
                actor_label="服务器单次恢复",
            )
        self.assertEqual(last_owner.exception.code, "NEXUS_ADMIN_LAST_SUPERADMIN")
        changed = admin_auth.set_role(
            self.s,
            operator["id"],
            "finance",
            actor_id=owner["id"],
            actor_label="测试管理员",
        )
        self.assertEqual(changed["role"], "finance")

    def test_recovery_code_is_short_lived_and_single_use(self) -> None:
        """SSH 恢复码只能消费一次，且数据库不保存明文。"""
        created = admin_auth.create_recovery_code(self.s, ttl_minutes=15)
        self.s.commit()
        self.assertTrue(created["code"].startswith("NXR-"))
        result = admin_auth.consume_recovery_code(self.s, created["code"])
        self.s.commit()
        resolved = admin_auth.resolve_session(self.s, result["token"])
        self.assertEqual(resolved.id, 0)
        with self.assertRaises(FleetError) as reused:
            admin_auth.consume_recovery_code(self.s, created["code"])
        self.assertEqual(reused.exception.code, "NEXUS_RECOVERY_INVALID")


class AdminAuthHttpTests(unittest.TestCase):
    """用真实 HTTP 处理器验证单次恢复与具名会话鉴权。"""

    def setUp(self) -> None:
        """创建临时文件数据库，避免 HTTP 工作线程拿到不同内存连接。"""
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        db.init_engine("sqlite:///" + self._tmp.name)
        self._old_dash = os.environ.get("NEXUS_DASH_TOKEN")
        os.environ["NEXUS_DASH_TOKEN"] = "readonly-test-token"
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), NexusHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        """关闭服务并恢复环境变量。"""
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self._restore("NEXUS_DASH_TOKEN", self._old_dash)
        os.unlink(self._tmp.name)

    @staticmethod
    def _restore(name: str, value: Optional[str]) -> None:
        """恢复单个环境变量。"""
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value

    def _request(
        self,
        path: str,
        token: str = "",
        body: Optional[Dict[str, Any]] = None,
        *,
        cookie: str = "",
        csrf: bool = False,
    ) -> Dict[str, Any]:
        """发送 JSON 请求并返回解码结果。"""
        return self._exchange(
            path, token, body, cookie=cookie, csrf=csrf
        )[0]

    def _exchange(
        self,
        path: str,
        token: str = "",
        body: Optional[Dict[str, Any]] = None,
        *,
        cookie: str = "",
        csrf: bool = False,
    ) -> Tuple[Dict[str, Any], Any]:
        """发送请求并同时返回响应头，用于核对 HttpOnly Cookie 属性。"""
        raw = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        if cookie:
            headers["Cookie"] = cookie
        if csrf:
            headers["X-Nexus-CSRF"] = "1"
        request = Request(self.base_url + path, data=raw, headers=headers)
        with urlopen(request, timeout=3) as response:
            return json.loads(response.read().decode("utf-8")), response.headers

    def _recovery_cookie(self) -> str:
        """在数据库模拟 SSH 生成单次码，再通过 HTTP 换取恢复 Cookie。"""
        s = db.session()
        try:
            created = admin_auth.create_recovery_code(s, ttl_minutes=15)
            s.commit()
        finally:
            s.close()
        _, headers = self._exchange(
            "/nexus/admin/auth/recovery",
            body={"recovery_code": created["code"]},
        )
        return str(headers["Set-Cookie"]).split(";", 1)[0]

    def test_recovery_code_bootstraps_named_admin(self) -> None:
        """单次恢复会话可创建首个账号，之后日常走具名会话。"""
        recovery_cookie = self._recovery_cookie()
        created = self._request(
            "/nexus/admin/admins",
            body={
                "username": "owner",
                "display_name": "平台负责人",
                "password": "Owner1234!",
            },
            cookie=recovery_cookie,
            csrf=True,
        )
        self.assertEqual(created["admin"]["username"], "owner")
        login, login_headers = self._exchange(
            "/nexus/admin/auth/login",
            body={"username": "owner", "password": "Owner1234!"},
        )
        self.assertNotIn("token", login)
        set_cookie = str(login_headers["Set-Cookie"])
        self.assertIn("HttpOnly", set_cookie)
        self.assertIn("Secure", set_cookie)
        self.assertIn("SameSite=Strict", set_cookie)
        self.assertNotIn("Max-Age", set_cookie)
        cookie = set_cookie.split(";", 1)[0]
        me = self._request("/nexus/admin/me", cookie=cookie)
        self.assertEqual(me["admin"]["display_name"], "平台负责人")
        self.assertEqual(me["admin"]["auth_kind"], "named_cookie")
        self.assertEqual(
            self._request("/nexus/admin/dashboard-token", cookie=cookie)["token"],
            "readonly-test-token",
        )
        self._request(
            "/nexus/admin/auth/logout", body={}, cookie=cookie, csrf=True
        )
        with self.assertRaises(HTTPError) as raised:
            self._request("/nexus/admin/me", cookie=cookie)
        self.assertEqual(raised.exception.code, 401)

    def test_recovery_code_becomes_short_recovery_cookie(self) -> None:
        """浏览器提交单次码后只能收到短期 HttpOnly 恢复会话。"""
        cookie = self._recovery_cookie()
        me = self._request("/nexus/admin/me", cookie=cookie)
        self.assertEqual(me["admin"]["id"], 0)
        self.assertEqual(me["admin"]["auth_kind"], "recovery_cookie")

    def test_long_lived_emergency_token_endpoint_is_gone(self) -> None:
        """旧静态令牌端点必须显式返回 410，不得继续开后门。"""
        with self.assertRaises(HTTPError) as raised:
            self._request(
                "/nexus/admin/auth/emergency",
                body={"emergency_token": "legacy-secret"},
            )
        self.assertEqual(raised.exception.code, 410)

    def test_cookie_write_requires_csrf_header(self) -> None:
        """即使浏览器自动携带管理 Cookie，跨站写请求也必须被拒绝。"""
        cookie = self._recovery_cookie()
        with self.assertRaises(HTTPError) as raised:
            self._request(
                "/nexus/admin/admins",
                body={
                    "username": "blocked",
                    "display_name": "阻断测试",
                    "password": "Blocked1234!",
                },
                cookie=cookie,
            )
        self.assertEqual(raised.exception.code, 403)

    def test_http_role_permissions_are_enforced_by_server(self) -> None:
        """隐藏按钮不是权限边界：直接请求无权 API 也必须返回 403。"""
        recovery_cookie = self._recovery_cookie()
        self._request(
            "/nexus/admin/admins",
            body={
                "username": "operator",
                "display_name": "运营管理员",
                "password": "Operator1234!",
                "role": "operations",
            },
            cookie=recovery_cookie,
            csrf=True,
        )
        _, headers = self._exchange(
            "/nexus/admin/auth/login",
            body={"username": "operator", "password": "Operator1234!"},
        )
        cookie = str(headers["Set-Cookie"]).split(";", 1)[0]
        me = self._request("/nexus/admin/me", cookie=cookie)
        self.assertEqual(me["admin"]["role"], "operations")
        self.assertIn("operations.write", me["admin"]["permissions"])
        self._request("/nexus/admin/instances", cookie=cookie)
        with self.assertRaises(HTTPError) as finance_denied:
            self._request("/nexus/admin/finance_summary", cookie=cookie)
        self.assertEqual(finance_denied.exception.code, 403)
        with self.assertRaises(HTTPError) as ledger_denied:
            self._request("/nexus/admin/finance_ledger", cookie=cookie)
        self.assertEqual(ledger_denied.exception.code, 403)
        with self.assertRaises(HTTPError) as release_denied:
            self._request(
                "/nexus/admin/release_action",
                body={"release_id": 1, "action": "publish"},
                cookie=cookie,
                csrf=True,
            )
        self.assertEqual(release_denied.exception.code, 403)


if __name__ == "__main__":
    unittest.main()
