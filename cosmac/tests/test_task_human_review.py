# -*- coding: utf-8 -*-
"""任务看板“真人审核闸”回归测试。

覆盖本次修复的三条硬约束：
- 新任务保存指定真人审核人，审核人能在自己的看板看到它；
- 执行人点“完成”只会提交 review/pending，不会跳过人审；
- 只有指定审核人能把任务放行为 done/approved，之后频道才算全部完成。

运行：``.venv/bin/python -m unittest cosmac.tests.test_task_human_review``。
"""

from __future__ import annotations

import unittest

from cosmac.bots.appservice_bot import CosmacBot
from cosmac.config import CosmacConfig
from cosmac.db import init_engine, session_scope
from cosmac.db.task_repo import (
    create_tasks,
    get_task,
    rooms_all_tasks_done,
)


ROOM = "!review:h"
BOSS = "@boss:h"
WORKER = "@worker:h"
REVIEWER = "@reviewer:h"


class _Client:
    """最小 Matrix 客户端桩：token 本身就是登录用户 ID。"""

    def whoami(self, token: str) -> str:
        """返回当前登录用户，空 token 视为未登录。"""
        return token or ""

    def is_joined_member(self, room_id: str, user_id: str) -> bool:
        """本测试故意不靠“频道成员”扩权，隔离执行/审核角色。"""
        return False


class TestTaskHumanReview(unittest.TestCase):
    """验证执行交付与真人验收不再合并为同一步。"""

    def setUp(self) -> None:
        """每个用例重建内存 SQLite，避免任务 ID/状态串扰。"""
        init_engine("sqlite://", create_all=True)
        self.bot = CosmacBot(CosmacConfig(llm_provider="echo"))
        self.bot.client = _Client()  # type: ignore[assignment]
        self.bot._is_platform_admin = lambda _uid: False  # type: ignore[method-assign]
        with session_scope() as session:
            rows = create_tasks(
                session,
                goal="发布健康科普",
                items=[{
                    "title": "审核科普内容",
                    "executor_kind": "human",
                    "executor_ref": WORKER,
                    "reviewer_ref": REVIEWER,
                }],
                room_id=ROOM,
                sender=BOSS,
            )
            self.task_id = rows[0].id

    def _task_state(self):
        """读取并脱离 session 复制测试关心的审核状态。"""
        with session_scope() as session:
            task = get_task(session, self.task_id)
            assert task is not None
            return task.status, task.review_status, task.progress

    def test_executor_submits_and_reviewer_approves(self) -> None:
        """执行人的 done 请求被转成待审，审核人才能真正完成。"""
        code, submitted = self.bot.handle_task_update(
            WORKER, {"id": self.task_id, "status": "done", "result": "交付物"}
        )
        self.assertEqual(code, 200)
        self.assertEqual(submitted["status"], "review")
        self.assertEqual(submitted["review_status"], "pending")
        self.assertEqual(self._task_state(), ("review", "pending", 100))

        # 待审时仍不算“全部完成”，不应触发归档催办。
        with session_scope() as session:
            self.assertEqual(rooms_all_tasks_done(session), [])

        code, approved = self.bot.handle_task_update(
            REVIEWER, {"id": self.task_id, "status": "done"}
        )
        self.assertEqual(code, 200)
        self.assertEqual(approved["status"], "done")
        self.assertEqual(approved["review_status"], "approved")
        self.assertEqual(self._task_state(), ("done", "approved", 100))
        with session_scope() as session:
            self.assertEqual(rooms_all_tasks_done(session)[0]["room_id"], ROOM)

    def test_reviewer_can_see_task_without_being_executor(self) -> None:
        """审核人不是执行人，仍必须在自己的看板看到待审卡。"""
        code, payload = self.bot.handle_tasks_list(REVIEWER)
        self.assertEqual(code, 200)
        self.assertEqual([row["id"] for row in payload["tasks"]], [self.task_id])
        self.assertEqual(payload["tasks"][0]["reviewer_ref"], REVIEWER)
        self.assertEqual(payload["tasks"][0]["review_status"], "waiting")


if __name__ == "__main__":
    unittest.main()
