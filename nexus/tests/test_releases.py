"""Nexus 版本发布中心回归测试。

覆盖未发布、灰度、全量、历史列表、版本回撤、暂停、节点领取、结果上报与失败人工
重试。测试使用独立 SQLite 文件，不访问 GitHub，也不会真的执行发行版升级脚本。
"""

from __future__ import annotations

import os
import hashlib
import hmac
import tempfile
import time
import unittest
from pathlib import Path

from nexus import db, fleet, release_artifacts, release_policy, releases
from nexus.db import NexusKeyClaim
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
        # 旧状态机测试需要两台节点都作为正式目标；自动灰度的
        # 1/2/3 真实策略由下面独立用例覆盖，避免改变旧回归语义。
        release_policy.set_policy(
            self.s,
            {
                "development_instance_ids": [],
                "canary_instance_id": 0,
                "production_instance_ids": [self.inst_a, self.inst_b],
                "auto_canary": False,
                "require_canary_success": False,
            },
        )

    def tearDown(self):
        self.s.close()
        os.unlink(self._tmp.name)

    def _create(self, version: str = "1.7.0", target: str = "node"):
        """创建一条合法草稿，减少各测试的样板参数。"""
        return releases.create_release(
            self.s,
            version=version,
            title="自动更新中心",
            notes="新增版本灰度、发布和结果监测。",
            git_ref="v" + version,
            target=target,
        )

    def _register_manifest(self, version: str = "1.7.0"):
        """登记一份测试用不可变镜像清单，不经过 HTTP/HMAC 层。"""
        return release_artifacts.register_manifest(
            self.s,
            {
                "version": version,
                "git_ref": "v" + version,
                "source_commit": "a" * 40,
                "bot_image": "ghcr.io/guduuos/guduu-os-bot@sha256:" + "b" * 64,
                "web_image": "ghcr.io/guduuos/guduu-os-web@sha256:" + "c" * 64,
                "platforms": "linux/amd64,linux/arm64",
            },
        )

    def test_container_release_freezes_manifest_and_check_returns_digests(self):
        """节点 Docker 发布必须冻结摘要，并把完整摘要下发给自己的更新代理。"""
        self._register_manifest()
        release = releases.create_release(
            self.s,
            version="1.7.0",
            title="镜像发布",
            notes="按不可变摘要安装。",
            git_ref="v1.7.0",
            target="node",
            delivery_mode="container",
        )
        self.assertEqual(release["artifact"]["mode"], "container")
        self.assertTrue(release["artifact"]["bot_image"].endswith("b" * 64))
        self.assertTrue(
            release["artifact"]["bot_mirror_image"].startswith(
                "registry.guduu.co/guduuos/"
            )
        )
        self.assertTrue(
            release["artifact"]["bot_dockerhub_image"].startswith(
                "docker.io/guduu/"
            )
        )
        releases.publish(self.s, release["id"])
        update = releases.check_update(self.s, self.key_a, "1.6.32")
        self.assertIsNotNone(update)
        self.assertEqual(update["artifact"]["mode"], "container")
        self.assertTrue(update["artifact"]["web_image"].endswith("c" * 64))
        self.assertEqual(
            update["artifact"]["web_mirror_image"].rsplit("@", 1)[-1],
            update["artifact"]["web_image"].rsplit("@", 1)[-1],
        )
        self.assertEqual(
            update["artifact"]["web_dockerhub_image"].rsplit("@", 1)[-1],
            update["artifact"]["web_image"].rsplit("@", 1)[-1],
        )

    def test_approved_key_can_fetch_first_install_artifact(self):
        """首次安装可在兑换前按审批域名获取正式镜像，但不能换域名复用。"""
        raw_key = fleet.issue_keys(self.s)[0]["key"]
        key = fleet._key_by_plain(self.s, raw_key)
        self.s.add(
            db.NexusKeyBinding(
                key_id=key.id,
                approved_domain="new-node.example.com",
            )
        )
        self._register_manifest()
        release = releases.create_release(
            self.s,
            version="1.7.0",
            title="首次镜像安装",
            notes="只下发精确摘要。",
            git_ref="v1.7.0",
            target="node",
            delivery_mode="container",
        )
        releases.publish(self.s, release["id"])
        result = releases.install_artifact(
            self.s, raw_key, "NEW-NODE.EXAMPLE.COM."
        )
        self.assertEqual(result["version"], "1.7.0")
        self.assertEqual(result["artifact"]["mode"], "container")
        with self.assertRaises(FleetError) as mismatch:
            releases.install_artifact(self.s, raw_key, "other.example.com")
        self.assertEqual(mismatch.exception.code, "NEXUS_DOMAIN_MISMATCH")

        # 冻结功能上线前已兑换的历史 KEY 只允许原实例同域重装。
        self._register_manifest("1.7.1")
        historical_release = releases.create_release(
            self.s,
            version="1.7.1",
            title="历史节点兼容",
            notes="同域重装。",
            git_ref="v1.7.1",
            target="node",
            delivery_mode="container",
        )
        releases.publish(self.s, historical_release["id"])
        historical_key = fleet.issue_keys(self.s)[0]["key"]
        historical_id = fleet.redeem(
            self.s, historical_key, "historical.example.com"
        )["instance_id"]
        historical_row = fleet._key_by_plain(self.s, historical_key)
        self.s.delete(self.s.get(db.NexusKeyBinding, historical_row.id))
        self.s.flush()
        self.assertEqual(historical_row.instance_id, historical_id)
        self.assertEqual(
            releases.install_artifact(
                self.s, historical_key, "historical.example.com"
            )["version"],
            "1.7.1",
        )
        with self.assertRaises(FleetError):
            releases.install_artifact(self.s, historical_key, "moved.example.com")

    def test_canary_node_reinstall_receives_its_assigned_artifact(self):
        """灰度节点清空重装时仍安装已分配候选版，其他 OEM 不得越权取得。"""
        self._register_manifest("1.7.0")
        stable = releases.create_release(
            self.s,
            version="1.7.0",
            title="当前正式版",
            notes="首次安装的稳定基线。",
            git_ref="v1.7.0",
            target="node",
            delivery_mode="container",
        )
        releases.publish(self.s, stable["id"])

        self._register_manifest("1.8.0")
        candidate = releases.create_release(
            self.s,
            version="1.8.0",
            title="一键重装候选版",
            notes="只分配给公司灰度节点。",
            git_ref="v1.8.0",
            target="node",
            delivery_mode="container",
        )
        release_policy.set_policy(
            self.s,
            {
                "development_instance_ids": [self.inst_a],
                "canary_instance_id": self.inst_b,
                "production_instance_ids": [],
                "auto_canary": False,
                "require_canary_success": True,
            },
        )
        releases.start_canary(self.s, candidate["id"], self.inst_b)

        assigned = releases.install_artifact(self.s, self.key_b, "b.example.com")
        self.assertEqual(assigned["version"], "1.8.0")
        self.assertEqual(assigned["source"], "assigned")

        new_key = fleet.issue_keys(self.s)[0]["key"]
        new_key_row = fleet._key_by_plain(self.s, new_key)
        self.s.add(
            db.NexusKeyBinding(
                key_id=new_key_row.id,
                approved_domain="new-oem.example.com",
            )
        )
        ordinary = releases.install_artifact(
            self.s, new_key, "new-oem.example.com"
        )
        self.assertEqual(ordinary["version"], "1.7.0")
        self.assertEqual(ordinary["source"], "published")

        deployment = self.s.get(
            db.NexusReleaseDeployment,
            {"release_id": candidate["id"], "instance_id": self.inst_b},
        )
        deployment.status = "failed"
        retry_blocked = releases.install_artifact(
            self.s, self.key_b, "b.example.com"
        )
        self.assertEqual(retry_blocked["version"], "1.7.0")

    def test_verified_canary_can_become_new_install_baseline(self):
        """新装基线必须灰度成功，且不会向正式节点创建任务。"""
        self._register_manifest("1.7.0")
        stable = releases.create_release(
            self.s,
            version="1.7.0",
            title="已发布稳定版",
            notes="新装回退基线。",
            git_ref="v1.7.0",
            target="node",
            delivery_mode="container",
        )
        releases.publish(self.s, stable["id"])

        self._register_manifest("1.8.0")
        candidate = releases.create_release(
            self.s,
            version="1.8.0",
            title="已验收候选版",
            notes="不给正式节点创建任务。",
            git_ref="v1.8.0",
            target="node",
            delivery_mode="container",
        )
        release_policy.set_policy(
            self.s,
            {
                "development_instance_ids": [self.inst_a],
                "canary_instance_id": self.inst_b,
                "production_instance_ids": [],
                "auto_canary": False,
                "require_canary_success": True,
            },
        )
        releases.start_canary(self.s, candidate["id"], self.inst_b)
        with self.assertRaises(FleetError) as not_verified:
            releases.set_install_baseline(self.s, candidate["id"])
        self.assertEqual(
            not_verified.exception.code, "NEXUS_INSTALL_BASELINE_NOT_VERIFIED"
        )

        deployment = self.s.get(
            db.NexusReleaseDeployment,
            {"release_id": candidate["id"], "instance_id": self.inst_b},
        )
        deployment.status = "success"
        releases.set_install_baseline(self.s, candidate["id"])
        self.assertEqual(
            release_policy.get_policy(self.s)["install_baseline_release_id"],
            candidate["id"],
        )

        new_key = fleet.issue_keys(self.s)[0]["key"]
        key_row = fleet._key_by_plain(self.s, new_key)
        self.s.add(
            db.NexusKeyBinding(
                key_id=key_row.id,
                approved_domain="fresh.example.com",
            )
        )
        artifact = releases.install_artifact(
            self.s, new_key, "fresh.example.com"
        )
        self.assertEqual(artifact["version"], "1.8.0")
        self.assertEqual(artifact["source"], "baseline")

        releases.pause(self.s, candidate["id"])
        self.assertEqual(
            release_policy.get_policy(self.s)["install_baseline_release_id"], 0
        )
        fallback = releases.install_artifact(
            self.s, new_key, "fresh.example.com"
        )
        self.assertEqual(fallback["version"], "1.7.0")
        self.assertEqual(fallback["source"], "published")

    def test_ci_manifest_creates_one_unpublished_container_draft(self):
        """CI 登记镜像后必须自动出现一条未发布节点草稿。"""
        self._register_manifest()
        first = releases.ensure_ci_release_draft(
            self.s,
            version="1.7.0",
            title="自动构建已完成",
            notes="镜像已固定，等待超管灰度。",
        )
        second = releases.ensure_ci_release_draft(
            self.s,
            version="1.7.0",
            title="重复回调不应覆盖",
            notes="这段内容不应被写入。",
        )
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["status"], "draft")
        self.assertEqual(second["target"], "node")
        self.assertEqual(second["title"], "自动构建已完成")
        self.assertEqual(second["artifact"]["mode"], "container")

    def test_ci_manifest_runs_development_before_canary_and_production(self):
        """CI 先推开发；开发成功自动通知灰度，灰度成功后才能人工发生产。"""
        key_c = fleet.issue_keys(self.s)[0]["key"]
        inst_c = fleet.redeem(self.s, key_c, "production.example.com")[
            "instance_id"
        ]
        fleet.heartbeat(self.s, key_c, "1.6.32")
        release_policy.set_policy(
            self.s,
            {
                "development_instance_ids": [self.inst_a],
                "canary_instance_id": self.inst_b,
                "production_instance_ids": [inst_c],
                "auto_canary": True,
                "require_canary_success": True,
            },
        )
        self._register_manifest()
        release = releases.ensure_ci_release_draft(
            self.s,
            version="1.7.0",
            title="自动灰度",
            notes="不可变镜像已固定。",
        )
        self.assertEqual(release["status"], "development")
        self.assertIsNone(release["canary_instance_id"])
        self.assertEqual(
            [item["instance_id"] for item in release["deployments"]],
            [self.inst_a],
        )
        self.assertIsNotNone(releases.check_update(self.s, self.key_a, "1.6.32"))
        self.assertIsNone(releases.check_update(self.s, self.key_b, "1.6.32"))
        self.assertIsNone(releases.check_update(self.s, key_c, "1.6.32"))

        with self.assertRaises(FleetError) as dev_blocked:
            releases.start_canary(self.s, release["id"], self.inst_b)
        self.assertEqual(
            dev_blocked.exception.code, "NEXUS_DEVELOPMENT_NOT_PASSED"
        )
        with self.assertRaises(FleetError) as blocked:
            releases.publish(self.s, release["id"])
        self.assertEqual(blocked.exception.code, "NEXUS_DEVELOPMENT_NOT_PASSED")

        releases.report_update(
            self.s,
            raw_key=self.key_a,
            release_id=release["id"],
            status="success",
            current_version="1.7.0",
            detail="负责人开发节点自动验证通过",
        )
        canary = releases.get_release(self.s, release["id"])
        self.assertEqual(canary["status"], "canary")
        self.assertEqual(canary["canary_instance_id"], self.inst_b)
        self.assertEqual(
            [item["instance_id"] for item in canary["deployments"]],
            [self.inst_a, self.inst_b],
        )
        self.assertIsNone(releases.check_update(self.s, self.key_a, "1.7.0"))
        self.assertIsNotNone(releases.check_update(self.s, self.key_b, "1.6.32"))

        releases.report_update(
            self.s,
            raw_key=self.key_b,
            release_id=release["id"],
            status="success",
            current_version="1.7.0",
            detail="公司技术节点验证通过",
        )

        # 生产节点尚未部署或已停用时，不能把零台投放伪装成发布成功。
        release_policy.set_policy(
            self.s,
            {"production_instance_ids": [999]},
        )
        with self.assertRaises(FleetError) as missing:
            releases.publish(self.s, release["id"])
        self.assertEqual(missing.exception.code, "NEXUS_RELEASE_TARGET_MISSING")

        release_policy.set_policy(
            self.s,
            {"production_instance_ids": [inst_c]},
        )
        published = releases.publish(self.s, release["id"])
        self.assertEqual(published["status"], "published")
        self.assertEqual(
            {item["instance_id"] for item in published["deployments"]},
            {self.inst_a, self.inst_b, inst_c},
        )
        self.assertIsNone(releases.check_update(self.s, self.key_a, "1.6.32"))
        self.assertIsNotNone(releases.check_update(self.s, key_c, "1.6.32"))

    def test_container_release_requires_ci_manifest_and_manifest_is_immutable(self):
        """没有 CI 清单不能创建 Docker 发布，同版本摘要也不能被替换。"""
        with self.assertRaises(FleetError) as missing:
            releases.create_release(
                self.s,
                version="1.7.0",
                title="缺清单",
                notes="不能保存。",
                git_ref="v1.7.0",
                target="node",
                delivery_mode="container",
            )
        self.assertEqual(missing.exception.code, "NEXUS_IMAGE_MANIFEST_MISSING")
        self.s.rollback()
        original = self._register_manifest()
        self.assertEqual(original, self._register_manifest())
        changed = dict(original)
        changed["bot_image"] = (
            "ghcr.io/guduuos/guduu-os-bot@sha256:" + "d" * 64
        )
        with self.assertRaises(FleetError) as immutable:
            release_artifacts.register_manifest(self.s, changed)
        self.assertEqual(immutable.exception.code, "NEXUS_MANIFEST_IMMUTABLE")

    def test_manifest_webhook_requires_valid_fresh_hmac(self):
        """CI 清单入口必须拒绝过期或伪造签名。"""
        payload = {
            "version": "1.7.0",
            "git_ref": "v1.7.0",
            "source_commit": "a" * 40,
            "bot_image": "ghcr.io/guduuos/guduu-os-bot@sha256:" + "b" * 64,
            "web_image": "ghcr.io/guduuos/guduu-os-web@sha256:" + "c" * 64,
            "platforms": "linux/amd64,linux/arm64",
        }
        secret = "test-release-secret-0123456789-abcdef"
        stamp = str(int(time.time()))
        signature = hmac.new(
            secret.encode("utf-8"),
            stamp.encode("ascii")
            + b"\n"
            + release_artifacts.canonical_payload(payload),
            hashlib.sha256,
        ).hexdigest()
        old = os.environ.get("NEXUS_RELEASE_WEBHOOK_SECRET")
        os.environ["NEXUS_RELEASE_WEBHOOK_SECRET"] = secret
        try:
            release_artifacts.verify_webhook(payload, stamp, "sha256=" + signature)
            with self.assertRaises(FleetError):
                release_artifacts.verify_webhook(payload, stamp, "sha256=" + "0" * 64)
            with self.assertRaises(FleetError):
                release_artifacts.verify_webhook(
                    payload, str(int(stamp) - 1000), "sha256=" + signature
                )
        finally:
            if old is None:
                os.environ.pop("NEXUS_RELEASE_WEBHOOK_SECRET", None)
            else:
                os.environ["NEXUS_RELEASE_WEBHOOK_SECRET"] = old

    def test_create_requires_semver_and_matching_tag(self):
        """版本号和 tag 必须严格一致，且不能创建倒序版本。"""
        row = self._create()
        self.assertEqual(row["status"], "draft")
        self.assertEqual(row["target"], "node")
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
        with self.assertRaises(FleetError):
            releases.create_release(
                self.s,
                version="1.7.2",
                title="错误对象",
                notes="说明",
                git_ref="v1.7.2",
                target="all",
            )

    def test_nexus_release_is_global_announcement_without_node_task(self):
        """平台更新只向所有 OEM 门户发公告，绝不能进入节点安装状态机。"""
        release = self._create(target="nexus")
        published = releases.publish(self.s, release["id"])
        self.assertEqual(published["target"], "nexus")
        self.assertEqual(published["status"], "published")
        self.assertEqual(published["deployments"], [])
        self.assertIsNone(releases.check_update(self.s, self.key_a, "1.6.32"))

        # 即使这个 OEM 暂时没有认领任何节点，也应看到共享 Nexus 已上线公告。
        announcements = releases.list_oem_announcements(self.s, 999)
        self.assertEqual(len(announcements), 1)
        self.assertEqual(announcements[0]["target"], "nexus")
        self.assertEqual(announcements[0]["domain"], "")

        with self.assertRaises(FleetError) as canary_error:
            releases.start_canary(self.s, release["id"], self.inst_a)
        self.assertEqual(canary_error.exception.code, "NEXUS_RELEASE_TARGET")
        with self.assertRaises(FleetError) as rollback_error:
            releases.rollback(self.s, release["id"])
        self.assertEqual(rollback_error.exception.code, "NEXUS_RELEASE_TARGET")

        # “暂停”在平台轨道代表撤下公告，历史版本和发布时间仍保留。
        paused = releases.pause(self.s, release["id"])
        self.assertEqual(paused["status"], "paused")
        self.assertEqual(releases.list_oem_announcements(self.s, 999), [])

    def test_nexus_and_node_tracks_do_not_pause_each_other(self):
        """平台公告与节点投放可以同时有效，任一轨道发布都不能覆盖另一条。"""
        platform_id = self._create("1.7.0", "nexus")["id"]
        releases.publish(self.s, platform_id)
        node_id = self._create("1.7.1", "node")["id"]
        releases.publish(self.s, node_id)
        self.assertEqual(releases.get_release(self.s, platform_id)["status"], "published")
        self.assertEqual(releases.get_release(self.s, node_id)["status"], "published")

        platform_two_id = self._create("1.7.2", "nexus")["id"]
        releases.publish(self.s, platform_two_id)
        self.assertEqual(releases.get_release(self.s, node_id)["status"], "published")

    def test_build_release_draft_from_devlog(self):
        """当前版本、标题和 OEM 公告正文应从 DEVLOG 稳定生成。"""
        self.assertEqual(releases._merge_wrapped(["所属 OEM", "门户"]), "所属 OEM 门户")
        self.assertEqual(releases._merge_wrapped(["客户业务群", "自动发送"]), "客户业务群自动发送")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(
                "# 日志\n\n"
                "## 2026-07-31 — GuDuu OS 2.3.4 (patch)\n\n"
                "- 新增：版本后台可根据 `DEVLOG.md` 自动生成内容，管理员仍可审阅。\n"
                "- 修复：公告只展示给**所属 OEM**，不会泄露其他节点。\n\n"
                "## 2026-07-30 — GuDuu OS 2.3.3 (patch)\n\n"
                "- 修复：旧内容。\n"
            )
            path = Path(f.name)
        try:
            draft = releases.build_release_draft(
                self.s, version="2.3.4", devlog_path=path
            )
            self.assertEqual(draft["version"], "2.3.4")
            self.assertEqual(draft["git_ref"], "v2.3.4")
            self.assertEqual(draft["title"], "版本后台可根据 DEVLOG.md 自动生成内容")
            self.assertIn("• 新增：版本后台", draft["notes"])
            self.assertIn("所属 OEM", draft["notes"])
            self.assertNotIn("`", draft["notes"])
            self.assertNotIn("**", draft["notes"])
            self.assertFalse(draft["already_exists"])

            releases.create_release(
                self.s,
                version=draft["version"],
                git_ref=draft["git_ref"],
                title=draft["title"],
                notes=draft["notes"],
            )
            existing = releases.build_release_draft(
                self.s, version="2.3.4", devlog_path=path
            )
            self.assertTrue(existing["already_exists"])
        finally:
            os.unlink(path)

    def test_oem_announcements_follow_successful_owned_deployments(self):
        """公告只在安装成功后出现，而且 OEM 之间严格按 KEY 归属隔离。"""
        release_id = self._create()["id"]
        releases.publish(self.s, release_id)
        key_a = fleet._key_by_plain(self.s, self.key_a)
        key_b = fleet._key_by_plain(self.s, self.key_b)
        self.s.add(NexusKeyClaim(key_id=key_a.id, oem_id=101))
        self.s.add(NexusKeyClaim(key_id=key_b.id, oem_id=202))
        releases.report_update(
            self.s,
            raw_key=self.key_a,
            release_id=release_id,
            status="success",
            current_version="1.7.0",
        )
        # B 尚未成功，自己的门户不应提前出现公告。
        self.assertEqual(releases.list_oem_announcements(self.s, 202), [])
        announcements = releases.list_oem_announcements(self.s, 101)
        self.assertEqual(len(announcements), 1)
        self.assertEqual(announcements[0]["domain"], "a.example.com")
        self.assertEqual(announcements[0]["version"], "1.7.0")
        self.assertNotEqual(announcements[0]["domain"], "b.example.com")

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

    def test_archived_baseline_is_read_only_and_never_offered_as_update(self):
        """历史基线只用于审计，不得继续向节点下发或重新发布。"""
        release = self._create("1.7.0")
        releases.start_canary(self.s, release["id"], self.inst_b)
        row = self.s.get(db.NexusRelease, release["id"])
        row.status = "archived"
        self.s.flush()

        self.assertIsNone(releases.check_update(self.s, self.key_b, "1.6.32"))
        with self.assertRaises(FleetError) as publish_error:
            releases.publish(self.s, release["id"])
        self.assertEqual(publish_error.exception.code, "NEXUS_RELEASE_STATE")
        self.assertEqual(
            releases.get_release(self.s, release["id"])["status"], "archived"
        )

    def test_history_list_and_rollback_to_lower_version(self):
        """历史版本永久保留，回撤时当前版本高于目标也必须领取旧 tag。"""
        old_id = self._create("1.7.0")["id"]
        releases.publish(self.s, old_id)
        # 模拟 1.7.0 已完成全量发布；心跳是实例当前运行版本的权威快照。
        fleet.heartbeat(self.s, self.key_a, "1.7.0")
        fleet.heartbeat(self.s, self.key_b, "1.7.0")

        new_id = self._create("1.7.1")["id"]
        releases.publish(self.s, new_id)
        fleet.heartbeat(self.s, self.key_a, "1.7.1")
        fleet.heartbeat(self.s, self.key_b, "1.7.1")

        history = releases.list_releases(self.s)
        self.assertEqual([row["version"] for row in history], ["1.7.1", "1.7.0"])
        self.assertEqual(history[1]["status"], "paused")

        rolled_back = releases.rollback(self.s, old_id)
        self.assertEqual(rolled_back["status"], "rollback")
        self.assertEqual(rolled_back["counts"]["pending"], 2)
        task = releases.check_update(self.s, self.key_a, "1.7.1")
        self.assertIsNotNone(task)
        self.assertEqual(task["version"], "1.7.0")
        self.assertEqual(task["git_ref"], "v1.7.0")

    def test_unpublished_version_cannot_be_rollback_target(self):
        """默认未发布版本不能借回撤动作绕过灰度和首次发布门禁。"""
        release = self._create("1.7.0")
        self.assertEqual(release["status"], "draft")
        with self.assertRaises(FleetError) as ctx:
            releases.rollback(self.s, release["id"])
        self.assertEqual(ctx.exception.code, "NEXUS_RELEASE_NOT_PUBLISHED")


if __name__ == "__main__":
    unittest.main()
