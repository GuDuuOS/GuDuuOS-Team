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

    def tearDown(self) -> None:
        """还原进程环境，避免污染其他单测。"""
        os.environ.clear()
        os.environ.update(self.previous)
        self.directory.cleanup()

    def test_pending_node_blocks_public_access(self) -> None:
        """不存在成功状态文件时，注册守卫必须保持关闭。"""
        self.assertFalse(node_activation.allows_public_access())

    @patch("cosmac.node_activation.requests.post")
    def test_activation_never_returns_or_persists_raw_key(self, post) -> None:
        """服务器代办兑换成功后只保存实例号，授权码不落盘也不回浏览器。"""
        post.return_value.ok = True
        post.return_value.content = b'{}'
        post.return_value.json.return_value = {"instance_id": 42}
        result = node_activation.activate(CosmacConfig(server_name="oem.test"))
        self.assertEqual(result["instance_id"], 42)
        with open(os.environ["COSMAC_NODE_ACTIVATION_STATE_PATH"], encoding="utf-8") as handle:
            stored = handle.read()
        self.assertNotIn(os.environ["COSMAC_OEM_KEY"], stored)
        self.assertTrue(node_activation.allows_public_access())
