# -*- coding: utf-8 -*-
"""任务派给频道外真人时的自动邀请单测（负责人 dev 实测报告，2026-07-31）。

场景：中枢 AI 在私人会话（全局模式）拆任务时，能力名册给的是全局名册，AI 把任务
派给了不在该频道的 duxz01——任务落库了，但 TA 侧边栏看不到频道、频道成员里也查
无此人，任务悬空没人知道。

修复口径（服务端兜底，不靠提示词）：
- create_tasks / update_task 派单给真人后，逐个检查执行者与 assignee 挂名真人，
  不在任务所属频道的**自动邀请**进来（_ensure_task_humans_in_room）；
- 裸 localpart（"duxz01"）归一成完整 id（@duxz01:<domain>），@ 通知不再静默跳过；
- 私聊/AI 会话房里拆的任务没有频道可邀 → 返回提醒文本让模型转告用户。

内存 SQLite、零 key。运行：.venv/bin/python -m unittest cosmac.tests.test_task_invite
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from cosmac.ai.tools import Toolbox, ToolCall, ToolContext
from cosmac.db import init_engine


class _Client:
    """最小 Matrix 客户端桩：频道房 + 可配置成员 + 记录邀请/发言。"""

    def __init__(self, members=None, ai_room=False, invite_ok=True):
        self.members = members if members is not None else [
            {"user_id": "@boss:h"}, {"user_id": "@inroom:h"},
        ]
        self.ai_room = ai_room
        self.invite_ok = invite_ok
        self.invited = []   # [(room_id, user_id)]
        self.sent = []      # [(room_id, text)]
        self.homeserver_url = "https://matrix.test"

    def resolve_alias(self, a):
        return "!ctrl:h"

    def get_state_event(self, room, etype, key=""):
        # ai_room=True 时打 cosmac.ai_session 标 → _room_kind 判成 "ai"(私聊会话)
        if etype == "cosmac.ai_session" and self.ai_room:
            return {}
        return None

    def get_members(self, room):
        return self.members

    def get_members_with_state(self, room):
        return [dict(m, membership=m.get("membership", "join")) for m in self.members]

    def is_joined_member(self, room, uid):
        return any(m.get("user_id") == uid for m in self.members)

    def invite_user_status(self, room, uid):
        self.invited.append((room, uid))
        return (True, 0, "") if self.invite_ok else (False, 403, "no permission")

    def send_text(self, room, text):
        self.sent.append((room, text))


def _create(tb: Toolbox, tasks, room="!team:h", sender="@boss:h"):
    return tb.execute(
        ToolCall(id="x", name="create_tasks",
                 arguments={"goal": "测试目标", "tasks": tasks}),
        ToolContext(room, sender),
    )


class TestCreateTasksAutoInvite(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)

    @patch("cosmac.registration.admin_join_room", return_value=(200, {"ok": True}))
    def test_outsider_human_gets_invited_and_joined(self, admin_join) -> None:
        """核心回归：派给频道外真人后邀请并立即 join，不再停在待接受。"""
        c = _Client()
        tb = Toolbox(c)
        out = _create(tb, [{
            "title": "科普内容审核",
            "executor_kind": "human", "executor_ref": "duxz01",
        }])
        # 自动邀请:归一成 @duxz01:h 邀进任务所在频道
        self.assertIn(("!team:h", "@duxz01:h"), c.invited)
        admin_join.assert_called_once_with("https://matrix.test", "!team:h", "@duxz01:h")
        self.assertIn("已自动加入", out)
        # @ 通知也发了(此前裸 localpart 不带 @ 会静默跳过)
        self.assertTrue(any("@duxz01:h" in t for _, t in c.sent), c.sent)

    def test_member_not_reinvited(self) -> None:
        """已在频道的执行者不重复邀请。"""
        c = _Client()
        tb = Toolbox(c)
        out = _create(tb, [{
            "title": "写文案",
            "executor_kind": "human", "executor_ref": "@inroom:h",
        }])
        self.assertEqual(c.invited, [])
        self.assertNotIn("已自动邀请", out)

    def test_nonmember_reviewer_falls_back_to_channel_sender(self) -> None:
        """审核人不在频道成员里时，不得再创建一张“假人审”卡片。"""
        from cosmac.db import session_scope
        from cosmac.db.task_repo import list_tasks

        c = _Client()
        tb = Toolbox(c)
        _create(tb, [{
            "title": "真人验收",
            "executor_kind": "agent",
            "executor_ref": "copywriter",
            "reviewer_ref": "@missing:h",
        }])
        with session_scope() as session:
            task = list_tasks(session, room_ids=["!team:h"])[0]
            self.assertEqual(task.reviewer_ref, "@boss:h")
            self.assertEqual(task.review_status, "waiting")

    def test_co_assignee_in_assignee_field_invited(self) -> None:
        """截图原样场景：AI 执行(agent) + assignee 挂真人 → 挂名真人也要被邀请。"""
        c = _Client()
        tb = Toolbox(c)
        with patch("cosmac.registration.admin_join_room", return_value=(200, {"ok": True})):
            _create(tb, [{
                "title": "三伏贴科普与临床证据审核",
                "executor_kind": "agent", "executor_ref": "copywriter",
                "assignee": "文案+duxz01",
            }])
        self.assertIn(("!team:h", "@duxz01:h"), c.invited)

    @patch("cosmac.registration.admin_join_room", return_value=(200, {"ok": True}))
    def test_existing_pending_invite_is_promoted_without_reinvite(self, admin_join) -> None:
        """旧版遗留的 invite 状态直接推进为 join，不要把重复邀请当前置条件。"""
        c = _Client(members=[
            {"user_id": "@boss:h", "membership": "join"},
            {"user_id": "@duxz01:h", "membership": "invite"},
        ])
        tb = Toolbox(c)
        out = _create(tb, [{
            "title": "存量任务", "executor_kind": "human", "executor_ref": "duxz01",
        }])
        self.assertEqual(c.invited, [])
        admin_join.assert_called_once_with("https://matrix.test", "!team:h", "@duxz01:h")
        self.assertIn("已自动加入", out)

    def test_ai_room_human_assignment_is_rejected_before_insert(self) -> None:
        """私聊派给第三人必须整批拒绝，强制走建频道+拉人的专班链路。"""
        c = _Client(ai_room=True)
        tb = Toolbox(c)
        out = _create(tb, [{
            "title": "复盘", "executor_kind": "human", "executor_ref": "duxz01",
        }], room="!aichat:h")
        self.assertEqual(c.invited, [])
        self.assertIn("本次没有登记任何任务", out)
        self.assertIn("assemble_team", out)
        from cosmac.db import session_scope
        from cosmac.db.task_repo import list_tasks
        with session_scope() as s:
            self.assertEqual(list_tasks(s, room_ids=["!aichat:h"]), [])

    def test_ai_room_agent_only_task_remains_allowed(self) -> None:
        """私人会话仍允许用户自己/AI 待办，不要误伤轻量 create_tasks 场景。"""
        c = _Client(ai_room=True)
        tb = Toolbox(c)
        out = _create(tb, [{
            "title": "AI 汇总资料", "executor_kind": "agent", "executor_ref": "analyst",
        }], room="!aichat:h")
        self.assertIn("登记到「任务看板」", out)
        from cosmac.db import session_scope
        from cosmac.db.task_repo import list_tasks
        with session_scope() as s:
            self.assertEqual(len(list_tasks(s, room_ids=["!aichat:h"])), 1)

    def test_invite_failure_reported(self) -> None:
        """邀请失败必须如实回报(带真实原因)，让模型转告用户改派或找管理员。"""
        c = _Client(invite_ok=False)
        tb = Toolbox(c)
        # _promote_bot_in_room 依赖 admin 通道,桩里没有 → 提权失败,保持原始 403
        tb._promote_bot_in_room = lambda room: False  # type: ignore
        out = _create(tb, [{
            "title": "审核", "executor_kind": "human", "executor_ref": "duxz01",
        }])
        self.assertIn("邀请失败", out)
        self.assertIn("403", out)

    @patch(
        "cosmac.registration.admin_join_room",
        return_value=(503, {"error": "服务器未配置管理员令牌"}),
    )
    def test_join_failure_keeps_invite_and_reports_pending(self, _admin_join) -> None:
        """join 失败不得谎报已入频道；标准邀请仍保留作为降级路径。"""
        c = _Client()
        tb = Toolbox(c)
        out = _create(tb, [{
            "title": "审核", "executor_kind": "human", "executor_ref": "duxz01",
        }])
        self.assertIn(("!team:h", "@duxz01:h"), c.invited)
        self.assertIn("自动加入失败", out)
        self.assertIn("待接受状态", out)

    def test_noise_words_not_invited(self) -> None:
        """assignee 里的噪音词(AI 等)不能被当账号去邀请。"""
        c = _Client()
        tb = Toolbox(c)
        _create(tb, [{
            "title": "写脚本", "executor_kind": "agent", "executor_ref": "social",
            "assignee": "社媒运营 + AI",
        }])
        self.assertEqual(c.invited, [])


class TestUpdateTaskReassignInvite(unittest.TestCase):
    """改派路径同口径：update_task 改派给频道外真人 → 邀进**任务所属房**。"""

    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)
        self.c = _Client()
        self.tb = Toolbox(self.c)
        _create(self.tb, [{
            "title": "初稿", "executor_kind": "agent", "executor_ref": "copywriter",
        }])
        # 从返回里拿不到 id,直接查库
        from cosmac.db import session_scope
        from cosmac.db.task_repo import list_tasks
        with session_scope() as s:
            self.tid = list_tasks(s, room_ids=["!team:h"])[0].id

    @patch("cosmac.registration.admin_join_room", return_value=(200, {"ok": True}))
    def test_reassign_to_outsider_invites_into_task_room(self, admin_join) -> None:
        # 在**另一个房间**发起改派——邀请必须落在任务自己的房(!team:h),不是发起房。
        # 真实环境 bot 注入 can_access_task(下达者放行);桩里注入同语义回调,
        # 否则会回落到"必须同房"的兜底口径把改派本身拦掉。
        self.tb.can_access_task = lambda uid, t: uid == "@boss:h"
        out = self.tb.execute(
            ToolCall(id="y", name="update_task", arguments={
                "task_id": self.tid,
                "executor_kind": "human", "executor_ref": "duxz01",
            }),
            ToolContext("!other:h", "@boss:h"),
        )
        self.assertIn(("!team:h", "@duxz01:h"), self.c.invited)
        admin_join.assert_called_once_with("https://matrix.test", "!team:h", "@duxz01:h")
        self.assertIn("已自动加入", out)


if __name__ == "__main__":
    unittest.main()
