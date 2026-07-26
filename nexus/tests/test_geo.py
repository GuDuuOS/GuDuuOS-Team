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

    def test_set_geo_and_clear(self):
        out = fleet.redeem(self.s, self._key(), "f.example.com")
        iid = out["instance_id"]
        fleet.set_geo(self.s, iid, "SG")
        row = self.s.get(NexusInstanceGeo, iid)
        self.assertEqual(row.region_label, "新加坡")
        # 改到别的地域
        fleet.set_geo(self.s, iid, "CN-GD")
        self.assertEqual(self.s.get(NexusInstanceGeo, iid).region_label, "广东")
        # 清空 → 大屏不再打点
        fleet.set_geo(self.s, iid, "")
        row = self.s.get(NexusInstanceGeo, iid)
        self.assertEqual(row.region_code, "")
        self.assertIsNone(row.lat)

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


if __name__ == "__main__":
    unittest.main()
