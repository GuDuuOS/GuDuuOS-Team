"""节点首次配置向导安全存储回归测试。"""

import os
import unittest

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


if __name__ == "__main__":
    unittest.main()
