"""节点首次配置向导安全存储回归测试。"""

import os
import unittest
from unittest import mock

from cosmac.db import init_engine
from cosmac.node_settings import (
    admin_config,
    public_config,
    runtime_ai,
    runtime_email,
    save_admin_config,
)


class NodeSettingsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.old_secret = os.environ.get("COSMAC_NODE_SETTINGS_SECRET")
        os.environ["COSMAC_NODE_SETTINGS_SECRET"] = (
            "unit-test-node-settings-secret-at-least-32-bytes"
        )
        init_engine("sqlite://")

    def tearDown(self) -> None:
        if self.old_secret is None:
            os.environ.pop("COSMAC_NODE_SETTINGS_SECRET", None)
        else:
            os.environ["COSMAC_NODE_SETTINGS_SECRET"] = self.old_secret

    def test_secret_never_returns_from_public_or_admin_response(self) -> None:
        saved = save_admin_config({
            "brand": {"product_name": "测试 OS", "company_name": "测试企业"},
            "email": {
                "host": "smtp.test.invalid", "port": 587, "user": "mailer",
                "from_address": "mailer@test.invalid", "security": "starttls",
                "password": "smtp-secret",
            },
            "ai": {
                "provider": "openai", "model": "gpt-test",
                "base_url": "https://api.test.invalid/v1", "api_key": "ai-secret",
            },
            "payment": {
                "provider": "stripe", "mode": "sandbox", "merchant_id": "merchant",
                "secret_key": "pay-secret", "webhook_secret": "webhook-secret",
            },
            "setup_completed": True,
        })
        self.assertTrue(saved["email"]["password_configured"])
        self.assertTrue(saved["ai"]["api_key_configured"])
        self.assertFalse(saved["payment"]["adapter_ready"])
        self.assertNotIn("ai-secret", str(saved))
        self.assertNotIn("smtp-secret", str(public_config()))
        self.assertEqual(runtime_ai()["api_key"], "ai-secret")
        self.assertEqual(runtime_email()["password"], "smtp-secret")

    def test_blank_secret_keeps_existing_value(self) -> None:
        save_admin_config({
            "brand": {"product_name": "测试 OS"},
            "email": {"password": "keep-me"},
            "ai": {}, "payment": {},
        })
        save_admin_config({
            "brand": {"product_name": "测试 OS 2"},
            "email": {"password": ""},
            "ai": {}, "payment": {},
        })
        self.assertEqual(runtime_email()["password"], "keep-me")
        self.assertEqual(admin_config()["brand"]["product_name"], "测试 OS 2")

    def test_nexus_gateway_uses_server_oem_credential_without_exposing_it(self) -> None:
        """Nexus 模式不让浏览器填 KEY，运行时才从服务器环境组装。"""
        with mock.patch.dict(
            os.environ,
            {
                "COSMAC_OEM_KEY": "CMK-server-only",
                "ARK_BASE_URL": "https://nexus.invalid/gw/ark",
            },
            clear=False,
        ):
            saved = save_admin_config({
                "brand": {"product_name": "测试 OS"},
                "email": {},
                "ai": {
                    "connection_mode": "nexus",
                    "provider": "deepseek",
                    "model": "deepseek-test",
                },
                "payment": {},
            })
            runtime = runtime_ai()
            self.assertEqual(runtime["api_key"], "CMK-server-only")
            self.assertEqual(runtime["base_url"], "https://nexus.invalid/gw/ark")
            self.assertNotIn("CMK-server-only", str(saved))

    def test_saved_blank_smtp_does_not_fall_back_to_old_environment(self) -> None:
        """管理员网页明确留空 SMTP 后，旧 .env 不得悄悄重新启用。"""
        from cosmac.registration import _smtp_conf

        with mock.patch.dict(
            os.environ,
            {
                "COSMAC_SMTP_HOST": "legacy.invalid",
                "COSMAC_SMTP_USER": "legacy-user",
                "COSMAC_SMTP_PASSWORD": "legacy-password",
                "COSMAC_SMTP_FROM": "legacy@example.com",
            },
            clear=False,
        ):
            save_admin_config({
                "brand": {"product_name": "测试 OS"},
                "email": {}, "ai": {}, "payment": {},
            })
            self.assertIsNone(_smtp_conf())


if __name__ == "__main__":
    unittest.main()
