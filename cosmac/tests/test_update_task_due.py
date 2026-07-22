"""update_task 工具支持改**截止日期**的单测（负责人报:AI 说不支持改期、只能重建任务）。

内存 SQLite、零 key。
运行：.venv/bin/python -m unittest cosmac.tests.test_update_task_due
"""

from __future__ import annotations

import unittest

from cosmac.ai.tools import (
    Toolbox, ToolCall, ToolContext, _parse_due_to_epoch, _parse_due_to_ts,
)
from cosmac.db import init_engine, session_scope
from cosmac.db.task_repo import create_tasks, get_task

ROOM = "!cur:h"


class _C:
    """极简假 client：update_task 工具只用到 DB，不碰 client。"""


class TestParseDue(unittest.TestCase):
    # 断言用产品时区还原(fmt_ts)而非 datetime.fromtimestamp(测试机时区)——
    # 解析已改按产品时区(北京),UTC 机器上用机器时区断言会差 8 小时(线上 bug 镜像)。
    def test_date_only_defaults_to_end_of_day(self) -> None:
        from cosmac.tzutil import fmt_ts
        ep = _parse_due_to_epoch("2025-07-11")
        self.assertIsNotNone(ep)
        self.assertEqual(fmt_ts(ep, "%Y-%m-%d %H:%M"), "2025-07-11 23:59")

    def test_date_time(self) -> None:
        from cosmac.tzutil import fmt_ts
        ep = _parse_due_to_epoch("2025-07-11 10:00")
        self.assertEqual(fmt_ts(ep, "%H:%M"), "10:00")

    def test_slash_and_t_separators(self) -> None:
        self.assertIsNotNone(_parse_due_to_epoch("2025/07/11"))
        self.assertIsNotNone(_parse_due_to_epoch("2025-07-11T09:30"))

    def test_garbage_returns_none(self) -> None:
        self.assertIsNone(_parse_due_to_epoch("下周三"))
        self.assertIsNone(_parse_due_to_epoch(""))

    def test_create_and_update_due_parsers_agree(self) -> None:
        # L10：建任务(_parse_due_to_ts)与改期(_parse_due_to_epoch)曾各用 18:00/23:59 两套口径，
        # 同一日期解析出的时刻差近 6 小时。现已统一——两者对同一 date-only 输入必须完全一致。
        for d in ("2025-07-11", "2025/12/31", "2026-01-01 09:30"):
            self.assertEqual(_parse_due_to_ts(d), _parse_due_to_epoch(d), d)


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
        from cosmac.tzutil import fmt_ts
        out = self._update({"due": "2025-07-11 10:00"})
        self.assertIn("截止改为", out)
        with session_scope() as s:
            ts = get_task(s, self.tid).due_ts
        self.assertEqual(fmt_ts(ts, "%Y-%m-%d %H:%M"), "2025-07-11 10:00")

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


class _BotClient:
    """打桩 client:whoami 固定回下单人(即有权改)。"""

    def whoami(self, token):
        return "@u:h"

    def resolve_alias(self, alias):
        return None

    def set_displayname(self, *a, **k):
        pass


class TestTaskUpdateEndpointDue(unittest.TestCase):
    """看板改期端点(负责人报:逾期提醒让去看板改期,看板此前不支持)。"""

    def setUp(self) -> None:
        from cosmac.bots.appservice_bot import CosmacBot
        from cosmac.config import CosmacConfig

        init_engine("sqlite://", create_all=True)
        self.bot = CosmacBot(CosmacConfig(llm_provider="echo", server_name="h"))
        self.bot.client = _BotClient()
        with session_scope() as s:
            rows = create_tasks(s, goal="g", items=[{"title": "改期目标"}],
                                room_id=ROOM, sender="@u:h")
            self.tid = rows[0].id

    def test_set_due_via_endpoint(self) -> None:
        code, out = self.bot.handle_task_update("tok", {"id": self.tid, "due": "2026-08-01 18:00"})
        self.assertEqual(code, 200)
        with session_scope() as s:
            self.assertIsNotNone(get_task(s, self.tid).due_ts)

    def test_clear_due_via_endpoint(self) -> None:
        self.bot.handle_task_update("tok", {"id": self.tid, "due": "2026-08-01"})
        code, _ = self.bot.handle_task_update("tok", {"id": self.tid, "due": ""})
        self.assertEqual(code, 200)
        with session_scope() as s:
            self.assertIsNone(get_task(s, self.tid).due_ts)

    def test_bad_due_rejected_400(self) -> None:
        code, out = self.bot.handle_task_update("tok", {"id": self.tid, "due": "下周三"})
        self.assertEqual(code, 400)
        self.assertIn("格式无效", out["error"])


if __name__ == "__main__":
    unittest.main()
