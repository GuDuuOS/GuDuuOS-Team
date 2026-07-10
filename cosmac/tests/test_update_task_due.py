"""update_task 工具支持改**截止日期**的单测（负责人报:AI 说不支持改期、只能重建任务）。

内存 SQLite、零 key。
运行：.venv/bin/python -m unittest cosmac.tests.test_update_task_due
"""

from __future__ import annotations

import unittest
from datetime import datetime

from cosmac.ai.tools import Toolbox, ToolCall, ToolContext, _parse_due_to_epoch
from cosmac.db import init_engine, session_scope
from cosmac.db.task_repo import create_tasks, get_task

ROOM = "!cur:h"


class _C:
    """极简假 client：update_task 工具只用到 DB，不碰 client。"""


class TestParseDue(unittest.TestCase):
    def test_date_only_defaults_to_end_of_day(self) -> None:
        ep = _parse_due_to_epoch("2025-07-11")
        self.assertIsNotNone(ep)
        dt = datetime.fromtimestamp(ep)
        self.assertEqual((dt.year, dt.month, dt.day, dt.hour, dt.minute), (2025, 7, 11, 23, 59))

    def test_date_time(self) -> None:
        ep = _parse_due_to_epoch("2025-07-11 10:00")
        dt = datetime.fromtimestamp(ep)
        self.assertEqual((dt.hour, dt.minute), (10, 0))

    def test_slash_and_t_separators(self) -> None:
        self.assertIsNotNone(_parse_due_to_epoch("2025/07/11"))
        self.assertIsNotNone(_parse_due_to_epoch("2025-07-11T09:30"))

    def test_garbage_returns_none(self) -> None:
        self.assertIsNone(_parse_due_to_epoch("下周三"))
        self.assertIsNone(_parse_due_to_epoch(""))


class TestUpdateTaskDue(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)
        self.tb = Toolbox(_C())
        with session_scope() as s:
            rows = create_tasks(s, goal="g", items=[{"title": "写方案"}], room_id=ROOM, sender="@u:h")
            self.tid = rows[0].id

    def _update(self, args):
        args = {"task_id": self.tid, **args}
        return self.tb.execute(ToolCall(id="x", name="update_task", arguments=args),
                               ToolContext(ROOM, "@u:h"))

    def test_set_due_date(self) -> None:
        out = self._update({"due": "2025-07-11 10:00"})
        self.assertIn("截止改为", out)
        with session_scope() as s:
            dt = datetime.fromtimestamp(get_task(s, self.tid).due_ts)
        self.assertEqual((dt.year, dt.month, dt.day, dt.hour, dt.minute), (2025, 7, 11, 10, 0))

    def test_clear_due_date(self) -> None:
        self._update({"due": "2025-07-11"})
        out = self._update({"due": ""})
        self.assertIn("清除截止日期", out)
        with session_scope() as s:
            self.assertIsNone(get_task(s, self.tid).due_ts)

    def test_bad_due_rejected(self) -> None:
        out = self._update({"due": "随便写的"})
        self.assertIn("看不懂", out)
        with session_scope() as s:
            self.assertIsNone(get_task(s, self.tid).due_ts)  # 没改坏

    def test_due_change_resets_reminded(self) -> None:
        # 改期要重置提醒位（新截止重新算"快到期/逾期"）——update_task 语义,顺带覆盖
        with session_scope() as s:
            get_task(s, self.tid)  # 存在即可
        self._update({"due": "2025-07-11"})
        with session_scope() as s:
            self.assertEqual(get_task(s, self.tid).reminded, 0)


if __name__ == "__main__":
    unittest.main()
