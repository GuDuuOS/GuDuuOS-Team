"""邀请成员的状态校验（负责人实报：AI 邀了停用账号、还建议拉群主本人入群）。

覆盖三条防线：
  ① create_room 建群时 invitees **过滤停用账号**（此前只有 assemble_team 过滤，建群这条漏了）；
  ② invite_to_room 的 _invite_precheck 拦 自己/已在群/停用；
  ③ list_room_members 输出**标注停用**——AI 在自由回复里推荐人选前就能看见状态。

内存 SQLite、零 key、假 client。
运行：.venv/bin/python -m unittest cosmac.tests.test_invite_guard
"""

from __future__ import annotations

import unittest

from cosmac.ai.tools import Toolbox, ToolContext
from cosmac.db import init_engine

SENDER = "@duxz:h"
DEAD = "@chengsp:h"      # 已停用
LIVE = "@duxz03:h"       # 正常


class FakeClient:
    """只实现被测路径用到的方法。"""

    def __init__(self, joined=()):
        self.created: list = []
        self.invited: list = []
        self._joined = set(joined)
        self.members = []

    def create_room(self, name, invitees=None, admins=None):
        self.created.append((name, list(invitees or []), admins))
        return "!new:h"

    def invite_user(self, room_id, user_id):
        self.invited.append(user_id)
        return True

    def invite_user_status(self, room_id, user_id):
        self.invited.append(user_id)
        return True, 200, ""

    def is_joined_member(self, room_id, user_id):
        return user_id in self._joined

    def get_members_with_state(self, room_id):
        return list(self.members)

    def set_state_event(self, *a, **k):
        return True

    def send_text(self, *a, **k):
        return "$e"


def _toolbox(client, inactive=(DEAD,)):
    tb = Toolbox(client)
    tb.inactive_users = lambda: set(inactive)
    return tb


class CreateRoomInviteFilterTest(unittest.TestCase):
    """① 建群时过滤停用账号——本次修复的核心缺口。"""

    def setUp(self):
        init_engine("sqlite://", create_all=True)
        self.client = FakeClient()
        self.tb = _toolbox(self.client)
        self.ctx = ToolContext(room_id="!dm:h", sender=SENDER, is_dm=True)

    def test_deactivated_invitee_is_dropped(self):
        out = self.tb._tool_create_room(
            {"name": "窝沟封闭通知", "invitees": [LIVE, DEAD]}, self.ctx
        )
        _, invitees, _ = self.client.created[0]
        self.assertIn(LIVE, invitees)
        self.assertNotIn(DEAD, invitees)      # 停用的不该被邀
        self.assertIn(SENDER, invitees)       # 发起人(群主)必须在
        self.assertIn("已停用", out)           # 如实告知,不静默吞掉
        self.assertIn(DEAD, out)

    def test_sender_never_filtered_even_if_flagged(self):
        """发起人是群主,即便被误标停用也不能过滤——否则建出一个自己都不在的房。"""
        tb = _toolbox(self.client, inactive=(SENDER, DEAD))
        tb._tool_create_room({"name": "x", "invitees": [DEAD]}, self.ctx)
        _, invitees, _ = self.client.created[0]
        self.assertIn(SENDER, invitees)

    def test_fail_open_when_status_unavailable(self):
        """查不到停用集时不过滤（宁可多邀一个，也不能因抖动建不成群）。"""
        tb = Toolbox(self.client)
        tb.inactive_users = None
        tb._tool_create_room({"name": "y", "invitees": [DEAD]}, self.ctx)
        _, invitees, _ = self.client.created[0]
        self.assertIn(DEAD, invitees)

    def test_normal_invitees_untouched(self):
        self.tb._tool_create_room({"name": "z", "invitees": [LIVE]}, self.ctx)
        out_name, invitees, _ = self.client.created[0]
        self.assertEqual(sorted(invitees), sorted([SENDER, LIVE]))


class InvitePrecheckTest(unittest.TestCase):
    """② 单个邀请的三种拦截。"""

    def setUp(self):
        init_engine("sqlite://", create_all=True)
        self.client = FakeClient(joined={LIVE})
        self.tb = _toolbox(self.client)
        self.ctx = ToolContext(room_id="!r:h", sender=SENDER, is_dm=False)

    def test_blocks_self(self):
        msg = self.tb._invite_precheck("!r:h", SENDER, self.ctx)
        self.assertIsNotNone(msg)
        self.assertIn("你自己", msg)

    def test_blocks_already_joined(self):
        msg = self.tb._invite_precheck("!r:h", LIVE, self.ctx)
        self.assertIsNotNone(msg)
        self.assertIn("已经在这个群里", msg)

    def test_blocks_deactivated(self):
        msg = self.tb._invite_precheck("!r:h", DEAD, self.ctx)
        self.assertIsNotNone(msg)
        self.assertIn("已停用", msg)

    def test_allows_normal_outsider(self):
        self.assertIsNone(self.tb._invite_precheck("!r:h", "@new:h", self.ctx))


class MemberListMarksInactiveTest(unittest.TestCase):
    """③ 成员列表标注停用——让 AI 建议人选前就看得见。"""

    def setUp(self):
        init_engine("sqlite://", create_all=True)
        self.client = FakeClient()
        self.client.members = [
            {"user_id": SENDER, "display_name": "duxz", "membership": "join"},
            {"user_id": DEAD, "display_name": "chengsp", "membership": "invite"},
            {"user_id": LIVE, "display_name": "duxz03", "membership": "join"},
        ]
        self.tb = _toolbox(self.client)
        self.ctx = ToolContext(room_id="!r:h", sender=SENDER, is_dm=False)

    def test_marks_deactivated_and_pending(self):
        out = self.tb._tool_list_members({}, self.ctx)
        # 停用者被标注（它同时是"待接受"——正是负责人截图里的那种死条目）
        self.assertIn("已停用", out)
        self.assertIn("待接受", out)
        # 正常成员不该被误标
        line = [ln for ln in out.splitlines() if LIVE in ln][0]
        self.assertNotIn("已停用", line)


if __name__ == "__main__":
    unittest.main()
