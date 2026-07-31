"""Nexus 版本发布中心回归测试。

覆盖草稿、灰度、全量、暂停、节点领取、结果上报与失败人工重试。测试使用独立
SQLite 文件，不访问 GitHub，也不会真的执行发行版升级脚本。
"""

from __future__ import annotations

import os
import tempfile
import unittest

from nexus import db, fleet, releases
from nexus.fleet import FleetError


class ReleaseTest(unittest.TestCase):
    """验证一个版本从创建到全舰队安装完成的状态机。"""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        db.init_engine("sqlite:///" + self._tmp.name)
        self.s = db.session()
        self.key_a = fleet.issue_keys(self.s)[0]["key"]
        self.key_b = fleet.issue_keys(self.s)[0]["key"]
        self.inst_a = fleet.redeem(self.s, self.key_a, "a.example.com")["instance_id"]
        self.inst_b = fleet.redeem(self.s, self.key_b, "b.example.com")["instance_id"]
        fleet.heartbeat(self.s, self.key_a, "1.6.32")
        fleet.heartbeat(self.s, self.key_b, "1.6.32")

    def tearDown(self):
        self.s.close()
        os.unlink(self._tmp.name)

    def _create(self, version: str = "1.7.0"):
        """创建一条合法草稿，减少各测试的样板参数。"""
        return releases.create_release(
            self.s,
            version=version,
            title="自动更新中心",
            notes="新增版本灰度、发布和结果监测。",
            git_ref="v" + version,
        )

    def test_create_requires_semver_and_matching_tag(self):
        """版本号和 tag 必须严格一致，且不能创建倒序版本。"""
        row = self._create()
        self.assertEqual(row["status"], "draft")
        with self.assertRaises(FleetError):
            releases.create_release(
                self.s,
                version="1.7",
                title="坏版本",
                notes="说明",
                git_ref="v1.7",
            )
        with self.assertRaises(FleetError):
            releases.create_release(
                self.s,
                version="1.7.1",
                title="tag 不匹配",
                notes="说明",
                git_ref="main",
            )
        with self.assertRaises(FleetError):
            releases.create_release(
                self.s,
                version="1.6.99",
                title="倒序",
                notes="说明",
                git_ref="v1.6.99",
            )

    def test_canary_only_assigns_selected_instance(self):
        """灰度阶段只有被选择的节点能领取版本。"""
        release_id = self._create()["id"]
        result = releases.start_canary(self.s, release_id, self.inst_a)
        self.assertEqual(result["status"], "canary")
        self.assertEqual(len(result["deployments"]), 1)
        self.assertIsNotNone(releases.check_update(self.s, self.key_a, "1.6.32"))
        self.assertIsNone(releases.check_update(self.s, self.key_b, "1.6.32"))

    def test_publish_reports_success_and_failure_then_retries(self):
        """全量创建两份任务；失败不会自重试，管理员重置后才重新出现。"""
        release_id = self._create()["id"]
        releases.publish(self.s, release_id)
        self.assertIsNotNone(releases.check_update(self.s, self.key_a, "1.6.32"))
        self.assertIsNotNone(releases.check_update(self.s, self.key_b, "1.6.32"))

        releases.report_update(
            self.s,
            raw_key=self.key_a,
            release_id=release_id,
            status="downloading",
            current_version="1.6.32",
        )
        releases.report_update(
            self.s,
            raw_key=self.key_a,
            release_id=release_id,
            status="installing",
            current_version="1.6.32",
        )
        releases.report_update(
            self.s,
            raw_key=self.key_a,
            release_id=release_id,
            status="success",
            current_version="1.7.0",
            detail="完成",
        )
        releases.report_update(
            self.s,
            raw_key=self.key_b,
            release_id=release_id,
            status="failed",
            current_version="1.6.32",
            detail="构建失败",
        )
        result = releases.get_release(self.s, release_id)
        self.assertEqual(result["counts"]["success"], 1)
        self.assertEqual(result["counts"]["failed"], 1)
        self.assertIsNone(releases.check_update(self.s, self.key_b, "1.6.32"))

        releases.retry_failed(self.s, release_id)
        self.assertIsNotNone(releases.check_update(self.s, self.key_b, "1.6.32"))

    def test_pause_hides_pending_update(self):
        """暂停后节点不能再领取尚未开始的任务，恢复发布后继续。"""
        release_id = self._create()["id"]
        releases.publish(self.s, release_id)
        releases.pause(self.s, release_id)
        self.assertIsNone(releases.check_update(self.s, self.key_a, "1.6.32"))
        releases.publish(self.s, release_id)
        self.assertIsNotNone(releases.check_update(self.s, self.key_a, "1.6.32"))

    def test_key_cannot_report_another_instances_task(self):
        """KEY 是节点边界，A 不能替 B 写安装状态。"""
        release_id = self._create()["id"]
        releases.start_canary(self.s, release_id, self.inst_b)
        with self.assertRaises(FleetError) as ctx:
            releases.report_update(
                self.s,
                raw_key=self.key_a,
                release_id=release_id,
                status="success",
                current_version="1.7.0",
            )
        self.assertEqual(ctx.exception.code, "NEXUS_UPDATE_NOT_ASSIGNED")


if __name__ == "__main__":
    unittest.main()
