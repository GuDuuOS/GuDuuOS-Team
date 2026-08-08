"""OEM 节点首次激活门禁的回归测试。"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from cosmac import node_activation
from cosmac.config import CosmacConfig


class NodeActivationTests(unittest.TestCase):
    """未激活拒绝公开入口，成功兑换后持久化放行。"""

    def setUp(self) -> None:
        """为每个用例隔离状态文件与环境。"""
        self.directory = tempfile.TemporaryDirectory()
        self.previous = dict(os.environ)
        os.environ["COSMAC_NODE_ACTIVATION_REQUIRED"] = "1"
        os.environ["COSMAC_NODE_ACTIVATION_STATE_PATH"] = os.path.join(
            self.directory.name, "activation.json"
        )
        os.environ["COSMAC_NEXUS_URL"] = "https://nexus.test"
        os.environ["COSMAC_OEM_KEY"] = "CMK-AAAA-BBBB-CCCC-DDDD"
        os.environ["COSMAC_NODE_REGION"] = "CN-BJ"

    def tearDown(self) -> None:
        """还原进程环境，避免污染其他单测。"""
        os.environ.clear()
        os.environ.update(self.previous)
        self.directory.cleanup()

    def test_pending_node_blocks_public_access(self) -> None:
        """不存在成功状态文件时，注册守卫必须保持关闭。"""
        self.assertFalse(node_activation.allows_public_access())

    def test_heartbeat_identity_can_repair_missing_activation_file(self) -> None:
        """心跳返回的受信实例号可修复旧安装器遗留的缺失状态。"""
        self.assertIsNone(node_activation.instance_id())
        self.assertEqual(node_activation.record_instance_id("2"), 2)
        self.assertEqual(node_activation.instance_id(), 2)
        mode = os.stat(os.environ["COSMAC_NODE_ACTIVATION_STATE_PATH"]).st_mode & 0o777
        self.assertEqual(mode, 0o600)

        with self.assertRaisesRegex(ValueError, "不合法"):
            node_activation.record_instance_id(True)

    def test_heartbeat_policy_is_persisted_without_losing_identity(self) -> None:
        """逐节点会员策略与实例身份共用原子状态文件且互不覆盖。"""
        node_activation.record_instance_id(7)
        self.assertFalse(node_activation.lifetime_approval_required())
        saved = node_activation.record_member_policy(
            {"lifetime_approval_required": True}
        )
        self.assertTrue(saved["lifetime_approval_required"])
        self.assertTrue(node_activation.lifetime_approval_required())
        self.assertEqual(node_activation.instance_id(), 7)

        # 后续每次心跳都会重写实例号，但不能把已收到的策略擦掉。
        node_activation.record_instance_id(7)
        self.assertTrue(node_activation.lifetime_approval_required())
        with self.assertRaisesRegex(ValueError, "不合法"):
            node_activation.record_member_policy({"lifetime_approval_required": 1})

    @patch("cosmac.node_activation.requests.post")
    def test_activation_never_returns_or_persists_raw_key(self, post) -> None:
        """服务器代办兑换成功后只保存实例号，授权码不落盘也不回浏览器。"""
        post.return_value.ok = True
        post.return_value.content = b'{}'
        post.return_value.json.return_value = {"instance_id": 42}
        result = node_activation.activate(CosmacConfig(server_name="oem.test"))
        self.assertEqual(result["instance_id"], 42)
        self.assertEqual(post.call_args.kwargs["json"]["region"], "CN-BJ")
        with open(os.environ["COSMAC_NODE_ACTIVATION_STATE_PATH"], encoding="utf-8") as handle:
            stored = handle.read()
        self.assertNotIn(os.environ["COSMAC_OEM_KEY"], stored)
        self.assertTrue(node_activation.allows_public_access())
        self.assertEqual(node_activation.instance_id(), 42)

        # 品牌权限仍需读节点号，即使存量节点暂时关闭首次激活门禁。
        os.environ["COSMAC_NODE_ACTIVATION_REQUIRED"] = "0"
        self.assertEqual(node_activation.instance_id(), 42)

    @patch("cosmac.node_activation.requests.post")
    def test_activation_without_region_stays_restricted(self, post) -> None:
        """受限态重试不能漏掉地域，否则节点会接入统计却不出现在地图。"""
        del os.environ["COSMAC_NODE_REGION"]
        with self.assertRaisesRegex(RuntimeError, "机房地域"):
            node_activation.activate(CosmacConfig(server_name="oem.test"))
        post.assert_not_called()
