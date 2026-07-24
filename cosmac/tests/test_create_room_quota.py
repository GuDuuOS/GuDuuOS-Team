# -*- coding: utf-8 -*-
"""建群/建专班的 teams 配额单测(负责人实报:免费用户 teams=1 却能反复建专班)。

根因:用户说「建专班」时 AI 常调轻量的 create_room 工具,而它此前不在配额映射里——
既不拦(quota_check)也不扣(quota_consume),成了免费墙旁路。修复:create_room 纳入
teams 配额,与 assemble_team 同一本账。

本测从两个层面锁定:
1. 映射层:bot 的 _TOOL_QUOTA_MAP 必须把 create_room 映到 teams(防回归);
2. 执行层:Toolbox.execute 对 create_room 会先过 quota_check(超额则不建房),
   成功建房后调 quota_consume。

运行:.venv/bin/python -m unittest cosmac.tests.test_create_room_quota
"""

from __future__ import annotations

import unittest
from typing import List, Optional

from cosmac.ai.tools import Toolbox, ToolCall, ToolContext
from cosmac.db import init_engine


class _FakeClient:
    def __init__(self) -> None:
        self.created: List[str] = []

    def create_room(self, name, invitees=None, admins=None):
        self.created.append(name)
        return "!new:h"

    def set_state_event(self, *a, **k):
        return "$e"

    def get_state_event(self, *a, **k):
        return None

    def joined_member_count(self, room_id):
        return 2


class TestCreateRoomQuotaMapping(unittest.TestCase):
    def test_map_has_create_room(self) -> None:
        # 防回归:create_room 必须与 assemble_team 一样计入 teams
        from cosmac.bots.appservice_bot import CosmacBot
        m = CosmacBot._TOOL_QUOTA_MAP
        self.assertEqual(m.get("create_room"), "teams")
        self.assertEqual(m.get("assemble_team"), "teams")


class TestCreateRoomQuotaEnforcement(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)
        self.client = _FakeClient()
        self.tb = Toolbox(self.client)
        self.checked: List[str] = []
        self.consumed: List[str] = []

    def _wire(self, over: Optional[str]) -> None:
        self.tb.quota_check = lambda sender, tool: (self.checked.append(tool) or over)
        self.tb.quota_consume = lambda sender, tool: self.consumed.append(tool)

    def _call(self):
        return self.tb.execute(
            ToolCall(id="x", name="create_room", arguments={"name": "测试专班"}),
            ToolContext("!cur:h", "@u:h", is_dm=True),
        )

    def test_blocked_when_over_quota_does_not_create(self) -> None:
        # teams 超额:execute 先过 quota_check,返回升级文案且**不建房**(旁路被堵)
        self._wire(over="已达专班上限，请升级会员")
        out = self._call()
        self.assertIn("升级", out)
        self.assertIn("create_room", self.checked)       # 确实过了配额检查
        self.assertEqual(self.client.created, [])          # 没建房
        self.assertEqual(self.consumed, [])                # 没扣配额

    def test_allowed_then_consumes(self) -> None:
        # 未超额:建房成功,且在成功路径消费 teams(tool 名 create_room → 映射到 teams)
        self._wire(over=None)
        out = self._call()
        self.assertIn("测试专班", out)
        self.assertEqual(self.client.created, ["测试专班"])
        self.assertIn("create_room", self.consumed)        # 成功后扣了配额


if __name__ == "__main__":
    unittest.main()
