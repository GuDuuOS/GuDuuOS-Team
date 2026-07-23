# -*- coding: utf-8 -*-
"""「我的AI工坊」三个 tab 的展示排序单测(负责人建议:按新增时间倒序,刚建的排最前)。

- 自建智能体/技能:端点按 created_at 倒序(共用 repo 的 slug 排序**不动**——
  名册注入等处依赖它的稳定顺序);
- 已获取:market_repo.list_acquired 直接按 id 倒序(另两个调用方只做 set/计数,无关顺序)。

运行:.venv/bin/python -m unittest cosmac.tests.test_studio_order
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from cosmac.db import init_engine, session_scope
from cosmac.db.market_repo import add_acquired, list_acquired
from cosmac.db.models import SCOPE_USER
from cosmac.db.repo import list_agents, list_skills, upsert_agent, upsert_skill

U = "@u:h"


class TestAcquiredOrder(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)

    def test_latest_acquired_first(self) -> None:
        with session_scope() as s:
            for slug in ("first", "second", "third"):
                add_acquired(s, user_id=U, kind="agent", slug=slug)
        with session_scope() as s:
            got = [slug for _kind, slug in list_acquired(s, user_id=U)]
        self.assertEqual(got, ["third", "second", "first"])  # 最近获取的在最前


class TestSelfBuiltOrder(unittest.TestCase):
    """端点侧排序键的等价验证:sorted(created_at, id) 倒序 = 新增在最前。"""

    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)

    def _mk(self, kind: str, slug: str, when: datetime) -> None:
        with session_scope() as s:
            fn = upsert_agent if kind == "agent" else upsert_skill
            row = fn(s, SCOPE_USER, U, slug, name=slug)
            row.created_at = when  # 打桩创建时间(同秒批量建时靠 id 兜底)

    def test_agents_newest_first(self) -> None:
        base = datetime(2026, 7, 1, 10, 0, 0)
        self._mk("agent", "old", base)
        self._mk("agent", "mid", base + timedelta(days=1))
        self._mk("agent", "new", base + timedelta(days=2))
        with session_scope() as s:
            rows = sorted(
                list_agents(s, scope=SCOPE_USER, scope_id=U),
                key=lambda x: (x.created_at, x.id), reverse=True,
            )
            self.assertEqual([r.slug for r in rows], ["new", "mid", "old"])

    def test_skills_newest_first(self) -> None:
        base = datetime(2026, 7, 1, 10, 0, 0)
        self._mk("skill", "aaa-old", base)              # slug 字典序最前但最旧
        self._mk("skill", "zzz-new", base + timedelta(days=1))
        with session_scope() as s:
            rows = sorted(
                list_skills(s, scope=SCOPE_USER, scope_id=U),
                key=lambda x: (x.created_at, x.id), reverse=True,
            )
            # 按时间倒序:新的在前(而不是按 slug 字典序 aaa 在前)
            self.assertEqual([r.slug for r in rows], ["zzz-new", "aaa-old"])

    def test_repo_default_order_unchanged(self) -> None:
        # 共用 repo 仍按 slug 稳定排序——名册注入等依赖它,不能被工坊需求带偏
        base = datetime(2026, 7, 1, 10, 0, 0)
        self._mk("skill", "bbb", base + timedelta(days=1))
        self._mk("skill", "aaa", base)
        with session_scope() as s:
            rows = list_skills(s, scope=SCOPE_USER, scope_id=U)
            self.assertEqual([r.slug for r in rows], ["aaa", "bbb"])


if __name__ == "__main__":
    unittest.main()
