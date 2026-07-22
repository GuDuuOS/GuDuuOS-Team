# -*- coding: utf-8 -*-
"""真人+AI 共同执行任务的可见性单测(负责人实报)。

场景:专班派单把任务派给 agent:social,assignee 写「社媒运营+duxiuzhen01」——
AI 执行,但挂名真人 duxiuzhen01 的任务看板看不到该任务(旧判定:executor 是
agent 且 ref 非空 → 直接 False,不看 assignee)。

修复后口径:executor_kind=human 且有 ref → 只认 ref;其余(agent/workflow/无 ref)
→ assignee 按词切分逐个比对本人 localpart(完整词相等,非子串)。
DB 超集查询(list_tasks_for_user)同步放宽:assignee LIKE 不再要求 ref 为空。

内存 SQLite、零 key。运行:.venv/bin/python -m unittest cosmac.tests.test_co_assignee
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from cosmac.bots.appservice_bot import CosmacBot
from cosmac.db import init_engine, session_scope
from cosmac.db.task_repo import create_tasks, list_tasks_for_user

ROOM = "!proj:h"


def _task(assignee: str, kind: str = "none", ref: str = "") -> SimpleNamespace:
    """构造判定用的最小任务对象(只带谓词读的三个字段)。"""
    return SimpleNamespace(assignee=assignee, executor_kind=kind, executor_ref=ref)


class TestIsTaskAssignee(unittest.TestCase):
    """后端谓词 _is_task_assignee(前端 assignedToMe 同口径)。"""

    def _hit(self, user: str, t: SimpleNamespace) -> bool:
        return CosmacBot._is_task_assignee(user, t)

    def test_agent_executed_task_visible_to_co_assignee(self) -> None:
        # 线上原样:AI 执行 + assignee 挂真人 → 真人必须命中
        t = _task("社媒运营+duxiuzhen01", kind="agent", ref="social")
        self.assertTrue(self._hit("@duxiuzhen01:dev-cs.guduuos.com", t))

    def test_agent_task_not_visible_to_others(self) -> None:
        t = _task("社媒运营+duxiuzhen01", kind="agent", ref="social")
        self.assertFalse(self._hit("@chengjy:h", t))

    def test_no_substring_false_match(self) -> None:
        # 完整词相等,非子串:localpart "du" 不该命中 "duxiuzhen01"
        t = _task("社媒运营+duxiuzhen01", kind="agent", ref="social")
        self.assertFalse(self._hit("@du:h", t))

    def test_full_id_in_assignee(self) -> None:
        # assignee 里写全 id 也能配(词内 _lp 剥 @ 和 :server)
        t = _task("运营 @duxiuzhen01:dev-cs.guduuos.com", kind="workflow", ref="wf1")
        self.assertTrue(self._hit("@duxiuzhen01:dev-cs.guduuos.com", t))

    def test_legacy_no_ref_any_word(self) -> None:
        # 旧任务无类型化执行者:assignee 任一词等于本人即命中(原先只认首词)
        t = _task("复盘 duxz")
        self.assertTrue(self._hit("@duxz:h", t))

    def test_human_ref_still_exclusive(self) -> None:
        # human+ref 保持原语义:只认 ref,assignee 挂别人也不扩权
        t = _task("协作+duxiuzhen01", kind="human", ref="@anqi:h")
        self.assertFalse(self._hit("@duxiuzhen01:h", t))
        self.assertTrue(self._hit("@anqi:h", t))


class TestListTasksForUser(unittest.TestCase):
    """DB 超集查询:AI 执行的共同任务不能在 DB 层被漏掉。"""

    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)

    def test_agent_task_with_co_assignee_in_candidates(self) -> None:
        with session_scope() as s:
            create_tasks(s, goal="测评", items=[{
                "title": "内容发布与互动运营",
                "assignee": "社媒运营+duxiuzhen01",
                "executor_kind": "agent",
                "executor_ref": "social",
            }], room_id=ROOM, sender="@boss:h")
        with session_scope() as s:
            rows = list_tasks_for_user(
                s, user_id="@duxiuzhen01:h", localpart="duxiuzhen01")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].title, "内容发布与互动运营")

    def test_unrelated_user_gets_nothing(self) -> None:
        with session_scope() as s:
            create_tasks(s, goal="测评", items=[{
                "title": "内容发布与互动运营",
                "assignee": "社媒运营+duxiuzhen01",
                "executor_kind": "agent",
                "executor_ref": "social",
            }], room_id=ROOM, sender="@boss:h")
        with session_scope() as s:
            rows = list_tasks_for_user(s, user_id="@other:h", localpart="other")
            self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
