"""cosmac.db 数据层单元测试。

全程用内存 SQLite（init_engine("sqlite://")），不碰真库、零基建。
覆盖：建表、Skill/Agent 的 upsert（新建+部分更新）、按作用域查询/过滤、
删除、作用域隔离（同 slug 不同作用域共存）、写错字段被挡。

运行：.venv/bin/python -m unittest cosmac.tests.test_db
"""

from __future__ import annotations

import unittest

from cosmac.db import init_engine, session_scope
from cosmac.db.models import SCOPE_GLOBAL, SCOPE_ROOM, SCOPE_USER
from cosmac.db import repo


class TestCosmacDb(unittest.TestCase):
    def setUp(self) -> None:
        # 每个用例一套全新的内存库，互不污染
        init_engine("sqlite://", create_all=True)

    # ───────── Skill ─────────

    def test_skill_create_and_get(self) -> None:
        with session_scope() as s:
            obj = repo.upsert_skill(
                s, SCOPE_USER, "@alice:example.invalid", "weekly-report",
                name="周报", description="生成本周数据周报", instructions="按...步骤",
            )
            self.assertIsNotNone(obj.id)
            self.assertTrue(obj.enabled)  # 默认启用
        with session_scope() as s:
            got = repo.get_skill(s, SCOPE_USER, "@alice:example.invalid", "weekly-report")
            self.assertIsNotNone(got)
            assert got is not None
            self.assertEqual(got.name, "周报")
            self.assertEqual(got.instructions, "按...步骤")

    def test_skill_upsert_partial_update(self) -> None:
        with session_scope() as s:
            repo.upsert_skill(s, SCOPE_GLOBAL, "", "kb-search", name="检索", enabled=True)
        # 再次 upsert 同三元组：只改 enabled，name 不动，且不新增行
        with session_scope() as s:
            repo.upsert_skill(s, SCOPE_GLOBAL, "", "kb-search", enabled=False)
        with session_scope() as s:
            rows = repo.list_skills(s, scope=SCOPE_GLOBAL)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].name, "检索")
            self.assertFalse(rows[0].enabled)

    def test_skill_scope_isolation(self) -> None:
        # 同 slug、不同作用域可共存（唯一约束是三元组）
        with session_scope() as s:
            repo.upsert_skill(s, SCOPE_USER, "@a:x", "summary", name="A的")
            repo.upsert_skill(s, SCOPE_ROOM, "!room:x", "summary", name="群的")
            repo.upsert_skill(s, SCOPE_GLOBAL, "", "summary", name="全局")
        with session_scope() as s:
            self.assertEqual(len(repo.list_skills(s)), 3)
            self.assertEqual(len(repo.list_skills(s, scope=SCOPE_USER)), 1)
            only = repo.get_skill(s, SCOPE_ROOM, "!room:x", "summary")
            assert only is not None
            self.assertEqual(only.name, "群的")

    def test_skill_enabled_filter_and_delete(self) -> None:
        with session_scope() as s:
            repo.upsert_skill(s, SCOPE_GLOBAL, "", "on", enabled=True)
            repo.upsert_skill(s, SCOPE_GLOBAL, "", "off", enabled=False)
        with session_scope() as s:
            self.assertEqual(len(repo.list_skills(s, enabled_only=True)), 1)
        with session_scope() as s:
            self.assertTrue(repo.delete_skill(s, SCOPE_GLOBAL, "", "off"))
            self.assertFalse(repo.delete_skill(s, SCOPE_GLOBAL, "", "off"))  # 再删返回 False
        with session_scope() as s:
            self.assertEqual(len(repo.list_skills(s)), 1)

    # ───────── Agent ─────────

    def test_agent_with_skill_slugs_json(self) -> None:
        with session_scope() as s:
            a = repo.upsert_agent(
                s, SCOPE_ROOM, "!ops:example.invalid", "planner",
                name="策划", system_prompt="你是策划", model="claude-opus-4-8",
                skill_slugs=["weekly-report", "kb-search"],
            )
            self.assertEqual(a.skill_slugs, ["weekly-report", "kb-search"])
        with session_scope() as s:
            got = repo.get_agent(s, SCOPE_ROOM, "!ops:example.invalid", "planner")
            assert got is not None
            self.assertEqual(got.model, "claude-opus-4-8")
            self.assertEqual(got.skill_slugs, ["weekly-report", "kb-search"])  # JSON 往返
        # 部分更新：换绑技能，人设不动
        with session_scope() as s:
            repo.upsert_agent(s, SCOPE_ROOM, "!ops:example.invalid", "planner",
                              skill_slugs=["summary"])
        with session_scope() as s:
            got = repo.get_agent(s, SCOPE_ROOM, "!ops:example.invalid", "planner")
            assert got is not None
            self.assertEqual(got.skill_slugs, ["summary"])
            self.assertEqual(got.system_prompt, "你是策划")

    # ───────── 护栏 ─────────

    def test_upsert_rejects_unknown_field(self) -> None:
        with session_scope() as s:
            with self.assertRaises(ValueError):
                repo.upsert_skill(s, SCOPE_GLOBAL, "", "x", bogus="hack")  # 不在白名单
            with self.assertRaises(ValueError):
                repo.upsert_agent(s, SCOPE_GLOBAL, "", "x", nonsense=1)


if __name__ == "__main__":
    unittest.main()
