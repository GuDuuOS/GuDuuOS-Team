# -*- coding: utf-8 -*-
"""成员查询含「待接受」邀请单测(负责人实报:前端人员列表有待接受的人,AI 查成员漏掉)。

原因:list_room_members 走 /joined_members,只返回**已加入**的人;被邀请还没点接受的
不在其中,AI 因此少报人、还回答"我拿不到邀请状态"。现改用 m.room.member state:
已加入与待接受分组返回,并明确告知模型待接受的人**还没进来**(别当在场成员派活)。

运行:.venv/bin/python -m unittest cosmac.tests.test_members_invited
"""

from __future__ import annotations

import unittest
from cosmac.ai.tools import Toolbox, ToolCall, ToolContext
from cosmac.db import init_engine

ROOM = "!team:h"


class _C:
    """打桩:get_members_with_state 返回 3 已加入 + 1 待接受。"""

    def __init__(self, with_state: bool = True) -> None:
        self.with_state = with_state

    def get_members_with_state(self, room_id):
        if not self.with_state:
            raise RuntimeError("老部署没有这个方法")
        return [
            {"user_id": "@duxz03:h", "display_name": "duxz03", "membership": "join"},
            {"user_id": "@guduu:h", "display_name": "GuDuu OS", "membership": "join"},
            {"user_id": "@duxz:h", "display_name": "duxz", "membership": "join"},
            {"user_id": "@duxz01:h", "display_name": "duxz01", "membership": "invite"},
        ]

    def get_members(self, room_id):
        return [{"user_id": "@duxz03:h", "display_name": "duxz03"}]

    def is_joined_member(self, room_id, user_id):
        return True

    def joined_member_count(self, room_id):
        return 4

    def get_state_event(self, room_id, etype, state_key=""):
        return {"name": "健身打卡大本营"} if etype == "m.room.name" else None

    def joined_rooms(self):
        return [ROOM]


def _run(client: _C) -> str:
    tb = Toolbox(client)
    return tb.execute(
        ToolCall(id="x", name="list_room_members", arguments={"room_id": ROOM}),
        ToolContext(ROOM, "@u:h", is_dm=False),
    )


class TestMembersWithInvited(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)

    def test_lists_joined_and_invited_separately(self) -> None:
        out = _run(_C())
        self.assertIn("已加入 3 人", out)          # 三个已加入
        self.assertIn("duxz01", out)               # 待接受的那位也出现了(此前完全漏掉)
        self.assertIn("尚未接受", out)             # 且明确标注状态
        # 待接受的人不能被算进"已加入"那段
        joined_part = out.split("另有")[0]
        self.assertNotIn("duxz01", joined_part)

    def test_warns_model_not_to_count_invited(self) -> None:
        out = _run(_C())
        self.assertIn("还没真正进入频道", out)     # 明确提醒模型别当在场成员

    def test_falls_back_when_method_missing(self) -> None:
        # 老部署/异常:回退 get_members(只有已加入),仍能答出成员而不是报错
        out = _run(_C(with_state=False))
        self.assertIn("duxz03", out)
        self.assertNotIn("尚未接受", out)


if __name__ == "__main__":
    unittest.main()
