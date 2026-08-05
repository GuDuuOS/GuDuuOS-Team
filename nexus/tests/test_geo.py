"""实例地域（大屏地图打点）回归测试。

覆盖：地域字典校验/查表、IP 脱敏、兑码时带地域、心跳记来源网段、console 改地域、
list_instances 带出地域字段。临时 SQLite，不碰 run/nexus.db，不依赖网络。
跑法（项目根）： .venv/bin/python -m unittest nexus.tests.test_geo -v
"""

from __future__ import annotations

import os
import tempfile
import unittest

from nexus import db, fleet, geo
from nexus.db import NexusInstanceGeo
from nexus.fleet import FleetError


class GeoDictTest(unittest.TestCase):
    """纯字典逻辑，不碰库。"""

    def test_normalize_and_lookup(self):
        self.assertEqual(geo.normalize("cn-zj"), "CN-ZJ")     # 小写也认
        self.assertEqual(geo.normalize(" CN-ZJ "), "CN-ZJ")   # 前后空格
        self.assertEqual(geo.normalize("火星"), "")            # 非法 → 空
        info = geo.lookup("CN-ZJ")
        self.assertEqual(info["label"], "浙江")
        self.assertAlmostEqual(info["lat"], 30.2741, places=3)
        self.assertIsNone(geo.lookup("XX"))

    def test_options_cn_first(self):
        opts = geo.options()
        self.assertTrue(opts[0]["code"].startswith("CN-"))    # 中国排前面
        self.assertTrue(any(o["code"] == "SG" for o in opts))  # 境外也在
        # 每一项都必须有可用于打点的经纬度
        self.assertTrue(all(isinstance(o["lat"], float) for o in opts))

    def test_mask_ip(self):
        self.assertEqual(geo.mask_ip("1.2.3.4"), "1.2.3.0/24")   # 只留网段
        self.assertEqual(geo.mask_ip("240e:3b1:2::9"), "240e:3b1:2::/64")
        self.assertEqual(geo.mask_ip(""), "")
        self.assertEqual(geo.mask_ip("?"), "")
        self.assertEqual(geo.mask_ip("乱码"), "")


class InstanceGeoTest(unittest.TestCase):
    """兑码/心跳/改地域 的落库行为。"""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        db.init_engine("sqlite:///" + self._tmp.name)
        self.s = db.session()

    def tearDown(self):
        self.s.close()
        os.unlink(self._tmp.name)

    def _key(self) -> str:
        return fleet.issue_keys(self.s, note="t", token_grant=100)[0]["key"]

    def test_redeem_with_region(self):
        out = fleet.redeem(self.s, self._key(), "a.example.com", region="CN-ZJ")
        row = self.s.get(NexusInstanceGeo, out["instance_id"])
        self.assertEqual(row.region_code, "CN-ZJ")
        self.assertEqual(row.region_label, "浙江")
        self.assertAlmostEqual(row.lat, 30.2741, places=3)

    def test_redeem_bad_region_is_ignored_not_fatal(self):
        """地域填错不能让装机失败——留空、之后 console 补即可。"""
        out = fleet.redeem(self.s, self._key(), "b.example.com", region="火星基地")
        self.assertIsNone(self.s.get(NexusInstanceGeo, out["instance_id"]))

    def test_redeem_without_region(self):
        out = fleet.redeem(self.s, self._key(), "c.example.com")
        self.assertIsNone(self.s.get(NexusInstanceGeo, out["instance_id"]))

    def test_heartbeat_records_masked_ip_only(self):
        k = self._key()
        fleet.redeem(self.s, k, "d.example.com")
        fleet.heartbeat(self.s, k, "1.6.4", {}, client_ip="203.0.113.77")
        row = self.s.get(NexusInstanceGeo, 1)
        self.assertEqual(row.last_ip, "203.0.113.0/24")   # 只留网段，不存完整 IP
        self.assertEqual(row.region_code, "")             # 心跳不自动定位

    def test_heartbeat_without_ip_is_noop(self):
        k = self._key()
        fleet.redeem(self.s, k, "e.example.com")
        fleet.heartbeat(self.s, k, "1.6.4", {})
        self.assertIsNone(self.s.get(NexusInstanceGeo, 1))

    def test_set_geo_can_change_but_cannot_clear(self):
        """已部署节点允许纠正地域，但不能再次从大屏地图消失。"""
        out = fleet.redeem(self.s, self._key(), "f.example.com")
        iid = out["instance_id"]
        fleet.set_geo(self.s, iid, "SG")
        row = self.s.get(NexusInstanceGeo, iid)
        self.assertEqual(row.region_label, "新加坡")
        # 改到别的地域
        fleet.set_geo(self.s, iid, "CN-GD")
        self.assertEqual(self.s.get(NexusInstanceGeo, iid).region_label, "广东")
        # 清空会让大屏漏掉已部署节点，因此必须拒绝并保留旧值。
        with self.assertRaisesRegex(FleetError, "必须保留"):
            fleet.set_geo(self.s, iid, "")
        row = self.s.get(NexusInstanceGeo, iid)
        self.assertEqual(row.region_code, "CN-GD")
        self.assertIsNotNone(row.lat)

    def test_http_deployment_requires_supported_region(self):
        """真实部署入口不能再接受空地域或伪造代码。"""
        raw_key = self._key()
        with self.assertRaisesRegex(FleetError, "必须选择"):
            fleet.deployment_region(self.s, raw_key, "")
        with self.assertRaisesRegex(FleetError, "无效"):
            fleet.deployment_region(self.s, raw_key, "火星基地")
        self.assertEqual(fleet.deployment_region(self.s, raw_key, "cn-bj"), "CN-BJ")

    def test_existing_located_instance_can_reuse_region(self):
        """已定位节点的旧更新器即使未传地域，重装仍可复用数据库真值。"""
        raw_key = self._key()
        fleet.redeem(self.s, raw_key, "reuse.example.com", region="SG")
        self.assertEqual(fleet.deployment_region(self.s, raw_key, ""), "SG")

    def test_existing_unlocated_instance_must_be_repaired(self):
        """历史漏定位节点不能借重装继续绕过大屏门禁。"""
        raw_key = self._key()
        out = fleet.redeem(self.s, raw_key, "repair.example.com")
        with self.assertRaisesRegex(FleetError, "必须选择"):
            fleet.deployment_region(self.s, raw_key, "")
        fleet.redeem(self.s, raw_key, "repair.example.com", region="CN-BJ")
        row = self.s.get(NexusInstanceGeo, out["instance_id"])
        self.assertEqual(row.region_code, "CN-BJ")

    def test_set_geo_rejects_bad_code_and_missing_instance(self):
        out = fleet.redeem(self.s, self._key(), "g.example.com")
        with self.assertRaises(FleetError):
            fleet.set_geo(self.s, out["instance_id"], "不存在的地域")
        with self.assertRaises(FleetError):
            fleet.set_geo(self.s, 99999, "CN-ZJ")

    def test_set_geo_preserves_last_ip(self):
        """改地域不能把心跳记录的网段抹掉（那是核对依据）。"""
        k = self._key()
        fleet.redeem(self.s, k, "h.example.com")
        fleet.heartbeat(self.s, k, "1.6.4", {}, client_ip="198.51.100.9")
        fleet.set_geo(self.s, 1, "CN-BJ")
        row = self.s.get(NexusInstanceGeo, 1)
        self.assertEqual(row.last_ip, "198.51.100.0/24")
        self.assertEqual(row.region_label, "北京")

    def test_list_instances_carries_geo(self):
        k1 = self._key()
        fleet.redeem(self.s, k1, "i.example.com", region="CN-SH")
        k2 = self._key()
        fleet.redeem(self.s, k2, "j.example.com")          # 没填地域
        rows = {r["domain"]: r for r in fleet.list_instances(self.s)}
        self.assertEqual(rows["i.example.com"]["region_label"], "上海")
        self.assertIsNotNone(rows["i.example.com"]["lat"])
        # 没填的也要有字段（值为空），前端不用判 key 是否存在
        self.assertEqual(rows["j.example.com"]["region"], "")
        self.assertIsNone(rows["j.example.com"]["lat"])



class RequestStatTest(unittest.TestCase):
    """网关请求分钟桶：成功率 / 平均延迟 / 峰值（大屏质量指标的数据源）。"""

    def setUp(self) -> None:
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        db.init_engine("sqlite:///" + self._tmp.name)
        self.s = db.session()
        k = fleet.issue_keys(self.s, note="t", token_grant=100)[0]["key"]
        self.iid = fleet.redeem(self.s, k, "q.example.com")["instance_id"]

    def tearDown(self) -> None:
        self.s.close()
        os.unlink(self._tmp.name)

    def test_success_rate_counts_failures(self) -> None:
        """失败必须计入分母——只记成功的话成功率永远 100%。"""
        for _ in range(3):
            fleet.record_request(self.s, self.iid, ok=True, latency_ms=200)
        fleet.record_request(self.s, self.iid, ok=False)
        st = fleet.request_stats(self.s)[self.iid]
        self.assertEqual((st["ok"], st["fail"]), (3, 1))
        self.assertEqual(st["success_pct"], 75.0)

    def test_latency_only_from_success(self) -> None:
        """失败多是秒回的 4xx，混进均值会把延迟拉得虚低。"""
        fleet.record_request(self.s, self.iid, ok=True, latency_ms=1000)
        fleet.record_request(self.s, self.iid, ok=True, latency_ms=3000)
        fleet.record_request(self.s, self.iid, ok=False, latency_ms=5)
        stats = fleet.request_stats(self.s)[self.iid]
        self.assertEqual(stats["avg_ms"], 2000)
        self.assertEqual(stats["p95_ms"], 3000)
        self.assertFalse(stats["p95_overflow"])

    def test_p95_comes_from_real_histogram(self) -> None:
        """P95 必须按真实延迟分布落桶，不能再由平均值乘常数估算。"""
        for _ in range(19):
            fleet.record_request(self.s, self.iid, ok=True, latency_ms=80)
        fleet.record_request(self.s, self.iid, ok=True, latency_ms=2800)
        stats = fleet.request_stats(self.s)[self.iid]
        self.assertEqual(stats["p95_ms"], 100)

    def test_p95_marks_overflow_bucket(self) -> None:
        """超过直方图上限的极慢请求必须显式标记，不能伪装成精确上界。"""
        fleet.record_request(self.s, self.iid, ok=True, latency_ms=400000)
        stats = fleet.request_stats(self.s)[self.iid]
        self.assertEqual(stats["p95_ms"], 300000)
        self.assertTrue(stats["p95_overflow"])

    def test_p95_at_last_finite_bucket_is_not_overflow(self) -> None:
        """仍在 300 秒内的请求属于有限上界，不能误标成“至少 300 秒”。"""
        fleet.record_request(self.s, self.iid, ok=True, latency_ms=250000)
        stats = fleet.request_stats(self.s)[self.iid]
        self.assertEqual(stats["p95_ms"], 300000)
        self.assertFalse(stats["p95_overflow"])

    def test_no_requests_yields_none_not_zero(self) -> None:
        """没有请求时成功率必须是 None（前端显示「—」）——绝不能落成 0%。"""
        self.assertEqual(fleet.request_stats(self.s), {})
        summary = fleet.dash_summary(self.s)
        self.assertIsNone(summary["oems"][0]["success_pct"])
        self.assertIsNone(summary["totals"]["success_pct"])
        self.assertIsNone(summary["totals"]["p95_latency_ms"])

    def test_peak_per_min_and_summary(self) -> None:
        for _ in range(5):
            fleet.record_request(self.s, self.iid, ok=True, latency_ms=100)
        self.s.commit()
        summary = fleet.dash_summary(self.s)
        self.assertEqual(summary["oems"][0]["peak_per_min"], 5)
        self.assertEqual(summary["oems"][0]["success_pct"], 100.0)
        self.assertEqual(summary["totals"]["peak_per_min"], 5)
        self.assertEqual(summary["totals"]["p95_latency_ms"], 100)

    def test_regions_only_counts_located_instances(self) -> None:
        fleet.set_geo(self.s, self.iid, "CN-ZJ")
        self.s.commit()
        self.assertIn("浙江", fleet.dash_summary(self.s)["totals"]["regions"])

    def test_unlocated_total_keeps_missing_marker_visible(self) -> None:
        """历史缺定位节点仍计入实例总数，并单独暴露待定位数量。"""
        summary = fleet.dash_summary(self.s)
        self.assertEqual(summary["totals"]["instances"], 1)
        self.assertEqual(summary["totals"]["unlocated"], 1)

if __name__ == "__main__":
    unittest.main()
