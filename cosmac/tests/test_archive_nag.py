# -*- coding: utf-8 -*-
"""归档催办单测:任务全完成的频道每日提醒频道主归档,直到写下归档标记为止。

负责人需求:AI 口头问"是否归档"被忽略时——完成满 24h 开始催、@频道主、每天一条、
归档后停止。Synapse 交互打桩;任务数据走内存 SQLite。

运行:.venv/bin/python -m unittest cosmac.tests.test_archive_nag
"""

from __future__ import annotations

import time
import unittest
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from cosmac.bots.appservice_bot import CosmacBot
from cosmac.config import CosmacConfig
from cosmac.db import init_engine, session_scope
from cosmac.db.task_repo import create_tasks, rooms_all_tasks_done, update_task

ROOM = "!team:h"
OWNER = "@boss:h"
DAY = 24 * 3600


class _C:
    """打桩 Matrix client:state 存内存 dict;记录发出的消息。"""

    def __init__(self) -> None:
        self.state: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self.sent: List[Tuple[str, str]] = []
        self.set_state_ok = True
        # 频道主 boss=100,普通成员 50,主 AI 100(要被排除),傀儡 50(要被排除)
        self.state[(ROOM, "m.room.power_levels")] = {
            "users": {
                OWNER: 100, "@guduu:h": 100,
                "@guduu-ai-copywriter:h": 50, "@member:h": 50,
            }
        }

    def get_state_event(self, room: str, ev_type: str, state_key: str = "") -> Optional[Dict[str, Any]]:
        return self.state.get((room, ev_type))

    def set_state_event(self, room: str, ev_type: str, content: Dict[str, Any], state_key: str = "") -> bool:
        if not self.set_state_ok:
            return False
        self.state[(room, ev_type)] = dict(content)
        return True

    def send_text(self, room: str, text: str, **kw) -> str:
        self.sent.append((room, text))
        return "$evt"

    def whoami(self, token: str) -> Optional[str]:
        return "@u:h"

    def resolve_alias(self, alias: str):
        return None

    def set_displayname(self, *a, **k):
        pass


def _bot() -> CosmacBot:
    bot = CosmacBot(CosmacConfig(llm_provider="echo", server_name="h"))
    bot.client = _C()
    return bot


def _seed_tasks(room: str = ROOM, all_done: bool = True, days_ago: float = 2.0) -> None:
    """造一个频道的任务:默认全部完成、最后更新在 days_ago 天前。"""
    with session_scope() as s:
        tasks = create_tasks(
            s, goal="专访项目",
            items=[{"title": "写脚本"}, {"title": "拍摄"}],
            room_id=room, sender=OWNER,
        )
        ids = [t.id for t in tasks]
    with session_scope() as s:
        for tid in ids:
            if all_done:
                update_task(s, task_id=tid, status="done")
        # 把 updated_at 拨回过去,模拟"完成后过了 N 天没人理"
        from cosmac.db.models import Task
        past = datetime.utcnow() - timedelta(days=days_ago)
        for tid in ids:
            s.get(Task, tid).updated_at = past


class TestArchiveNag(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)
        self.bot = _bot()

    def test_repo_rooms_all_done(self) -> None:
        _seed_tasks()
        _seed_tasks(room="!busy:h", all_done=False)  # 有未完成 → 不该出现
        with session_scope() as s:
            rooms = rooms_all_tasks_done(s)
        self.assertEqual([r["room_id"] for r in rooms], [ROOM])
        self.assertEqual(rooms[0]["total"], 2)
        self.assertGreater(rooms[0]["last_update_ts"], 0)

    def test_nag_sent_with_owner_mention(self) -> None:
        """全完成+满24h+未归档 → 发催办、@频道主(排除主AI/傀儡)、写 nag state。"""
        _seed_tasks()
        n = self.bot.scan_archive_nags()
        self.assertEqual(n, 1)
        room, text = self.bot.client.sent[0]
        self.assertEqual(room, ROOM)
        self.assertIn(OWNER, text)                    # @频道主
        self.assertNotIn("@guduu:h", text)            # 主 AI 不 @
        self.assertNotIn("guduu-ai-", text)           # 傀儡不 @
        self.assertIn("归档", text)
        nag = self.bot.client.state[(ROOM, "cosmac.archive.nag")]
        self.assertEqual(nag["count"], 1)

    def test_throttled_within_24h_then_resends(self) -> None:
        """同一天不重复;拨过 24h 再扫 → 第二条,count 递增。"""
        _seed_tasks()
        self.bot.scan_archive_nags()
        self.assertEqual(self.bot.scan_archive_nags(), 0)   # 24h 内不再发
        # 把上次催办时刻拨回 25h 前
        nag = self.bot.client.state[(ROOM, "cosmac.archive.nag")]
        nag["last_ts"] = int(time.time()) - 25 * 3600
        self.assertEqual(self.bot.scan_archive_nags(), 1)
        self.assertEqual(
            self.bot.client.state[(ROOM, "cosmac.archive.nag")]["count"], 2)

    def test_recent_completion_not_nagged(self) -> None:
        """刚完成(不满24h观察窗) → 不催(AI 当场已口头问过)。"""
        _seed_tasks(days_ago=0.5)
        self.assertEqual(self.bot.scan_archive_nags(), 0)

    def test_archived_room_stops(self) -> None:
        """已写归档标记 → 闭环终点,永不再催。"""
        _seed_tasks()
        self.bot.client.state[(ROOM, "cosmac.project.archived")] = {"archived": True}
        self.assertEqual(self.bot.scan_archive_nags(), 0)

    def test_unfinished_room_not_nagged(self) -> None:
        _seed_tasks(all_done=False)
        self.assertEqual(self.bot.scan_archive_nags(), 0)

    def test_state_write_failure_skips_send(self) -> None:
        """nag state 写失败(无权限) → 不发消息——防按扫描间隔(15min)轰炸。"""
        _seed_tasks()
        self.bot.client.set_state_ok = False
        self.assertEqual(self.bot.scan_archive_nags(), 0)
        self.assertEqual(self.bot.client.sent, [])

    def test_owner_fallback_to_admins(self) -> None:
        """没有 power=100 的真人 → 退而 @ ≥50 的管理员。"""
        self.bot.client.state[(ROOM, "m.room.power_levels")] = {
            "users": {"@guduu:h": 100, "@admin2:h": 50, "@member:h": 0}
        }
        _seed_tasks()
        self.bot.scan_archive_nags()
        _, text = self.bot.client.sent[0]
        self.assertIn("@admin2:h", text)
        self.assertNotIn("@member:h", text)


if __name__ == "__main__":
    unittest.main()
