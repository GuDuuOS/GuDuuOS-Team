"""任务鉴权（_can_access_task / _is_task_assignee）回归测试。

守住红线：被指派者「看得到 == 改得动」——可见性放行了派给本人的任务，改状态(点「开始」)
也必须放行，否则线上会 403（本次修复的正是这个「看得到却点不动」）。同时不能放开越权。
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from cosmac.bots.appservice_bot import CosmacBot
from cosmac.config import CosmacConfig


def _bot() -> CosmacBot:
    bot = CosmacBot(CosmacConfig(llm_provider="echo"))
    # 平台管理员判定 / 房间成员判定都打桩成「否」，隔离出「被指派者」这条通路。
    bot._is_platform_admin = lambda uid: False  # type: ignore
    bot.client = SimpleNamespace(is_joined_member=lambda rid, uid: False)  # type: ignore
    return bot


def _task(**kw):
    base = dict(
        sender="", executor_kind="none", executor_ref="", assignee="", room_id="!r:cosmac.cc"
    )
    base.update(kw)
    return SimpleNamespace(**base)


class TestTaskAccess(unittest.TestCase):
    def test_assignee_full_id_can_update(self) -> None:
        bot = _bot()
        t = _task(executor_kind="human", executor_ref="@duxz02:cosmac.cc")
        self.assertTrue(bot._can_access_task("@duxz02:cosmac.cc", t))

    def test_assignee_bare_localpart_ref_matches_full_user(self) -> None:
        # executor_ref 存的是纯 localpart，登录用户是全 id —— 仍应放行。
        bot = _bot()
        t = _task(executor_kind="human", executor_ref="duxz02")
        self.assertTrue(bot._can_access_task("@duxz02:cosmac.cc", t))

    def test_case_insensitive(self) -> None:
        bot = _bot()
        t = _task(executor_kind="human", executor_ref="@DuxZ02:cosmac.cc")
        self.assertTrue(bot._can_access_task("@duxz02:cosmac.cc", t))

    def test_legacy_assignee_first_word(self) -> None:
        # 旧任务无 executor_ref，按 assignee 首词兜底。
        bot = _bot()
        t = _task(assignee="@duxz02:cosmac.cc 人事经理")
        self.assertTrue(bot._can_access_task("@duxz02:cosmac.cc", t))

    def test_other_user_denied(self) -> None:
        # 不是被指派者、不是下达者、非管理员、非房间成员 → 拒绝（防越权遍历 id）。
        bot = _bot()
        t = _task(executor_kind="human", executor_ref="@liwei:cosmac.cc")
        self.assertFalse(bot._can_access_task("@duxz02:cosmac.cc", t))

    def test_sender_can_update(self) -> None:
        bot = _bot()
        t = _task(sender="@boss:cosmac.cc", executor_kind="human", executor_ref="@liwei:cosmac.cc")
        self.assertTrue(bot._can_access_task("@boss:cosmac.cc", t))

    def test_none_kind_not_assignee(self) -> None:
        # executor_kind=none 且无 assignee → 谁都不是被指派者。
        bot = _bot()
        t = _task()
        self.assertFalse(bot._is_task_assignee("@duxz02:cosmac.cc", t))


if __name__ == "__main__":
    unittest.main()
