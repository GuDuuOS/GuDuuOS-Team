# -*- coding: utf-8 -*-
"""产品时区(tzutil)单测:解析/显示按产品时区而非服务器时区。

负责人线上实测:GCP 服务器是 UTC,AI 报"现在是 03:04"而用户是 11:05(北京)。
断言策略不依赖测试机时区:比较两个 COSMAC_TZ 设置下的差值(上海 vs 东京差 1 小时)。

运行:.venv/bin/python -m unittest cosmac.tests.test_tzutil
"""

from __future__ import annotations

import os
import re
import unittest
from datetime import datetime, timedelta, timezone

from cosmac.ai.tools import _parse_due_to_epoch
from cosmac.tzutil import fmt_ts, now_text, parse_local_to_epoch, utc_iso


class TestTzUtil(unittest.TestCase):
    def setUp(self) -> None:
        self._old = os.environ.get("COSMAC_TZ")

    def tearDown(self) -> None:
        if self._old is None:
            os.environ.pop("COSMAC_TZ", None)
        else:
            os.environ["COSMAC_TZ"] = self._old

    def test_parse_respects_product_tz(self) -> None:
        os.environ["COSMAC_TZ"] = "Asia/Shanghai"
        ts_sh = parse_local_to_epoch("2026-07-14 11:30", "%Y-%m-%d %H:%M")
        os.environ["COSMAC_TZ"] = "Asia/Tokyo"
        ts_tokyo = parse_local_to_epoch("2026-07-14 11:30", "%Y-%m-%d %H:%M")
        # 同一钟面时刻,东京(UTC+9)比上海(UTC+8)早 1 小时到 → epoch 小 3600。
        # 若解析走了服务器时区,两者会相等(回归即抓)。
        self.assertEqual(ts_sh - ts_tokyo, 3600)

    def test_roundtrip_parse_then_format(self) -> None:
        os.environ["COSMAC_TZ"] = "Asia/Shanghai"
        ts = parse_local_to_epoch("2026-07-14 11:30", "%Y-%m-%d %H:%M")
        self.assertEqual(fmt_ts(ts), "07-14 11:30")  # 存进去什么钟面,显示回什么钟面

    def test_now_text_format(self) -> None:
        os.environ["COSMAC_TZ"] = "Asia/Shanghai"
        self.assertTrue(re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}（周[一二三四五六日]）$", now_text()))

    def test_bad_tz_falls_back(self) -> None:
        os.environ["COSMAC_TZ"] = "Not/AZone"
        self.assertIsNotNone(parse_local_to_epoch("2026-07-14 11:30", "%Y-%m-%d %H:%M"))

    def test_weekday_table(self) -> None:
        # 对照表:从明天起 N 天,格式 MM-DD周X,星期与 zoneinfo 权威推算一致
        from cosmac.tzutil import product_tz, weekday_table
        os.environ["COSMAC_TZ"] = "Asia/Shanghai"
        table = weekday_table(14)
        items = table.split(" ")
        self.assertEqual(len(items), 14)
        wd = "一二三四五六日"
        for i, it in enumerate(items, start=1):
            d = datetime.now(product_tz()) + timedelta(days=i)
            self.assertEqual(it, f"{d.strftime('%m-%d')}周{wd[d.weekday()]}")

    def test_due_parse_uses_product_tz(self) -> None:
        # 任务截止解析(_parse_due_to_epoch)同口径:date-only 默认当天 23:59
        os.environ["COSMAC_TZ"] = "Asia/Shanghai"
        full = _parse_due_to_epoch("2026-07-14 11:30")
        day = _parse_due_to_epoch("2026-07-14")
        self.assertEqual(fmt_ts(full), "07-14 11:30")
        self.assertEqual(fmt_ts(day), "07-14 23:59")
        os.environ["COSMAC_TZ"] = "Asia/Tokyo"
        self.assertEqual(full - _parse_due_to_epoch("2026-07-14 11:30"), 3600)

    def test_utc_iso_marks_naive_database_time_as_utc(self) -> None:
        """数据库 naive UTC 必须补 Z，避免浏览器误按本地钟面解释。"""
        value = datetime(2026, 7, 27, 2, 34, 37)
        self.assertEqual(utc_iso(value), "2026-07-27T02:34:37Z")

    def test_utc_iso_converts_aware_time_and_accepts_none(self) -> None:
        """带时区时间先换算 UTC；空数据库字段保持为空字符串。"""
        shanghai = timezone(timedelta(hours=8))
        value = datetime(2026, 7, 27, 10, 34, 37, tzinfo=shanghai)
        self.assertEqual(utc_iso(value), "2026-07-27T02:34:37Z")
        self.assertEqual(utc_iso(None), "")


if __name__ == "__main__":
    unittest.main()
