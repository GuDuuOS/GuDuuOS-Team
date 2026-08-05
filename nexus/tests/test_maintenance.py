"""Nexus 周期维护与数据保留策略回归测试。"""

from __future__ import annotations

import unittest

from nexus import db, maintenance
from nexus.db import (
    NexusAdminRecoveryCode,
    NexusAdminSession,
    NexusGatewayDebitOutbox,
    NexusHeartbeat,
    NexusRequestLatencyBucket,
    NexusRequestStat,
)


class MaintenanceTests(unittest.TestCase):
    """验证过期数据被删除，待补偿账务和新数据不受影响。"""

    def setUp(self) -> None:
        """每条用例使用独立内存库。"""
        db.init_engine("sqlite:///:memory:")
        self.s = db.session()

    def tearDown(self) -> None:
        """关闭测试会话。"""
        self.s.close()

    def test_cleanup_keeps_pending_money_and_recent_runtime_data(self) -> None:
        """账务 pending 永不删，新心跳保留，旧鉴权与观测数据清理。"""
        now = 2_000_000_000_000
        day = 24 * 60 * 60 * 1000
        self.s.add_all(
            [
                NexusAdminSession(
                    token_hash="a" * 64,
                    admin_id=1,
                    created_ts=now - day,
                    expires_ts=now - 1,
                ),
                NexusAdminRecoveryCode(
                    code_hash="b" * 64,
                    created_ts=now - 10 * day,
                    expires_ts=now - 8 * day,
                ),
                NexusHeartbeat(instance_id=1, ts=now - 100 * day, version="old"),
                NexusHeartbeat(instance_id=1, ts=now - day, version="new"),
                NexusRequestStat(
                    instance_id=1,
                    minute_ts=now - 200 * day,
                    ok_count=1,
                    fail_count=0,
                ),
                NexusRequestLatencyBucket(
                    instance_id=1,
                    minute_ts=now - 200 * day,
                    upper_ms=500,
                    count=1,
                ),
                NexusGatewayDebitOutbox(
                    request_id="gwd_pending",
                    instance_id=1,
                    tokens=10,
                    status="pending",
                    created_ts=now - 100 * day,
                    updated_ts=now - 100 * day,
                ),
                NexusGatewayDebitOutbox(
                    request_id="gwd_applied_old",
                    instance_id=1,
                    tokens=10,
                    status="applied",
                    created_ts=now - 100 * day,
                    updated_ts=now - 40 * day,
                    applied_ts=now - 40 * day,
                ),
            ]
        )
        self.s.commit()
        counts = maintenance.cleanup(self.s, now_ms=now)
        self.s.commit()
        self.assertEqual(counts["admin_sessions"], 1)
        self.assertEqual(counts["heartbeats"], 1)
        self.assertEqual(counts["request_stats"], 1)
        self.assertEqual(counts["request_latency_buckets"], 1)
        self.assertIsNotNone(
            self.s.get(NexusGatewayDebitOutbox, "gwd_pending")
        )
        self.assertIsNone(
            self.s.get(NexusGatewayDebitOutbox, "gwd_applied_old")
        )
        remaining_heartbeats = self.s.query(NexusHeartbeat).all()
        self.assertEqual([row.version for row in remaining_heartbeats], ["new"])


if __name__ == "__main__":
    unittest.main()
