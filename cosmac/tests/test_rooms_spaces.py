# -*- coding: utf-8 -*-
"""频道清单按工作区分组单测(负责人实报:AI 不知道频道属于哪个工作区,只能猜)。

真相在 Space 房间的 m.space.child state 里,bot 通常不在用户工作区房 → 走管理员
API(admin_room_state)读。本测打桩管理员通道,验证:
1. 有管理员通道:输出按「工作区名」分组,孤儿频道归未归类,Space 本身不当频道列;
2. 无管理员通道:回退平铺并自报"工作区归属信息暂不可用"。

内存打桩、零网络。运行:.venv/bin/python -m unittest cosmac.tests.test_rooms_spaces
"""

from __future__ import annotations

import unittest

from cosmac.ai.tools import Toolbox, ToolCall, ToolContext


class SpacedClient:
    """打桩 client:1 个工作区(物业,含 2 频道) + 1 个孤儿频道 + AI 会话房。"""

    SPACE = "!space-wuye:h"
    CH_A = "!ch-chouqu:h"     # 车位抽取(在工作区)
    CH_B = "!ch-zhuaban:h"    # 车位抓阄执行专班(在工作区)
    CH_ORPHAN = "!ch-orphan:h"  # 雅诗兰黛测评组(孤儿)
    AI_ROOM = "!ai:h"

    NAMES = {
        CH_A: "车位抽取", CH_B: "车位抓阄执行专班",
        CH_ORPHAN: "雅诗兰黛测评组", SPACE: "物业",
    }

    def joined_rooms(self):
        # bot 进驻了所有频道+AI 会话房(不在 Space 里——真实情形)
        return [self.CH_A, self.CH_B, self.CH_ORPHAN, self.AI_ROOM]

    def admin_user_joined_rooms(self, user_id):
        # 管理员视角:用户在工作区房+全部频道
        return [self.SPACE, self.CH_A, self.CH_B, self.CH_ORPHAN, self.AI_ROOM]

    def admin_room_state(self, room_id):
        if room_id == self.SPACE:
            return [
                {"type": "m.room.create", "content": {"type": "m.space"}},
                {"type": "m.room.name", "content": {"name": "物业"}},
                {"type": "m.space.child", "state_key": self.CH_A,
                 "content": {"via": ["h"]}},
                {"type": "m.space.child", "state_key": self.CH_B,
                 "content": {"via": ["h"]}},
            ]
        # 普通房:create 无 space 标记(读到 create 即 break)
        return [{"type": "m.room.create", "content": {}}]

    def admin_room_name(self, room_id):
        return self.NAMES.get(room_id, "")

    def get_state_event(self, room_id, etype, state_key=""):
        if etype == "m.room.name":
            n = self.NAMES.get(room_id)
            return {"name": n} if n else None
        if etype == "cosmac.ai_session" and room_id == self.AI_ROOM:
            return {"kind": "ai"}
        return None

    def is_joined_member(self, room_id, user_id):
        return True


class NoAdminClient(SpacedClient):
    """同上但管理员通道不可用(没配 token / 失效)——必须回退平铺不硬报。"""

    def admin_user_joined_rooms(self, user_id):
        return None

    def admin_room_state(self, room_id):
        return None

    def admin_room_name(self, room_id):
        return None


class TestRoomsGroupedBySpace(unittest.TestCase):
    def _run(self, client) -> str:
        tb = Toolbox(client)
        return tb.execute(
            ToolCall(id="x", name="list_my_rooms", arguments={}),
            ToolContext("!cur:h", "@alice:h", is_dm=True),
        )

    def test_grouped_by_workspace(self) -> None:
        out = self._run(SpacedClient())
        # 分组头:工作区名
        self.assertIn("工作区「物业」", out)
        # 归属频道在组内
        self.assertIn("车位抽取", out)
        self.assertIn("车位抓阄执行专班", out)
        # 孤儿频道归未归类
        self.assertIn("未归类", out)
        self.assertIn("雅诗兰黛测评组", out)
        # 组内顺序:工作区组先于未归类组
        self.assertLess(out.index("物业"), out.index("未归类"))

    def test_space_room_not_listed_as_channel(self) -> None:
        out = self._run(SpacedClient())
        # Space 本身是房间但绝不能当频道列出(会被误当邀人目标)
        self.assertNotIn("!space-wuye:h", out)

    def test_ai_room_excluded(self) -> None:
        out = self._run(SpacedClient())
        self.assertNotIn("!ai:h", out)

    def test_fallback_flat_when_no_admin(self) -> None:
        out = self._run(NoAdminClient())
        # 平铺仍列频道,但明说归属不可用,不装作没有工作区
        self.assertIn("车位抽取", out)
        self.assertIn("工作区归属信息暂不可用", out)
        self.assertNotIn("工作区「", out)


if __name__ == "__main__":
    unittest.main()
