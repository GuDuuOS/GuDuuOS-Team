"""任务看板数据层 + 档2 类型化执行者单元测试（内存 SQLite）。

运行：.venv/bin/python -m unittest cosmac.tests.test_task_repo
"""

from __future__ import annotations

import unittest

from cosmac.db import init_engine, session_scope
from cosmac.db.task_repo import create_tasks, list_tasks


class TestTaskRepo(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)

    def test_typed_executor_stored(self) -> None:
        with session_scope() as s:
            create_tasks(s, goal="做条短视频", items=[
                {"title": "写文案", "assignee": "文案", "executor_kind": "human", "executor_ref": "@xiaoyu:h"},
                {"title": "出分镜", "assignee": "分镜AI", "executor_kind": "agent", "executor_ref": "storyboard"},
                {"title": "跑封面", "executor_kind": "workflow", "executor_ref": "cover-gen"},
            ], room_id="!r:h", sender="@u:h")
        with session_scope() as s:
            rows = {t.title: t for t in list_tasks(s, room_ids=["!r:h"])}
        self.assertEqual(rows["写文案"].executor_kind, "human")
        self.assertEqual(rows["写文案"].executor_ref, "@xiaoyu:h")
        self.assertEqual(rows["出分镜"].executor_kind, "agent")
        self.assertEqual(rows["跑封面"].executor_kind, "workflow")
        self.assertEqual(rows["跑封面"].executor_ref, "cover-gen")

    def test_space_id_stored_and_defaults_empty(self) -> None:
        # 工作区归属：给了就存（任务看板据它按工作区过滤）；没给 → 空串（存量/无归属任务）。
        with session_scope() as s:
            create_tasks(s, goal="g", items=[{"title": "带归属"}],
                         room_id="!r:h", sender="@u:h", space_id="!space:h")
            create_tasks(s, goal="g", items=[{"title": "无归属"}],
                         room_id="!r:h", sender="@u:h")
        with session_scope() as s:
            rows = {t.title: t for t in list_tasks(s, room_ids=["!r:h"])}
        self.assertEqual(rows["带归属"].space_id, "!space:h")
        self.assertEqual(rows["无归属"].space_id, "")

    def test_invalid_kind_falls_back_to_none(self) -> None:
        with session_scope() as s:
            create_tasks(s, goal="g", items=[
                {"title": "瞎填的", "executor_kind": "robot", "executor_ref": "x"},
            ], room_id="!r:h", sender="@u:h")
        with session_scope() as s:
            t = list_tasks(s, room_ids=["!r:h"])[0]
        self.assertEqual(t.executor_kind, "none")
        self.assertEqual(t.executor_ref, "")  # 非法 kind → ref 也清掉，不留悬空引用

    def test_none_kind_clears_ref(self) -> None:
        with session_scope() as s:
            create_tasks(s, goal="g", items=[
                {"title": "暂不指派", "executor_kind": "none", "executor_ref": "@someone:h"},
            ], room_id="!r:h", sender="@u:h")
        with session_scope() as s:
            t = list_tasks(s, room_ids=["!r:h"])[0]
        self.assertEqual(t.executor_ref, "")

    def test_backward_compat_no_executor_fields(self) -> None:
        # 旧式只带 title/assignee 的拆解仍能用，默认 kind=none
        with session_scope() as s:
            create_tasks(s, goal="g", items=[{"title": "老任务", "assignee": "某人"}],
                         room_id="!r:h", sender="@u:h")
        with session_scope() as s:
            t = list_tasks(s, room_ids=["!r:h"])[0]
        self.assertEqual(t.executor_kind, "none")
        self.assertEqual(t.assignee, "某人")


if __name__ == "__main__":
    unittest.main()
