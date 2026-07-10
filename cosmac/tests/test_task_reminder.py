"""任务时效提醒（定时扫描 + 频道内提醒）的回归测试。

覆盖：
  - task_repo.tasks_needing_reminder：快到期/逾期判定 + 已完成排除 + 位掩码去重；
  - CosmacBot.scan_task_reminders：在任务频道 @负责人发提醒、按位去重、无 room 不发只标记；
  - tools._parse_due_to_ts：日期/日期时间解析。
"""

from __future__ import annotations

import unittest

from cosmac.ai.tools import _parse_due_to_ts
from cosmac.bots.appservice_bot import CosmacBot
from cosmac.config import CosmacConfig
from cosmac.db import init_engine, session_scope
from cosmac.db.task_repo import (
    REMIND_OVERDUE, REMIND_SOON, create_tasks, mark_reminded,
    tasks_needing_reminder,
)

ROOM = "!r:h"
DAY = 86400


def _mk(due_ts, *, status="todo", room=ROOM, kind="human", ref="@a:h", assignee="小李",
        sender="@u:h"):
    with session_scope() as s:
        created = create_tasks(
            s, goal="G", room_id=room, sender=sender,
            items=[{
                "title": "写方案", "assignee": assignee,
                "executor_kind": kind, "executor_ref": ref, "due_ts": due_ts,
            }],
        )
        tid = created[0].id
        if status != "todo":
            from cosmac.db.task_repo import update_task
            update_task(s, tid, status=status)
        return tid


class FakeClient:
    def __init__(self):
        self.sent = []

    def set_displayname(self, *a, **k):
        pass

    def send_text(self, room, text):
        self.sent.append((room, text))


class TestTaskReminder(unittest.TestCase):
    def setUp(self):
        init_engine("sqlite://", create_all=True)

    def test_needing_reminder_selects_soon_and_overdue(self):
        now = 1_000_000
        soon = _mk(now + 3600)          # 1h 后到期 → soon（24h 窗口内）
        overdue = _mk(now - 100)        # 已逾期 → overdue
        _mk(now + 10 * DAY)             # 10天后 → 不提醒
        _mk(now - 100, status="done")   # 逾期但已完成 → 不提醒
        _mk(None)                       # 无截止 → 不提醒
        with session_scope() as s:
            items = tasks_needing_reminder(s, now_ts=now, soon_secs=DAY)
            got = {it["task"].id: it["kind"] for it in items}
        self.assertEqual(got, {soon: "soon", overdue: "overdue"})

    def test_bitmask_dedup(self):
        now = 1_000_000
        tid = _mk(now - 100)  # 逾期
        with session_scope() as s:
            self.assertEqual(len(tasks_needing_reminder(s, now_ts=now, soon_secs=DAY)), 1)
            mark_reminded(s, tid, REMIND_OVERDUE)
        with session_scope() as s:  # 已标记 → 不再提醒
            self.assertEqual(tasks_needing_reminder(s, now_ts=now, soon_secs=DAY), [])

    def test_soon_then_overdue_fires_again(self):
        # 已发过"快到期"的任务，逾期后仍应触发一次"逾期"提醒。
        now = 1_000_000
        tid = _mk(now - 1)
        with session_scope() as s:
            mark_reminded(s, tid, REMIND_SOON)  # 假装之前发过快到期
            items = tasks_needing_reminder(s, now_ts=now, soon_secs=DAY)
        self.assertEqual([it["kind"] for it in items], ["overdue"])

    def test_scan_posts_and_dedups(self):
        import time as _t
        now = int(_t.time())
        _mk(now - 100, ref="@a:h")                       # 逾期 → @a:h
        _mk(now + 3600, kind="none", ref="", assignee="小李")  # 快到期 → 文本标签
        bot = CosmacBot(CosmacConfig(llm_provider="echo"))
        bot.client = FakeClient()
        n = bot.scan_task_reminders()
        self.assertEqual(n, 2)
        joined = "\n".join(t for _, t in bot.client.sent)
        self.assertIn("@a:h", joined)
        self.assertIn("已逾期", joined)
        self.assertIn("将在", joined)  # 快到期文案
        # 都发到了任务频道
        self.assertTrue(all(r == ROOM for r, _ in bot.client.sent))
        # 再扫一次 → 去重，不重复发
        self.assertEqual(bot.scan_task_reminders(), 0)

    def test_no_room_marked_not_sent(self):
        import time as _t
        now = int(_t.time())
        _mk(now - 100, room="")  # 逾期但没挂频道
        bot = CosmacBot(CosmacConfig(llm_provider="echo"))
        bot.client = FakeClient()
        self.assertEqual(bot.scan_task_reminders(), 0)  # 没发
        self.assertEqual(bot.client.sent, [])
        with session_scope() as s:  # 但已标记，避免每轮空扫
            self.assertEqual(tasks_needing_reminder(s, now_ts=now, soon_secs=DAY), [])

    def test_overdue_escalates_to_owner(self):
        # 逾期 → 除 @负责人，还升级 @下达者(owner) + 建议改派，避免任务挂着阻塞他人。
        import time as _t
        now = int(_t.time())
        _mk(now - 100, ref="@a:h", sender="@boss:h")
        bot = CosmacBot(CosmacConfig(llm_provider="echo"))
        bot.client = FakeClient()
        bot.scan_task_reminders()
        msg = bot.client.sent[0][1]
        self.assertIn("@a:h", msg)     # 负责人
        self.assertIn("@boss:h", msg)  # 下达者被升级提醒
        self.assertIn("改派", msg)

    def test_unavailable_assignee_escalates_early(self):
        # 负责人已"不可用"(此处：停用)时，任务**还没逾期**(soon)也提前升级给下达者、注明原因。
        import time as _t
        now = int(_t.time())
        _mk(now + 3600, ref="@a:h", sender="@boss:h")  # 快到期、未逾期
        bot = CosmacBot(CosmacConfig(llm_provider="echo"))
        bot.client = FakeClient()
        bot._deactivated_user_ids = lambda: {"@a:h"}  # type: ignore
        bot.scan_task_reminders()
        msg = bot.client.sent[0][1]
        self.assertIn("账号已停用", msg)
        self.assertIn("@boss:h", msg)  # 提前升级给下达者
        self.assertIn("改派", msg)

    def test_parse_due(self):
        self.assertIsNone(_parse_due_to_ts(""))
        self.assertIsNone(_parse_due_to_ts("下周三"))  # 相对词不解析
        import time as _t
        ts = _parse_due_to_ts("2026-07-15")
        self.assertIsNotNone(ts)
        tm = _t.localtime(ts)
        self.assertEqual((tm.tm_year, tm.tm_mon, tm.tm_mday, tm.tm_hour), (2026, 7, 15, 18))
        ts2 = _parse_due_to_ts("2026-07-15 09:30")
        tm2 = _t.localtime(ts2)
        self.assertEqual((tm2.tm_hour, tm2.tm_min), (9, 30))


if __name__ == "__main__":
    unittest.main()
