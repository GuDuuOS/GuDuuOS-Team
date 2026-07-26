# -*- coding: utf-8 -*-
"""任务改派与重开单测(负责人报的 bug:AI 改派后看板责任人不变、重开任务进度仍挂 100%)。

运行:.venv/bin/python -m unittest cosmac.tests.test_task_reassign
"""

from __future__ import annotations

import unittest

from cosmac.db import init_engine, session_scope
from cosmac.db.task_repo import create_tasks, get_task, update_task

ROOM = "!team:h"


def _seed() -> int:
    """造一条已完成的真人任务(设计师 chengjy),返回 task_id。"""
    with session_scope() as s:
        tasks = create_tasks(
            s, goal="自习室预约专班",
            items=[{
                "title": "界面设计与视觉稿输出", "assignee": "设计师 chengjy",
                "executor_kind": "human", "executor_ref": "@chengjy:h",
            }],
            room_id=ROOM, sender="@boss:h",
        )
        tid = tasks[0].id
    with session_scope() as s:
        update_task(s, tid, status="done")
    return tid


class TestTaskReassign(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)
        self.tid = _seed()

    def test_reassign_updates_executor_fields(self) -> None:
        """改派:assignee/executor_kind/executor_ref 三件套真实落库(此前根本不支持)。"""
        with session_scope() as s:
            ok = update_task(
                s, self.tid, status="doing",
                assignee="UI 设计师", executor_kind="agent", executor_ref="ui-designer",
            )
            self.assertTrue(ok)
        with session_scope() as s:
            t = get_task(s, self.tid)
            self.assertEqual(t.assignee, "UI 设计师")
            self.assertEqual(t.executor_kind, "agent")
            self.assertEqual(t.executor_ref, "ui-designer")
            self.assertEqual(t.status, "doing")

    def test_reopen_resets_stale_100_progress(self) -> None:
        """done(100%) 改回 doing 且未显式给进度 → 进度清回 0(重开的卡别再显示 100%)。"""
        with session_scope() as s:
            update_task(s, self.tid, status="doing")
        with session_scope() as s:
            self.assertEqual(get_task(s, self.tid).progress, 0)

    def test_reopen_keeps_partial_progress(self) -> None:
        """非 100 的进度重开时保留(暂停再继续不丢进度)。"""
        with session_scope() as s:
            update_task(s, self.tid, status="doing", progress=60)  # 先置 60
        with session_scope() as s:
            update_task(s, self.tid, status="todo")                # 重开不给进度
        with session_scope() as s:
            self.assertEqual(get_task(s, self.tid).progress, 60)

    def test_explicit_progress_wins_on_reopen(self) -> None:
        with session_scope() as s:
            update_task(s, self.tid, status="doing", progress=30)
        with session_scope() as s:
            self.assertEqual(get_task(s, self.tid).progress, 30)

    def test_done_still_fills_100(self) -> None:
        """回归:标 done 不给进度仍补满 100。"""
        with session_scope() as s:
            update_task(s, self.tid, status="doing", progress=40)
        with session_scope() as s:
            update_task(s, self.tid, status="done")
        with session_scope() as s:
            self.assertEqual(get_task(s, self.tid).progress, 100)

    def test_bad_executor_kind_falls_to_none(self) -> None:
        """repo 层白名单外的 kind 回落 none(工具层另有拒绝,这里是最后防线)。"""
        with session_scope() as s:
            update_task(s, self.tid, executor_kind="robot")
        with session_scope() as s:
            self.assertEqual(get_task(s, self.tid).executor_kind, "none")

    def test_empty_assignee_ignored(self) -> None:
        """空白 assignee 不覆盖原责任人。"""
        with session_scope() as s:
            update_task(s, self.tid, assignee="   ", status="doing")
        with session_scope() as s:
            self.assertEqual(get_task(s, self.tid).assignee, "设计师 chengjy")


class TestUpdateTaskTool(unittest.TestCase):
    """工具层:_tool_update_task 透传改派参数 + 非法 kind 拒绝。"""

    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)
        self.tid = _seed()
        from cosmac.ai.tools import Toolbox, ToolContext
        self.box = Toolbox(client=None)  # type: ignore[arg-type]
        self.ctx = ToolContext(room_id=ROOM, sender="@boss:h")

    def test_tool_reassign_persists(self) -> None:
        out = self.box._tool_update_task({
            "task_id": self.tid, "status": "doing",
            "assignee": "UI 设计师", "executor_kind": "agent",
            "executor_ref": "ui-designer",
        }, self.ctx)
        self.assertIn("改派给 UI 设计师", out)
        with session_scope() as s:
            t = get_task(s, self.tid)
            self.assertEqual(t.executor_ref, "ui-designer")
            self.assertEqual(t.executor_kind, "agent")

    def test_tool_rejects_bad_kind(self) -> None:
        out = self.box._tool_update_task({
            "task_id": self.tid, "executor_kind": "robot",
        }, self.ctx)
        self.assertIn("executor_kind", out)
        with session_scope() as s:
            self.assertEqual(get_task(s, self.tid).executor_kind, "human")  # 没被动

    def test_reassign_to_agent_triggers_autorun(self) -> None:
        """负责人实报根因回归:把任务改派给 AI 同事(executor_kind=agent)→ 触发一次自动执行。
        此前只有 assemble_team 内联建 agent 任务才自动跑,事后 update_task 改派的永远不执行。"""
        fired = []
        self.box.auto_execute_agent_tasks = (  # type: ignore
            lambda room, sender, ids, rule: fired.append((room, sender, tuple(ids)))
        )
        out = self.box._tool_update_task({
            "task_id": self.tid, "status": "doing",
            "executor_kind": "agent", "executor_ref": "ui-designer",
        }, self.ctx)
        self.assertIn("已交给 TA 自动执行", out)
        self.assertEqual(fired, [(ROOM, "@boss:h", (self.tid,))])

    def test_mark_agent_task_doing_triggers_autorun(self) -> None:
        """负责人实报根因回归:把**已是 agent、尚无产出**的任务只标 status=doing(不重传
        executor_kind)也要触发执行。此前外层闸只认本次传了 executor_kind=agent,于是这种
        "只标 doing"的任务永远不执行→卡在 doing/进度0、频道无产出、AI 却谎报已交付。"""
        from cosmac.db.task_repo import create_tasks
        with session_scope() as s:
            tid = create_tasks(s, goal="摆摊专班", items=[{
                "title": "摊位文案", "executor_kind": "agent", "executor_ref": "copywriter",
            }], room_id=ROOM, sender="@boss:h")[0].id
        fired = []
        self.box.auto_execute_agent_tasks = (  # type: ignore
            lambda room, sender, ids, rule: fired.append((room, sender, tuple(ids))))
        # 只标 doing,不传 executor_kind → 也应触发(任务本就是 agent、未完成、无产出)
        out = self.box._tool_update_task({"task_id": tid, "status": "doing"}, self.ctx)
        self.assertIn("已交给 TA 自动执行", out)
        self.assertEqual(fired, [(ROOM, "@boss:h", (tid,))])

    def test_doing_agent_task_in_flight_not_retriggered(self) -> None:
        """已在执行中(进度≥10)的 agent 任务,再标 doing 不重复触发(防重复产出)。"""
        from cosmac.db.task_repo import create_tasks
        with session_scope() as s:
            tid = create_tasks(s, goal="摆摊专班", items=[{
                "title": "排班", "executor_kind": "agent", "executor_ref": "project-shepherd",
            }], room_id=ROOM, sender="@boss:h")[0].id
            update_task(s, tid, status="doing", progress=10)  # 模拟执行器已开跑
        fired = []
        self.box.auto_execute_agent_tasks = lambda *a: fired.append(a)  # type: ignore
        self.box._tool_update_task({"task_id": tid, "status": "doing"}, self.ctx)
        self.assertEqual(fired, [])  # 进度≥10 → 不重复触发

    def test_mark_done_does_not_trigger_autorun(self) -> None:
        """已完成/已交付的任务不因改派再被自动执行(避免重复产出)。"""
        fired = []
        self.box.auto_execute_agent_tasks = (  # type: ignore
            lambda *a: fired.append(a))
        # 直接标 done(seed 任务本就 done)+ 指定 agent:status=done → 不触发
        self.box._tool_update_task({
            "task_id": self.tid, "status": "done",
            "executor_kind": "agent", "executor_ref": "ui-designer",
        }, self.ctx)
        self.assertEqual(fired, [])


if __name__ == "__main__":
    unittest.main()
