"""Nexus 支付配置中心回归测试：加密、脱敏、字段保留与凭据验证。

测试只使用临时 SQLite 和本地生成的 RSA 密钥；远程支付平台调用全部 mock，绝不访问
真实账号、创建订单或产生扣款。
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from nexus import db, payment_config
from nexus.db import NexusPaymentConfig
from nexus.fleet import FleetError


class PaymentConfigTest(unittest.TestCase):
    """覆盖支付配置中心最重要的安全与状态语义。"""

    def setUp(self):
        """为每个用例创建独立数据库与加密主密钥，避免污染开发数据。"""
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        db.init_engine("sqlite:///" + self._tmp.name)
        self.s = db.session()
        os.environ["NEXUS_SECRET_KEY"] = "test-master-key-0123456789-abcdef"

    def tearDown(self):
        """关闭会话并清掉测试主密钥与临时数据库。"""
        self.s.close()
        os.environ.pop("NEXUS_SECRET_KEY", None)
        os.unlink(self._tmp.name)

    @staticmethod
    def _rsa_pair():
        """生成可解析的 RSA 私钥/公钥 PEM，供支付宝和微信本地校验使用。"""
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private_pem = private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode("ascii")
        public_pem = private.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii")
        return private_pem, public_pem

    @patch("nexus.payment_config.requests.get")
    def test_stripe_is_encrypted_and_public_response_is_redacted(self, request_get):
        """Stripe Key 远程验证后只以密文入库，公开结果只能看到 configured。"""
        request_get.return_value = Mock(status_code=200)
        secret = "sk_test_abcdefghijklmnopqrstuvwxyz"
        webhook = "whsec_abcdefghijklmnopqrstuvwxyz"
        public = payment_config.save_and_verify(
            self.s,
            "stripe",
            {
                "mode": "sandbox",
                "secret_key": secret,
                "webhook_secret": webhook,
            },
        )
        row = self.s.get(NexusPaymentConfig, "stripe")
        self.assertIsNotNone(row)
        self.assertNotIn(secret.encode("utf-8"), bytes(row.encrypted_config))
        self.assertNotIn(webhook.encode("utf-8"), bytes(row.encrypted_config))
        self.assertEqual(public["verify_status"], "remote_verified")
        for field in public["fields"]:
            if field["name"] != "mode":
                self.assertEqual(field["value"], "")
                self.assertTrue(field["configured"])

    @patch("nexus.payment_config.requests.get")
    def test_blank_submission_retains_existing_secret(self, request_get):
        """管理员只改环境或重新保存时，空白密钥字段必须保留旧值而不是清空。"""
        request_get.return_value = Mock(status_code=200)
        payment_config.save_and_verify(
            self.s,
            "stripe",
            {
                "mode": "sandbox",
                "secret_key": "sk_test_keep-this-value",
                "webhook_secret": "whsec_keep-this-value",
            },
        )
        payment_config.save_and_verify(
            self.s,
            "stripe",
            {"mode": "sandbox", "secret_key": "", "webhook_secret": ""},
        )
        row = self.s.get(NexusPaymentConfig, "stripe")
        config = payment_config._decrypt(row)
        self.assertEqual(config["secret_key"], "sk_test_keep-this-value")
        self.assertEqual(config["webhook_secret"], "whsec_keep-this-value")

    def test_alipay_local_validation_is_not_transaction_ready(self):
        """支付宝格式通过只能标 local_valid，不能把 adapter_ready 误置为真。"""
        private, public = self._rsa_pair()
        result = payment_config.save_and_verify(
            self.s,
            "alipay",
            {
                "mode": "sandbox",
                "app_id": "2026000000000001",
                "private_key": private,
                "alipay_public_key": public,
            },
        )
        self.assertEqual(result["verify_status"], "local_valid")
        self.assertFalse(result["adapter_ready"])

    def test_failed_remote_verification_is_saved_for_later_retry(self):
        """网络/权限失败仍加密保存配置，管理员可稍后点重新验证而无需重填。"""
        with patch("nexus.payment_config.requests.post") as request_post:
            request_post.return_value = Mock(status_code=401)
            result = payment_config.save_and_verify(
                self.s,
                "paypal",
                {
                    "mode": "sandbox",
                    "client_id": "client-id-for-test",
                    "client_secret": "client-secret-for-test",
                    "webhook_id": "WebhookId123",
                },
            )
        self.assertEqual(result["verify_status"], "verification_failed")
        self.assertTrue(result["configured"])
        self.assertIsNotNone(self.s.get(NexusPaymentConfig, "paypal"))

    def test_missing_master_key_refuses_plaintext_fallback(self):
        """主密钥缺失时必须拒绝保存，不能为了可用性偷偷退化成明文。"""
        os.environ.pop("NEXUS_SECRET_KEY", None)
        with self.assertRaises(FleetError) as raised:
            payment_config.save_and_verify(
                self.s,
                "usdt",
                {"api_key": "test-api-key", "ipn_secret": "test-ipn-secret"},
            )
        self.assertEqual(raised.exception.code, "NEXUS_SECRET_KEY_MISSING")


if __name__ == "__main__":
    unittest.main()
