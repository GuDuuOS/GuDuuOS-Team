"""Nexus 具名超级管理员账号、会话和审计回归测试。"""

from __future__ import annotations

import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from typing import Any, Dict, Optional
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
            actor_label="服务器应急令牌",
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
                actor_label="服务器应急令牌",
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


class AdminAuthHttpTests(unittest.TestCase):
    """用真实 HTTP 处理器验证应急引导和具名会话都能访问管理端点。"""

    def setUp(self) -> None:
        """创建临时文件数据库，避免 HTTP 工作线程拿到不同内存连接。"""
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        db.init_engine("sqlite:///" + self._tmp.name)
        self._old_admin = os.environ.get("NEXUS_ADMIN_TOKEN")
        self._old_dash = os.environ.get("NEXUS_DASH_TOKEN")
        os.environ["NEXUS_ADMIN_TOKEN"] = "emergency-test-token"
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
        self._restore("NEXUS_ADMIN_TOKEN", self._old_admin)
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
        self, path: str, token: str = "", body: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """发送 JSON 请求并返回解码结果。"""
        raw = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        request = Request(self.base_url + path, data=raw, headers=headers)
        with urlopen(request, timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_emergency_token_bootstraps_named_admin(self) -> None:
        """现有生产令牌可创建首个账号，之后日常接口接受短期会话。"""
        created = self._request(
            "/nexus/admin/admins",
            "emergency-test-token",
            {
                "username": "owner",
                "display_name": "平台负责人",
                "password": "Owner1234!",
            },
        )
        self.assertEqual(created["admin"]["username"], "owner")
        login = self._request(
            "/nexus/admin/auth/login",
            body={"username": "owner", "password": "Owner1234!"},
        )
        me = self._request("/nexus/admin/me", login["token"])
        self.assertEqual(me["admin"]["display_name"], "平台负责人")
        self.assertEqual(me["admin"]["auth_kind"], "named_session")
        self.assertEqual(
            self._request("/nexus/admin/dashboard-token", login["token"])["token"],
            "readonly-test-token",
        )
        self._request("/nexus/admin/auth/logout", login["token"], {})
        with self.assertRaises(HTTPError) as raised:
            self._request("/nexus/admin/me", login["token"])
        self.assertEqual(raised.exception.code, 401)


if __name__ == "__main__":
    unittest.main()
