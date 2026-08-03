"""Nexus OEM 邮箱认证回归测试。

覆盖注册验证、无密码登录、找回密码、验证码用途隔离、限次和防账号枚举。测试替换
SMTP 发送函数，只验证业务与持久化，不连接外部邮件服务器。
"""

from __future__ import annotations

import os
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from typing import Any, Dict, Optional
from urllib.request import Request, urlopen
from unittest.mock import patch

from nexus import db, oem, oem_email
from nexus.fleet import FleetError
from nexus.service import NexusHandler


class OemEmailAuthTests(unittest.TestCase):
    """每条测试使用独立 SQLite 与假 SMTP，避免污染本地或生产数据。"""

    def setUp(self) -> None:
        """准备数据库、邮箱配置和捕获验证码的发送替身。"""
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        db.init_engine("sqlite:///" + self._tmp.name)
        self.s = db.session()
        self._old_env = {
            key: os.environ.get(key)
            for key in (
                "NEXUS_SECRET_KEY",
                "NEXUS_SMTP_HOST",
                "NEXUS_SMTP_USER",
                "NEXUS_SMTP_PASSWORD",
                "NEXUS_SMTP_FROM",
                "NEXUS_TURNSTILE_SITE_KEY",
                "NEXUS_TURNSTILE_SECRET_KEY",
                "NEXUS_TURNSTILE_HOSTNAME",
            )
        }
        os.environ.update(
            {
                "NEXUS_SECRET_KEY": "test-secret-key-that-is-at-least-32-bytes-long",
                "NEXUS_SMTP_HOST": "smtp.test.invalid",
                "NEXUS_SMTP_USER": "noreply@test.invalid",
                "NEXUS_SMTP_PASSWORD": "not-a-real-secret",
                "NEXUS_SMTP_FROM": "noreply@test.invalid",
            }
        )
        # 邮箱领域测试聚焦验证码生命周期，显式关闭可选的 HTTP 人机校验层。
        os.environ.pop("NEXUS_TURNSTILE_SITE_KEY", None)
        os.environ.pop("NEXUS_TURNSTILE_SECRET_KEY", None)
        os.environ.pop("NEXUS_TURNSTILE_HOSTNAME", None)
        self.sent = []
        self._send_patch = patch.object(
            oem_email,
            "_send_email",
            side_effect=lambda email, code, purpose: self.sent.append(
                (email, code, purpose)
            ),
        )
        self._send_patch.start()

    def tearDown(self) -> None:
        """关闭替身与数据库，并完整恢复进程环境。"""
        self._send_patch.stop()
        self.s.close()
        os.unlink(self._tmp.name)
        for key, value in self._old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _request(self, email: str, purpose: str) -> str:
        """申请验证码并返回测试替身捕获的原文。"""
        result = oem_email.request_code(self.s, email, purpose)
        self.assertTrue(result["ok"])
        self.assertEqual(self.sent[-1][0], email.strip().lower())
        self.assertEqual(self.sent[-1][2], purpose)
        return self.sent[-1][1]

    def _register(self, email: str = "owner@example.com") -> dict:
        """完成一次真实的“发码→验码→建企业账号”流程。"""
        code = self._request(email, "register")
        return oem_email.register_with_code(
            self.s,
            email=email,
            code=code,
            password="abc12345",
            inviter="GUDUU",
            company="邮箱认证测试企业",
            contact_name="测试人",
            phone="13800000000",
        )

    def test_verified_registration_consumes_code_once(self) -> None:
        """新账号必须验证邮箱，验证码成功后不可再次使用。"""
        email = " Owner@Example.com "
        code = self._request(email, "register")
        public = oem_email.register_with_code(
            self.s,
            email=email,
            code=code,
            password="abc12345",
            inviter="GUDUU",
            company="邮箱认证测试企业",
            contact_name="测试人",
            phone="13800000000",
        )
        self.assertEqual(public["email"], "owner@example.com")
        verified = self.s.get(db.NexusOemEmailVerification, public["id"])
        self.assertIsNotNone(verified)
        self.assertEqual(verified.email, "owner@example.com")
        with self.assertRaises(FleetError):
            oem_email.register_with_code(
                self.s,
                email=email,
                code=code,
                password="abc12345",
                inviter="GUDUU",
                company="另一家企业",
                contact_name="测试人",
                phone="13800000000",
            )

    def test_request_code_passes_turnstile_context_before_account_lookup(self) -> None:
        """发码领域入口必须把一次性 token、用途和来源 IP 交给安全校验层。"""
        with patch.object(oem_email.turnstile, "verify", return_value=True) as verify:
            result = oem_email.request_code(
                self.s,
                "robot-check@example.com",
                "register",
                turnstile_token="browser-token",
                source_ip="203.0.113.9",
            )
        self.assertTrue(result["ok"])
        verify.assert_called_once_with(
            "browser-token", "register", "203.0.113.9"
        )

    def test_code_login_uses_independent_purpose(self) -> None:
        """注册码不能冒充登录码；登录码验证后签发可解析的 OEM 会话。"""
        public = self._register()
        register_code = self.sent[-1][1]
        with self.assertRaises(FleetError):
            oem_email.login_with_code(self.s, public["email"], register_code)

        login_code = self._request(public["email"], "login")
        result = oem_email.login_with_code(self.s, public["email"], login_code)
        self.assertEqual(result["oem"]["id"], public["id"])
        self.assertEqual(
            oem.resolve_session(self.s, result["token"]).id,
            public["id"],
        )

    def test_reset_password_revokes_all_old_sessions(self) -> None:
        """找回密码后旧浏览器会话全部失效，且只能用新密码再次登录。"""
        public = self._register()
        token_a = oem.login(self.s, public["email"], "abc12345")["token"]
        token_b = oem.login(self.s, public["email"], "abc12345")["token"]
        reset_code = self._request(public["email"], "reset")
        self.assertTrue(
            oem_email.reset_password(
                self.s, public["email"], reset_code, "newpass123", "127.0.0.1"
            )["ok"]
        )
        self.assertIsNone(oem.resolve_session(self.s, token_a))
        self.assertIsNone(oem.resolve_session(self.s, token_b))
        with self.assertRaises(FleetError):
            oem.login(self.s, public["email"], "abc12345")
        self.assertIn("token", oem.login(self.s, public["email"], "newpass123"))

    def test_unknown_login_and_reset_do_not_send_or_reveal(self) -> None:
        """不存在账号也返回通用成功响应，但不会真实消耗邮件配额。"""
        before = len(self.sent)
        for purpose in ("login", "reset"):
            result = oem_email.request_code(self.s, "ghost@example.com", purpose)
            self.assertEqual(result, {"ok": True, "cooldown_seconds": 60})
        self.assertEqual(len(self.sent), before)

    def test_wrong_code_is_locked_after_five_attempts(self) -> None:
        """连续输错五次后即使拿到原码也不能再验证。"""
        code = self._request("locked@example.com", "register")
        for _ in range(5):
            with self.assertRaises(FleetError):
                oem_email.register_with_code(
                    self.s,
                    email="locked@example.com",
                    code="000000" if code != "000000" else "999999",
                    password="abc12345",
                    inviter="GUDUU",
                    company="邮箱认证测试企业",
                    contact_name="测试人",
                    phone="13800000000",
                )
        with self.assertRaises(FleetError):
            oem_email.register_with_code(
                self.s,
                email="locked@example.com",
                code=code,
                password="abc12345",
                inviter="GUDUU",
                company="邮箱认证测试企业",
                contact_name="测试人",
                phone="13800000000",
            )

    def test_existing_disabled_email_cannot_register_again(self) -> None:
        """停用账号仍占用唯一邮箱，不可借注册流程覆盖原账号。"""
        public = self._register("disabled@example.com")
        self.s.get(db.NexusOem, public["id"]).status = "disabled"
        with self.assertRaises(FleetError) as raised:
            oem_email.request_code(self.s, public["email"], "register")
        self.assertEqual(raised.exception.code, "NEXUS_EMAIL_TAKEN")


class OemEmailAuthHttpTests(unittest.TestCase):
    """通过真实 HTTP 处理器核对公开接口与领域服务正确接线。"""

    def setUp(self) -> None:
        """建立文件数据库、假发信函数和本机随机端口服务。"""
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        db.init_engine("sqlite:///" + self._tmp.name)
        self._old_env = {
            key: os.environ.get(key)
            for key in (
                "NEXUS_SECRET_KEY",
                "NEXUS_SMTP_HOST",
                "NEXUS_SMTP_USER",
                "NEXUS_SMTP_PASSWORD",
                "NEXUS_TURNSTILE_SITE_KEY",
                "NEXUS_TURNSTILE_SECRET_KEY",
                "NEXUS_TURNSTILE_HOSTNAME",
            )
        }
        os.environ.update(
            {
                "NEXUS_SECRET_KEY": "http-test-secret-key-that-is-over-32-bytes",
                "NEXUS_SMTP_HOST": "smtp.test.invalid",
                "NEXUS_SMTP_USER": "noreply@test.invalid",
                "NEXUS_SMTP_PASSWORD": "not-a-real-secret",
            }
        )
        # 默认用未启用状态验证向后兼容；Turnstile 自身由独立测试覆盖。
        os.environ.pop("NEXUS_TURNSTILE_SITE_KEY", None)
        os.environ.pop("NEXUS_TURNSTILE_SECRET_KEY", None)
        os.environ.pop("NEXUS_TURNSTILE_HOSTNAME", None)
        self.sent = []
        self._send_patch = patch.object(
            oem_email,
            "_send_email",
            side_effect=lambda email, code, purpose: self.sent.append(
                (email, code, purpose)
            ),
        )
        self._send_patch.start()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), NexusHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        """关闭 HTTP 服务、恢复环境并删除临时数据库。"""
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self._send_patch.stop()
        for key, value in self._old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        os.unlink(self._tmp.name)

    def _request(
        self, path: str, body: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """发送公开 JSON 请求并解析成功响应。"""
        raw = json.dumps(body).encode("utf-8") if body is not None else None
        request = Request(
            self.base_url + path,
            data=raw,
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_register_code_login_and_reset_routes(self) -> None:
        """公开配置、发码、注册、验证码登录和找回密码端点完整可达。"""
        self.assertTrue(
            self._request("/nexus/oem/auth/config")["email_verification"]
        )
        email = "http@example.com"
        self._request(
            "/nexus/oem/email/request-code",
            {"email": email, "purpose": "register"},
        )
        register_code = self.sent[-1][1]
        registered = self._request(
            "/nexus/oem/register",
            {
                "email": email,
                "code": register_code,
                "password": "abc12345",
                "inviter": "GUDUU",
                "company": "HTTP 邮箱认证企业",
                "contact_name": "测试人",
                "phone": "13800000000",
            },
        )
        self.assertEqual(registered["oem"]["email"], email)

        self._request(
            "/nexus/oem/email/request-code",
            {"email": email, "purpose": "login"},
        )
        code_login = self._request(
            "/nexus/oem/login/code",
            {"email": email, "code": self.sent[-1][1]},
        )
        self.assertTrue(code_login["token"])

        self._request(
            "/nexus/oem/email/request-code",
            {"email": email, "purpose": "reset"},
        )
        reset = self._request(
            "/nexus/oem/password/reset",
            {
                "email": email,
                "code": self.sent[-1][1],
                "password": "changed123",
            },
        )
        self.assertTrue(reset["ok"])
        password_login = self._request(
            "/nexus/oem/login",
            {"email": email, "password": "changed123"},
        )
        self.assertTrue(password_login["token"])


if __name__ == "__main__":
    unittest.main()
