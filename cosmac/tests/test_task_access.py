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
        sender="", executor_kind="none", executor_ref="", assignee="", room_id="!r:example.invalid"
    )
    base.update(kw)
    return SimpleNamespace(**base)


class TestTaskAccess(unittest.TestCase):
    def test_assignee_full_id_can_update(self) -> None:
        bot = _bot()
        t = _task(executor_kind="human", executor_ref="@duxz02:example.invalid")
        self.assertTrue(bot._can_access_task("@duxz02:example.invalid", t))

    def test_assignee_bare_localpart_ref_matches_full_user(self) -> None:
        # executor_ref 存的是纯 localpart，登录用户是全 id —— 仍应放行。
        bot = _bot()
        t = _task(executor_kind="human", executor_ref="duxz02")
        self.assertTrue(bot._can_access_task("@duxz02:example.invalid", t))

    def test_case_insensitive(self) -> None:
        bot = _bot()
        t = _task(executor_kind="human", executor_ref="@DuxZ02:example.invalid")
        self.assertTrue(bot._can_access_task("@duxz02:example.invalid", t))

    def test_legacy_assignee_first_word(self) -> None:
        # 旧任务无 executor_ref，按 assignee 首词兜底。
        bot = _bot()
        t = _task(assignee="@duxz02:example.invalid 人事经理")
        self.assertTrue(bot._can_access_task("@duxz02:example.invalid", t))

    def test_other_user_denied(self) -> None:
        # 不是被指派者、不是下达者、非管理员、非房间成员 → 拒绝（防越权遍历 id）。
        bot = _bot()
        t = _task(executor_kind="human", executor_ref="@liwei:example.invalid")
        self.assertFalse(bot._can_access_task("@duxz02:example.invalid", t))

    def test_sender_can_update(self) -> None:
        bot = _bot()
        t = _task(sender="@boss:example.invalid", executor_kind="human", executor_ref="@liwei:example.invalid")
        self.assertTrue(bot._can_access_task("@boss:example.invalid", t))

    def test_none_kind_not_assignee(self) -> None:
        # executor_kind=none 且无 assignee → 谁都不是被指派者。
        bot = _bot()
        t = _task()
        self.assertFalse(bot._is_task_assignee("@duxz02:example.invalid", t))


class TestTaskBoardWindow(unittest.TestCase):
    """#6：平台任务超过 200 条后，「派给我的 / 我下达的」仍必须可见，不被全局窗口挤掉。"""

    def setUp(self) -> None:
        from cosmac.db import init_engine
        init_engine("sqlite://", create_all=True)

    def _bot_for(self, user_id: str) -> CosmacBot:
        bot = CosmacBot(CosmacConfig(llm_provider="echo"))
        bot._is_platform_admin = lambda uid: False  # type: ignore
        bot.client = SimpleNamespace(  # type: ignore
            whoami=lambda tok: user_id if tok == "tok" else None,
            is_joined_member=lambda rid, uid: False,
        )
        return bot

    def test_assigned_task_visible_beyond_200(self) -> None:
        from cosmac.db import session_scope
        from cosmac.db.task_repo import create_tasks
        me = "@alice:h"
        with session_scope() as s:
            # 先造 1 条派给 alice 的老任务(id 最小,会落在"最新 200"窗口之外)
            create_tasks(s, goal="g", items=[
                {"title": "我的老任务", "executor_kind": "human", "executor_ref": me}],
                room_id="!r:h", sender="@boss:h")
            # 再造 250 条别人的新任务，把 alice 的挤出最新 200 窗口
            for i in range(250):
                create_tasks(s, goal="g", items=[
                    {"title": f"别人{i}", "executor_kind": "human", "executor_ref": "@bob:h"}],
                    room_id="!r:h", sender="@bob:h")
        code, payload = self._bot_for(me).handle_tasks_list("tok")
        self.assertEqual(code, 200)
        titles = [t["title"] for t in payload["tasks"]]
        self.assertIn("我的老任务", titles)                       # 旧实现这里会消失
        self.assertFalse(any(x.startswith("别人") for x in titles))  # 不泄漏别人的

    def test_own_created_task_visible_beyond_200(self) -> None:
        # 「我下达的」（sender==本人）同样不能被窗口挤掉
        from cosmac.db import session_scope
        from cosmac.db.task_repo import create_tasks
        me = "@alice:h"
        with session_scope() as s:
            create_tasks(s, goal="g", items=[
                {"title": "我下达的老任务", "executor_kind": "human", "executor_ref": "@carol:h"}],
                room_id="!r:h", sender=me)
            for i in range(250):
                create_tasks(s, goal="g", items=[
                    {"title": f"别人{i}", "executor_kind": "human", "executor_ref": "@bob:h"}],
                    room_id="!r:h", sender="@bob:h")
        code, payload = self._bot_for(me).handle_tasks_list("tok")
        titles = [t["title"] for t in payload["tasks"]]
        self.assertIn("我下达的老任务", titles)


if __name__ == "__main__":
    unittest.main()
