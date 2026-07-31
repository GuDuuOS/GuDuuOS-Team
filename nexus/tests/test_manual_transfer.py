"""Nexus 企业转账人工入账、加密凭证、AI 识别和资金统计回归测试。

测试使用临时 SQLite 与伪造图片魔数，不接触生产 PostgreSQL、真实银行凭证或模型 API。
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from nexus import db, manual_transfer, oem, pay
from nexus.db import NexusManualTransfer
from nexus.fleet import FleetError


class ManualTransferTest(unittest.TestCase):
    """覆盖“必传凭证→加密落库→人工实收统计→专用订单号”主链路。"""

    def setUp(self) -> None:
        """每条用例使用独立数据库和加密主密钥，杜绝测试间状态串扰。"""
        self.temp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp.close()
        db.init_engine("sqlite:///" + self.temp.name)
        self.session = db.session()
        self.original_secret = os.environ.get("NEXUS_SECRET_KEY")
        self.original_ai_key = os.environ.get("NEXUS_RECEIPT_AI_KEY")
        self.original_gateway_key = os.environ.get("NEXUS_GW_OPENAI_KEY")
        os.environ["NEXUS_SECRET_KEY"] = "unit-test-nexus-secret-key-at-least-32-bytes"
        os.environ.pop("NEXUS_RECEIPT_AI_KEY", None)
        os.environ.pop("NEXUS_GW_OPENAI_KEY", None)
        self.oem_id = oem.register(
            self.session,
            "finance@example.com",
            "abc12345",
            inviter="GUDUU",
            company="付款测试企业",
            contact_name="财务",
            phone="test-contact",
        )["id"]
        # 业务层只需确认真实图片魔数；无需依赖 Pillow 解析像素，保持 Nexus 最小依赖。
        self.image = b"\x89PNG\r\n\x1a\n" + b"fake-receipt-image"

    def tearDown(self) -> None:
        """关闭会话、恢复环境并删除临时数据库。"""
        self.session.close()
        os.unlink(self.temp.name)
        self._restore("NEXUS_SECRET_KEY", self.original_secret)
        self._restore("NEXUS_RECEIPT_AI_KEY", self.original_ai_key)
        self._restore("NEXUS_GW_OPENAI_KEY", self.original_gateway_key)

    @staticmethod
    def _restore(name: str, value) -> None:
        """把单个环境变量恢复到用例运行前状态。"""
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value

    def _create(self):
        """创建一笔标准人工转账，供各用例复用。"""
        return manual_transfer.create_transfer(
            self.session,
            amount_cents=123_456,
            image_data=self.image,
            content_type="image/png",
            filename="../银行回单.png",
            oem_id=self.oem_id,
            purpose="年度授权服务",
            details={
                "payer_company": "付款测试企业",
                "payer_account": "6222000012345678",
                "payee_company": "GuDuu",
                "transaction_id": "BANK-001",
            },
            recognition={
                "amount_cents": 123_456,
                "payer_company": "付款测试企业",
                "confidence": 0.92,
            },
        )

    def test_transfer_is_encrypted_and_included_in_finance(self) -> None:
        """详情/图片不得明文落库，确认单要计入总额、笔数和统一订单列表。"""
        public = self._create()
        self.assertTrue(public["order_no"].startswith("BT"))
        self.assertEqual(public["record_type"], "manual_transfer")
        self.assertEqual(public["amount_cents"], 123_456)
        self.assertEqual(public["details"]["payer_company"], "付款测试企业")
        self.assertEqual(public["voucher_filename"], "银行回单.png")

        row = self.session.query(NexusManualTransfer).one()
        self.assertNotIn("付款测试企业".encode(), bytes(row.encrypted_details))
        self.assertNotIn(self.image, bytes(row.encrypted_voucher))
        filename, content_type, restored = manual_transfer.voucher(
            self.session, row.id
        )
        self.assertEqual((filename, content_type, restored), (
            "银行回单.png", "image/png", self.image
        ))

        summary = pay.finance_summary(self.session)
        self.assertEqual(summary["paid_revenue_cents"], 123_456)
        self.assertEqual(summary["paid_revenue_30d_cents"], 123_456)
        self.assertEqual(summary["paid_order_count"], 1)
        self.assertEqual(summary["manual_transfer_revenue_cents"], 123_456)
        self.assertEqual(summary["manual_transfer_count"], 1)
        self.assertEqual(summary["online_paid_revenue_cents"], 0)
        self.assertEqual(pay.list_orders(self.session)[0]["channel"], "corporate_transfer")

    def test_duplicate_voucher_is_rejected(self) -> None:
        """同一图片不能重复登记，避免刷新/误点造成营收翻倍。"""
        self._create()
        with self.assertRaises(FleetError) as raised:
            self._create()
        self.assertEqual(raised.exception.code, "NEXUS_TRANSFER_DUPLICATE")

    def test_voucher_is_required_and_must_be_real_image_type(self) -> None:
        """空文件、伪装图片和错误 Base64 都必须在入库前被拒绝。"""
        with self.assertRaises(FleetError):
            manual_transfer.decode_image("", "image/png")
        with self.assertRaises(FleetError):
            manual_transfer.decode_image("not-base64", "image/png")
        with self.assertRaises(FleetError):
            manual_transfer.create_transfer(
                self.session,
                amount_cents=100,
                image_data=b"<script>alert(1)</script>",
                content_type="image/png",
                filename="fake.png",
            )

    def test_ai_unconfigured_does_not_block_manual_entry(self) -> None:
        """没有视觉模型 key 时只禁用识别，不影响人工凭证保存。"""
        self.assertFalse(manual_transfer.ai_status()["configured"])
        with self.assertRaises(FleetError) as raised:
            manual_transfer.recognize_voucher(self.image, "image/png")
        self.assertEqual(raised.exception.code, "NEXUS_RECEIPT_AI_UNAVAILABLE")
        self.assertEqual(self._create()["status"], "paid")

    @patch("nexus.manual_transfer.requests.post")
    def test_ai_recognition_uses_image_and_strict_json(self, request_post) -> None:
        """视觉请求须显式禁用存储并用严格 Schema，返回值经类型/长度清洗。"""
        os.environ["NEXUS_RECEIPT_AI_KEY"] = "test-ai-key"
        response = Mock(status_code=200)
        response.json.return_value = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": (
                                '{"amount_cents":123456,"confidence":0.91,'
                                '"payer_company":"付款测试企业",'
                                '"payer_account":"1234","payee_company":"GuDuu",'
                                '"payee_account":"5678","bank_name":"测试银行",'
                                '"transaction_id":"TX-1",'
                                '"transfer_time":"2026-08-01 10:00",'
                                '"currency":"CNY","note":"测试"}'
                            ),
                        }
                    ],
                }
            ]
        }
        request_post.return_value = response

        result = manual_transfer.recognize_voucher(self.image, "image/png")
        self.assertEqual(result["amount_cents"], 123_456)
        self.assertEqual(result["payer_company"], "付款测试企业")
        sent = request_post.call_args.kwargs["json"]
        self.assertIs(sent["store"], False)
        self.assertEqual(sent["text"]["format"]["type"], "json_schema")
        self.assertIs(sent["text"]["format"]["strict"], True)
        image_part = sent["input"][0]["content"][1]
        self.assertEqual(image_part["type"], "input_image")
        self.assertTrue(image_part["image_url"].startswith("data:image/png;base64,"))


if __name__ == "__main__":
    unittest.main()
