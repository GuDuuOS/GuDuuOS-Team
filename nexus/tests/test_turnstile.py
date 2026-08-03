"""Nexus OEM Turnstile 服务端校验回归测试。

所有 Siteverify 响应均由本地替身返回，不访问 Cloudflare；重点验证关闭兼容、公开配置、
token 必填、hostname/action 隔离以及上游不可用时 fail closed。
"""

from __future__ import annotations

import json
import os
import unittest
from typing import Any, Dict
from unittest.mock import patch
from urllib.error import URLError

from nexus import turnstile
from nexus.fleet import FleetError


class _FakeResponse:
    """实现 ``urlopen`` 上下文协议的最小 JSON 响应替身。"""

    def __init__(self, payload: Dict[str, Any]) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        """返回模拟的 Cloudflare JSON 响应。"""
        return self._body


class NexusTurnstileTests(unittest.TestCase):
    """逐条验证 Nexus 独立小组件的服务端安全边界。"""

    _ENV_KEYS = (
        "NEXUS_TURNSTILE_SITE_KEY",
        "NEXUS_TURNSTILE_SECRET_KEY",
        "NEXUS_TURNSTILE_HOSTNAME",
    )

    def setUp(self) -> None:
        """保存环境并从明确关闭状态开始，避免开发机配置污染测试。"""
        self._old_env = {key: os.environ.get(key) for key in self._ENV_KEYS}
        for key in self._ENV_KEYS:
            os.environ.pop(key, None)

    def tearDown(self) -> None:
        """恢复进程环境。"""
        for key, value in self._old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _enable(self) -> None:
        """写入仅供测试的完整 Nexus 小组件配置。"""
        os.environ.update(
            {
                "NEXUS_TURNSTILE_SITE_KEY": "site-key-for-test",
                "NEXUS_TURNSTILE_SECRET_KEY": "secret-key-for-test",
                "NEXUS_TURNSTILE_HOSTNAME": "dev-nexus.guduu.co",
            }
        )

    def test_incomplete_config_stays_disabled_and_compatible(self) -> None:
        """配置不完整时不显示组件，也不阻断原有验证码流程。"""
        os.environ["NEXUS_TURNSTILE_SITE_KEY"] = "site-only"
        self.assertFalse(turnstile.enabled())
        self.assertEqual(
            turnstile.public_config(), {"enabled": False, "site_key": ""}
        )
        self.assertTrue(turnstile.verify("", "register", "203.0.113.8"))

    def test_enabled_config_exposes_only_site_key(self) -> None:
        """公开配置只能出现 site key，不能出现 secret 或预期域名。"""
        self._enable()
        self.assertTrue(turnstile.enabled())
        public = turnstile.public_config()
        self.assertEqual(public, {"enabled": True, "site_key": "site-key-for-test"})
        self.assertNotIn("secret_key", public)
        self.assertNotIn("hostname", public)

    def test_missing_token_is_rejected_before_network(self) -> None:
        """功能启用后空 token 必须直接拒绝，不能默默降级。"""
        self._enable()
        with patch("nexus.turnstile.urlopen") as opened:
            with self.assertRaises(FleetError) as raised:
                turnstile.verify("", "register", "203.0.113.8")
        self.assertEqual(raised.exception.code, "NEXUS_TURNSTILE_REQUIRED")
        opened.assert_not_called()

    def test_success_requires_matching_hostname_and_action(self) -> None:
        """只有 success、hostname 与当前用途 action 三项都吻合才放行。"""
        self._enable()
        payload = {
            "success": True,
            "hostname": "dev-nexus.guduu.co",
            "action": "oem_register_code",
        }
        with patch(
            "nexus.turnstile.urlopen", return_value=_FakeResponse(payload)
        ) as opened:
            self.assertTrue(
                turnstile.verify("browser-token", "register", "203.0.113.8")
            )
        request = opened.call_args.args[0]
        body = request.data.decode("utf-8")
        self.assertIn("response=browser-token", body)
        self.assertIn("remoteip=203.0.113.8", body)

        for invalid in (
            {**payload, "hostname": "dev-os.guduu.co"},
            {**payload, "action": "oem_reset_code"},
            {**payload, "success": False},
        ):
            with patch(
                "nexus.turnstile.urlopen", return_value=_FakeResponse(invalid)
            ):
                with self.assertRaises(FleetError) as raised:
                    turnstile.verify("browser-token", "register")
            self.assertEqual(raised.exception.code, "NEXUS_TURNSTILE_FAILED")

    def test_siteverify_outage_fails_closed(self) -> None:
        """已启用后 Cloudflare 不可达必须停止发信，不能形成绕过窗口。"""
        self._enable()
        with patch(
            "nexus.turnstile.urlopen", side_effect=URLError("offline")
        ):
            with self.assertRaises(FleetError) as raised:
                turnstile.verify("browser-token", "reset")
        self.assertEqual(raised.exception.code, "NEXUS_TURNSTILE_UNAVAILABLE")
        self.assertEqual(raised.exception.http_status, 503)


if __name__ == "__main__":
    unittest.main()
