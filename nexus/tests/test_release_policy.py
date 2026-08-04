"""Nexus 节点环境发布策略回归测试。

本文件只使用内存 SQLite，验证 1/2/3 默认角色、持久化以及环境互斥，
避免运营人员误把同一台机器同时配置成开发、灰度和正式节点。
"""

from __future__ import annotations

import unittest

from nexus import db, release_policy
from nexus.fleet import FleetError


class ReleasePolicyTests(unittest.TestCase):
    """发布策略必须默认安全，并拒绝会绕过灰度门禁的配置。"""

    def setUp(self) -> None:
        """为每条用例建立独立内存数据库。"""
        db.init_engine("sqlite:///:memory:")
        self.s = db.session()

    def tearDown(self) -> None:
        """关闭会话，避免数据库连接泄漏到其他测试。"""
        self.s.close()

    def test_defaults_match_confirmed_three_environments(self) -> None:
        """旧数据库没有设置行时也必须直接采用负责人确认的 1/2/3 角色。"""
        self.assertEqual(
            release_policy.get_policy(self.s),
            {
                "development_instance_ids": [1],
                "canary_instance_id": 2,
                "production_instance_ids": [3],
                "auto_canary": True,
                "require_canary_success": True,
            },
        )

    def test_policy_persists_normalized_node_ids(self) -> None:
        """节点数组要去重排序，并在提交事务后可由新会话读回。"""
        saved = release_policy.set_policy(
            self.s,
            {
                "development_instance_ids": [7, 1, 7],
                "canary_instance_id": 8,
                "production_instance_ids": [10, 9, 10],
            },
        )
        self.s.commit()
        self.assertEqual(saved["development_instance_ids"], [1, 7])
        self.assertEqual(saved["production_instance_ids"], [9, 10])
        self.assertEqual(release_policy.get_policy(self.s), saved)

    def test_same_instance_cannot_have_multiple_roles(self) -> None:
        """开发、灰度、生产环境交叉时必须由服务端拒绝。"""
        with self.assertRaises(FleetError) as overlap:
            release_policy.set_policy(
                self.s,
                {
                    "development_instance_ids": [1, 2],
                    "canary_instance_id": 2,
                },
            )
        self.assertEqual(overlap.exception.code, "NEXUS_RELEASE_POLICY_OVERLAP")

    def test_canary_is_required_when_automation_or_gate_is_enabled(self) -> None:
        """开启自动灰度或生产门禁时，不能把灰度编号清空。"""
        with self.assertRaises(FleetError) as invalid:
            release_policy.set_policy(self.s, {"canary_instance_id": 0})
        self.assertEqual(invalid.exception.code, "NEXUS_RELEASE_POLICY_INVALID")


if __name__ == "__main__":
    unittest.main()
