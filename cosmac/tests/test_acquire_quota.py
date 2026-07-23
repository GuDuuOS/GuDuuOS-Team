# -*- coding: utf-8 -*-
"""商城「已获取」数量按会员等级限额单测(负责人:获取数量应由会员限制,此前无此配额项)。

要点:
- 配额目录有 acquired_items 一项(前后端各一份,后台「会员权限」页可逐等级配);
- 未获取过的资源超额 → 403 带升级提示;已获取的再点(幂等)不受限;
- -1(创作者/管理员)不限;移除后额度立即释放(track=existing 直接数现有行)。

运行:.venv/bin/python -m unittest cosmac.tests.test_acquire_quota
"""

from __future__ import annotations

import unittest

from cosmac.db import init_engine, session_scope
from cosmac.db.market_repo import add_acquired, list_acquired, remove_acquired
from cosmac.quotas import metric_meta

U = "@u:h"


class TestAcquiredQuotaCatalog(unittest.TestCase):
    def test_metric_exists_with_tier_defaults(self) -> None:
        meta = metric_meta("acquired_items")
        self.assertIsNotNone(meta, "配额目录里必须有 acquired_items(否则后台配不了、限制无从生效)")
        self.assertEqual(meta["track"], "existing")  # 数现有行,移除即释放
        d = meta["defaults"]
        # 免费给少量体验、付费放宽、创作者不限——阶梯必须单调
        self.assertLess(d["free"], d["paid"])
        self.assertEqual(d["creator"], -1)


class TestAcquiredCounting(unittest.TestCase):
    """计数口径:限额判定与「我的额度」用量都基于 list_acquired 的现有行数。"""

    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)

    def test_count_grows_and_shrinks(self) -> None:
        with session_scope() as s:
            for i in range(3):
                add_acquired(s, user_id=U, kind="agent", slug=f"a{i}")
            self.assertEqual(len(list_acquired(s, user_id=U)), 3)
            remove_acquired(s, user_id=U, kind="agent", slug="a1")
            # 移除后额度立即释放(不是单调累计,否则删了也回不了血)
            self.assertEqual(len(list_acquired(s, user_id=U)), 2)

    def test_reacquire_same_slug_is_idempotent(self) -> None:
        # 同一条重复获取不该把额度算两次(端点侧也据此对"已获取"放行)
        with session_scope() as s:
            add_acquired(s, user_id=U, kind="agent", slug="dup")
            add_acquired(s, user_id=U, kind="agent", slug="dup")
            self.assertEqual(len(list_acquired(s, user_id=U)), 1)

    def test_scoped_per_user(self) -> None:
        # 别人的获取不占我的额度
        with session_scope() as s:
            add_acquired(s, user_id=U, kind="agent", slug="mine")
            add_acquired(s, user_id="@other:h", kind="agent", slug="theirs")
            self.assertEqual(len(list_acquired(s, user_id=U)), 1)


if __name__ == "__main__":
    unittest.main()
