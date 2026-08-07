"""Nexus 心跳修复节点身份的回归测试。"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from cosmac import nexus_link, node_activation
from cosmac.config import CosmacConfig


class NexusIdentityHeartbeatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.previous = dict(os.environ)
        os.environ["COSMAC_NEXUS_URL"] = "https://nexus.test"
        os.environ["COSMAC_OEM_KEY"] = "CMK-AAAA-BBBB-CCCC-DDDD"
        os.environ["COSMAC_NODE_ACTIVATION_STATE_PATH"] = os.path.join(
            self.directory.name, "activation.json"
        )

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self.previous)
        self.directory.cleanup()

    @patch("cosmac.nexus_link.build_stats", return_value={})
    @patch("cosmac.nexus_link.requests.post")
    def test_successful_heartbeat_repairs_instance_identity(self, post, _stats) -> None:
        response = Mock()
        response.ok = True
        response.json.return_value = {"instance_id": 1, "balance_tokens": 123}
        post.return_value = response

        self.assertTrue(nexus_link.beat(CosmacConfig()))
        self.assertEqual(node_activation.instance_id(), 1)
        self.assertEqual(nexus_link.get_last_balance(), 123)


if __name__ == "__main__":
    unittest.main()
