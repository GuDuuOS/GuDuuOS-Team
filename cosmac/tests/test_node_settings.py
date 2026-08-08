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
    runtime_payments,
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
            "website": {
                "headline": "让团队协作更简单",
                "description": "测试官网介绍",
                "contact_email": "service@test.invalid",
                "contact_phone": "+86 10 8888 8888",
                "contact_address": "测试地址",
                "support_url": "https://support.test.invalid",
                "privacy_url": "/privacy",
                "footer_text": "测试企业 版权所有",
            },
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
        self.assertEqual(public_config()["website"]["headline"], "让团队协作更简单")
        self.assertEqual(public_config()["website"]["privacy_url"], "/privacy")
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

    def test_public_config_exposes_only_membership_policy_boolean(self) -> None:
        with mock.patch(
            "cosmac.node_activation.lifetime_approval_required", return_value=True
        ):
            policy = public_config()["member_policy"]
        self.assertEqual(policy, {"lifetime_approval_required": True})

    def test_nexus_gateway_uses_server_oem_credential_without_exposing_it(self) -> None:
        """Nexus 模式不让浏览器填 KEY，运行时才从服务器环境组装。"""
        with mock.patch.dict(
            os.environ,
            {
                "COSMAC_OEM_KEY": "CMK-server-only",
                "COSMAC_NEXUS_URL": "https://nexus.invalid",
                "ARK_BASE_URL": "https://legacy.invalid/should-not-win",
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

    def test_only_instance_three_may_use_reserved_brand(self) -> None:
        """仅官网正式节点 #3 可使用保留品牌，其他节点必须改用自有品牌。"""
        with mock.patch.dict(
            os.environ, {"COSMAC_OEM_KEY": "CMK-official"}, clear=False
        ), mock.patch(
            "cosmac.node_settings.activated_instance_id", return_value=3
        ):
            saved = save_admin_config({
                "brand": {
                    "product_name": "GuDuu OS",
                    "company_name": "中富通集团股份有限公司",
                },
                "email": {"from_name": "GuDuu OS"},
                "ai": {}, "payment": {},
            })
            self.assertTrue(saved["brand_policy"]["reserved_brand_allowed"])

        for node_id in (1, 2, 4):
            with self.subTest(node_id=node_id), mock.patch.dict(
                os.environ, {"COSMAC_OEM_KEY": "CMK-external"}, clear=False
            ), mock.patch(
                "cosmac.node_settings.activated_instance_id", return_value=node_id
            ):
                for field, value in (
                    ("product_name", "GuDuu-OS"),
                    ("company_name", "GUDUU_OS 联合实验室"),
                    ("company_name", "中富通集团股份有限公司"),
                    ("from_name", "guduu os 通知"),
                ):
                    body = {
                        "brand": {"product_name": "星海协作", "company_name": "星海科技"},
                        "email": {"from_name": "星海协作"},
                        "ai": {}, "payment": {},
                    }
                    if field == "from_name":
                        body["email"][field] = value
                    else:
                        body["brand"][field] = value
                    with self.subTest(field=field), self.assertRaisesRegex(
                        Exception, "GuDuu OS 保留品牌"
                    ):
                        save_admin_config(body)

                saved = save_admin_config({
                    "brand": {"product_name": "星海协作 OS", "company_name": "星海科技"},
                    "email": {"from_name": "星海协作"},
                    "ai": {}, "payment": {},
                })
                self.assertFalse(saved["brand_policy"]["reserved_brand_allowed"])
                self.assertEqual(saved["brand"]["product_name"], "星海协作 OS")

    def test_external_oem_legacy_default_brand_is_neutralized(self) -> None:
        """外部 OEM 未配置或留有历史默认值时，不得对外显示官方品牌。"""
        with mock.patch.dict(
            os.environ, {"COSMAC_OEM_KEY": "CMK-external"}, clear=False
        ), mock.patch(
            "cosmac.node_settings.activated_instance_id", return_value=9
        ):
            admin = admin_config()
            public = public_config()
            self.assertEqual(admin["brand"]["product_name"], "")
            self.assertTrue(admin["brand_policy"]["requires_custom_brand"])
            self.assertEqual(public["brand"]["product_name"], "OEM 协作平台")
            self.assertFalse(public["setup_completed"])

    def test_external_oem_cannot_use_reserved_brand_in_website_copy(self) -> None:
        """官网公开文案与产品名称执行同一保留品牌门禁。"""
        with mock.patch.dict(
            os.environ, {"COSMAC_OEM_KEY": "CMK-external"}, clear=False
        ), mock.patch(
            "cosmac.node_settings.activated_instance_id", return_value=9
        ):
            for field in ("headline", "description", "footer_text"):
                website = {"headline": "企业智能协作", "description": "团队平台"}
                website[field] = "由 GuDuu-OS 提供"
                with self.subTest(field=field), self.assertRaisesRegex(
                    Exception, "GuDuu OS 保留品牌"
                ):
                    save_admin_config({
                        "brand": {"product_name": "星海协作"},
                        "website": website,
                        "email": {}, "ai": {}, "payment": {},
                    })

    def test_oem_completed_setup_requires_footer_intro_and_contacts(self) -> None:
        """OEM 完成首次部署前必须提供官网底部介绍与企业联系方式。"""
        with mock.patch.dict(
            os.environ, {"COSMAC_OEM_KEY": "CMK-external"}, clear=False
        ), mock.patch(
            "cosmac.node_settings.activated_instance_id", return_value=9
        ):
            with self.assertRaisesRegex(
                Exception, "企业/组织名称.*官网介绍.*联系邮箱.*联系电话.*联系地址"
            ):
                save_admin_config({
                    "brand": {"product_name": "星海协作"},
                    "website": {"headline": "企业智能协作"},
                    "email": {}, "ai": {}, "payment": {},
                    "setup_completed": True,
                })

            saved = save_admin_config({
                "brand": {
                    "product_name": "星海协作",
                    "company_name": "星海科技有限公司",
                },
                "website": {
                    "headline": "企业智能协作",
                    "description": "星海协作产品与服务介绍。",
                    "contact_email": "service@xinghai.example",
                    "contact_phone": "+86 10 8888 8888",
                    "contact_address": "北京市测试地址 1 号",
                },
                "email": {}, "ai": {}, "payment": {},
                "setup_completed": True,
            })
            self.assertTrue(saved["setup_completed"])
            self.assertEqual(
                saved["website"]["contact_email"], "service@xinghai.example"
            )

    def test_website_links_reject_unsafe_schemes(self) -> None:
        with self.assertRaisesRegex(Exception, "HTTPS"):
            save_admin_config({
                "brand": {"product_name": "测试 OS"},
                "website": {
                    "headline": "测试官网",
                    "support_url": "javascript:alert(1)",
                },
                "email": {}, "ai": {}, "payment": {},
            })

    def test_oem_without_saved_settings_ignores_legacy_business_env(self) -> None:
        """官方节点首次进向导前，旧 SMTP/模型 env 不得成为隐形第二真值源。"""
        from cosmac.registration import _smtp_conf

        with mock.patch.dict(
            os.environ,
            {
                "COSMAC_OEM_KEY": "CMK-server-only",
                "COSMAC_NEXUS_URL": "https://nexus.invalid",
                "COSMAC_LLM_PROVIDER": "openai",
                "OPENAI_API_KEY": "legacy-ai-key",
                "COSMAC_SMTP_HOST": "legacy.invalid",
                "COSMAC_SMTP_USER": "legacy-user",
                "COSMAC_SMTP_PASSWORD": "legacy-password",
                "COSMAC_SMTP_FROM": "legacy@example.com",
            },
            clear=False,
        ):
            admin = admin_config()
            self.assertEqual(admin["ai"]["connection_mode"], "nexus")
            self.assertEqual(admin["ai"]["provider"], "deepseek")
            self.assertFalse(admin["ai"]["api_key_configured"])
            self.assertFalse(admin["email"]["password_configured"])
            self.assertEqual(runtime_ai()["provider"], "echo")
            self.assertIsNone(_smtp_conf())

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

    def test_alipay_and_wechat_can_be_configured_together_without_secret_echo(self) -> None:
        saved = save_admin_config({
            "brand": {"product_name": "测试 OS"},
            "email": {},
            "ai": {},
            "payment": {
                "alipay": {
                    "enabled": True,
                    "mode": "sandbox",
                    "app_id": "2021000000000000",
                    "notify_url": "https://pay.test.invalid/cosmac/pay/callback/alipay",
                    "private_key": "alipay-private-secret",
                    "alipay_public_key": "alipay-public-secret",
                },
                "wechat": {
                    "enabled": True,
                    "mode": "live",
                    "mch_id": "1900000001",
                    "app_id": "wx-test-app",
                    "merchant_serial_no": "SERIAL-1",
                    "platform_public_key_id": "PUB_KEY_ID_TEST",
                    "notify_url": "https://pay.test.invalid/cosmac/pay/callback/wechat",
                    "api_v3_key": "12345678901234567890123456789012",
                    "merchant_private_key": "wechat-merchant-private",
                    "platform_public_key": "wechat-platform-public",
                },
            },
        })
        self.assertTrue(saved["payment"]["alipay"]["enabled"])
        self.assertTrue(saved["payment"]["wechat"]["enabled"])
        self.assertTrue(saved["payment"]["alipay"]["private_key_configured"])
        self.assertTrue(saved["payment"]["wechat"]["api_v3_key_configured"])
        self.assertNotIn("alipay-private-secret", str(saved))
        self.assertNotIn("wechat-merchant-private", str(saved))
        runtime = runtime_payments()
        self.assertEqual(runtime["alipay"]["private_key"], "alipay-private-secret")
        self.assertEqual(runtime["wechat"]["api_v3_key"], "12345678901234567890123456789012")
        self.assertEqual(runtime["wechat"]["platform_public_key"], "wechat-platform-public")

        # 系统设置再次保存时留空密钥必须保持原值，不能要求客户重复粘贴。
        payment = saved["payment"]
        payment["alipay"]["private_key"] = ""
        payment["alipay"]["alipay_public_key"] = ""
        payment["wechat"]["api_v3_key"] = ""
        payment["wechat"]["merchant_private_key"] = ""
        payment["wechat"]["platform_public_key"] = ""
        save_admin_config({
            "brand": {"product_name": "测试 OS"},
            "email": {}, "ai": {}, "payment": payment,
        })
        self.assertEqual(
            runtime_payments()["wechat"]["merchant_private_key"],
            "wechat-merchant-private",
        )

    def test_enabled_payment_channels_require_complete_credentials(self) -> None:
        with self.assertRaisesRegex(Exception, "支付宝"):
            save_admin_config({
                "brand": {"product_name": "测试 OS"},
                "email": {}, "ai": {},
                "payment": {"alipay": {"enabled": True}},
            })
        with self.assertRaisesRegex(Exception, "32 字节"):
            save_admin_config({
                "brand": {"product_name": "测试 OS"},
                "email": {}, "ai": {},
                "payment": {
                    "wechat": {
                        "enabled": True, "mch_id": "m", "app_id": "a",
                        "merchant_serial_no": "s", "platform_public_key_id": "p",
                        "notify_url": "https://pay.test.invalid/cosmac/pay/callback/wechat",
                        "api_v3_key": "too-short",
                        "merchant_private_key": "private",
                        "platform_public_key": "public",
                    },
                },
            })


if __name__ == "__main__":
    unittest.main()
