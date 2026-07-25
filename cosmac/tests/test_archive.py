"""专班归档收尾（模块3.5 收尾环节）单元测试：archive_repo / clear_summary / archive_project 工具。

内存 SQLite、零 key；假 client 记录写 state / 发消息。
运行：.venv/bin/python -m unittest cosmac.tests.test_archive
"""

from __future__ import annotations

import unittest

from cosmac.ai.tools import Toolbox, ToolCall, ToolContext
from cosmac.db import init_engine, session_scope
from cosmac.db.archive_repo import create_archive, list_archives
from cosmac.db.memory_repo import clear_summary, get_summary, save_summary
from cosmac.db.models import SCOPE_ROOM
from cosmac.db.task_repo import create_tasks, update_task


class FakeClient:
    def __init__(self) -> None:
        self.states: list = []
        self.sent: list = []

    def set_state_event(self, room_id, etype, content, state_key=""):
        self.states.append((room_id, etype, content))
        return True

    def get_state_event(self, room_id, etype, state_key=""):
        # 归档授权(L9)读 power_levels：把项目负责人 @owner:h 设为管理员(power 100)——
        # 与 assemble_team 建房时把发起人提成 100 一致。
        if etype == "m.room.power_levels":
            return {"users": {"@owner:h": 100}}
        return None

    def send_text(self, room_id, text, txn_id=None):
        self.sent.append((room_id, text))
        return "$e"


class TestArchiveRepo(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)

    def test_create_and_list_scoped(self) -> None:
        with session_scope() as s:
            create_archive(s, room_id="!a:h", goal="做大促", summary="交付了X",
                           tasks=[{"title": "t1", "status": "done"}], done_count=1, total_count=1,
                           archived_by="@u:h")
            create_archive(s, room_id="!b:h", goal="别的项目", summary="y")
        with session_scope() as s:
            rows = list_archives(s, room_ids=["!a:h"])
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].goal, "做大促")
            self.assertEqual(rows[0].done_count, 1)
            self.assertEqual(rows[0].tasks[0]["title"], "t1")
            # 越权防护：空作用域返回空，不泄露别的房间
            self.assertEqual(list_archives(s, room_ids=[]), [])


class TestClearSummary(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)

    def test_clear_removes_memory(self) -> None:
        with session_scope() as s:
            save_summary(s, SCOPE_ROOM, "!r:h", "一段长期记忆")
        with session_scope() as s:
            self.assertEqual(get_summary(s, SCOPE_ROOM, "!r:h"), "一段长期记忆")
            self.assertEqual(clear_summary(s, SCOPE_ROOM, "!r:h"), 1)  # 删了 1 行
        with session_scope() as s:
            self.assertEqual(get_summary(s, SCOPE_ROOM, "!r:h"), "")
            self.assertEqual(clear_summary(s, SCOPE_ROOM, "!r:h"), 0)  # 已无、再删 0


class TestArchiveProjectTool(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)
        self.client = FakeClient()
        self.tb = Toolbox(self.client)
        # !team:h 频道下建两条任务并都标 done
        with session_scope() as s:
            rows = create_tasks(s, goal="双11大促短视频", items=[
                {"title": "写文案", "executor_kind": "human", "executor_ref": "@a:h"},
                {"title": "出图", "executor_kind": "agent", "executor_ref": "designer"},
            ], room_id="!team:h", sender="@owner:h")
            for r in rows:
                update_task(s, r.id, status="done", result="ok")
            # 频道有一段长期记忆，归档后应被清掉
            save_summary(s, SCOPE_ROOM, "!team:h", "项目过程记忆")

    def _exec(self, name, args, room="!team:h"):
        return self.tb.execute(
            ToolCall(id="x", name=name, arguments=args),
            ToolContext(room, "@owner:h"),
        )

    def test_list_shows_completion_and_done_hint(self) -> None:
        out = self._exec("list_room_tasks", {})
        self.assertIn("完成度 2/2", out)
        self.assertIn("archive_project", out)  # 全完成 → 提示归档

    def test_archive_writes_record_clears_memory_marks_state(self) -> None:
        out = self._exec("archive_project", {"summary": "交付了2条短视频"})
        # 归档记录落库
        with session_scope() as s:
            arch = list_archives(s, room_ids=["!team:h"])
            self.assertEqual(len(arch), 1)
            self.assertEqual(arch[0].done_count, 2)
            self.assertEqual(arch[0].total_count, 2)
            self.assertEqual(arch[0].goal, "双11大促短视频")
            self.assertEqual(len(arch[0].tasks), 2)
            # 频道长期记忆已清
            self.assertEqual(get_summary(s, SCOPE_ROOM, "!team:h"), "")
        # 写了『已归档』state 标记
        marks = [c for _r, e, c in self.client.states if e == "cosmac.project.archived"]
        self.assertEqual(len(marks), 1)
        self.assertTrue(marks[0]["archived"])
        # 群里贴了收尾通知
        self.assertTrue(any("已归档" in t for _r, t in self.client.sent))
        # 回灌包含完成度与清理记忆
        self.assertIn("2/2", out)
        self.assertIn("清理频道长期记忆", out)

    def test_archive_empty_room_noop(self) -> None:
        out = self._exec("archive_project", {"summary": "x"}, room="!empty:h")
        self.assertIn("没有任务", out)
        with session_scope() as s:
            self.assertEqual(list_archives(s, room_ids=["!empty:h"]), [])

    def test_archive_targets_room_from_dm(self) -> None:
        # 负责人实报:在私聊里归档某频道,却因 ctx.room_id=私聊房而归档不到真频道。
        # 现在带 room 指明频道 → 归档落到那个频道(不是私聊房)。
        self.client.get_members = lambda rid: [{"user_id": "@owner:h"}]  # type: ignore
        out = self.tb.execute(
            ToolCall(id="x", name="archive_project",
                     arguments={"summary": "收尾", "room": "!team:h"}),
            ToolContext("!dm:h", "@owner:h", is_dm=True),  # 当前是私聊
        )
        self.assertIn("已归档", out)
        with session_scope() as s:
            self.assertEqual(len(list_archives(s, room_ids=["!team:h"])), 1)  # 落到目标频道
            self.assertEqual(list_archives(s, room_ids=["!dm:h"]), [])        # 没误档私聊房
        # state 标记也写在目标频道
        marks = [r for r, e, _c in self.client.states if e == "cosmac.project.archived"]
        self.assertEqual(marks, ["!team:h"])

    def test_dm_without_room_prompts_not_archives(self) -> None:
        # 私聊里不指明频道 → 提示要哪个频道,绝不把私聊当频道归档(会归档不到真频道、还清私聊记忆)
        out = self.tb.execute(
            ToolCall(id="x", name="archive_project", arguments={"summary": "x"}),
            ToolContext("!dm:h", "@owner:h", is_dm=True),
        )
        self.assertIn("哪个频道", out)
        with session_scope() as s:
            self.assertEqual(list_archives(s, room_ids=["!dm:h"]), [])

    def test_non_admin_cannot_archive(self) -> None:
        # L9：频道内普通成员(power<50)不能归档——不会清掉长期记忆，也不落归档记录。
        out = self.tb.execute(
            ToolCall(id="x", name="archive_project", arguments={"summary": "偷偷归档"}),
            ToolContext("!team:h", "@member:h"),  # 非管理员
        )
        self.assertIn("频道管理员", out)
        with session_scope() as s:
            self.assertEqual(list_archives(s, room_ids=["!team:h"]), [])   # 没落档
            self.assertEqual(get_summary(s, SCOPE_ROOM, "!team:h"), "项目过程记忆")  # 记忆没被清


if __name__ == "__main__":
    unittest.main()
