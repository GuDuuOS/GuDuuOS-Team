# -*- coding: utf-8 -*-
"""主 AI 代 AI 同事发言单测(负责人实报:三个 Agent 写的内容全署名主AI)。

背景:任务自动执行链路一直以傀儡身份发(频道里显示「文案」在说话);但主 AI 在**对话里
代写**内容时只有 send_message_to_room,没有"以谁的身份发"的选项,只能署名主AI。
现加 as_agent 参数:拉傀儡进房→以其身份发;傀儡不可用/发失败**退回主AI身份**,绝不丢消息,
且返回文案如实说明实际署名(防模型对用户宣称"已以 XX 名义发出"而其实没有)。

运行:.venv/bin/python -m unittest cosmac.tests.test_send_as_agent
"""

from __future__ import annotations

import unittest
from typing import List, Optional, Tuple

from cosmac.ai.tools import Toolbox, ToolCall, ToolContext
from cosmac.db import init_engine

ROOM = "!team:h"


class _C:
    def __init__(self, as_ok: bool = True) -> None:
        self.as_ok = as_ok
        self.sent_plain: List[Tuple[str, str]] = []
        self.sent_as: List[Tuple[str, str, str]] = []

    def send_text(self, room_id, text, txn_id=None):
        self.sent_plain.append((room_id, text))
        return "$plain"

    def send_text_as(self, room_id, text, as_user, txn_id=None):
        if not self.as_ok:
            return None            # 模拟傀儡发送失败(如不在房/权限)
        self.sent_as.append((room_id, text, as_user))
        return "$as"

    def get_state_event(self, room_id, etype, state_key=""):
        if etype == "m.room.name":
            return {"name": "健身打卡大本营"}
        return None

    def is_joined_member(self, room_id, user_id):
        return True

    def joined_member_count(self, room_id):
        return 5

    def joined_rooms(self):
        return [ROOM]


def _tb(client: _C, puppet: Optional[str] = "@guduu-ai-copywriter:h") -> Toolbox:
    tb = Toolbox(client)
    # bot 注入的傀儡入房回调:返回傀儡 MXID(空串=拉不进/建不了)
    tb.ensure_worker_in_room = lambda room, slug: (puppet or "")  # type: ignore
    return tb


def _call(tb: Toolbox, **args) -> str:
    return tb.execute(
        ToolCall(id="x", name="send_message_to_room", arguments=dict(args)),
        ToolContext(ROOM, "@u:h", is_dm=False),
    )


class TestSendAsAgent(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)

    def test_sends_as_agent_when_given(self) -> None:
        c = _C()
        out = _call(_tb(c), text="开营帖内容", room_id=ROOM, as_agent="copywriter")
        self.assertEqual(len(c.sent_as), 1)                 # 走了傀儡身份
        self.assertEqual(c.sent_as[0][2], "@guduu-ai-copywriter:h")
        self.assertEqual(c.sent_plain, [])                  # 没有重复用主AI再发一条
        self.assertIn("copywriter", out)                    # 回报里说明了署名

    def test_defaults_to_main_ai_without_as_agent(self) -> None:
        c = _C()
        _call(_tb(c), text="普通通知", room_id=ROOM)
        self.assertEqual(len(c.sent_plain), 1)              # 不填 as_agent = 主AI身份
        self.assertEqual(c.sent_as, [])

    def test_falls_back_when_puppet_unavailable(self) -> None:
        # 傀儡建不了/拉不进房 → 退回主AI身份发,消息绝不丢
        c = _C()
        out = _call(_tb(c, puppet=""), text="日报", room_id=ROOM, as_agent="analyst")
        self.assertEqual(len(c.sent_plain), 1)
        self.assertEqual(c.sent_as, [])
        self.assertIn("未能以", out)                         # 如实告知没能代发

    def test_falls_back_when_send_as_fails(self) -> None:
        # 傀儡在房但 send_text_as 失败(403 等) → 同样退回主AI身份
        c = _C(as_ok=False)
        out = _call(_tb(c), text="互动帖", room_id=ROOM, as_agent="social")
        self.assertEqual(len(c.sent_plain), 1)
        self.assertIn("未能以", out)

    def test_no_worker_hook_still_works(self) -> None:
        # 未注入 ensure_worker_in_room(如单测/精简部署):照常以主AI发,不报错
        c = _C()
        tb = Toolbox(c)
        _call(tb, text="内容", room_id=ROOM, as_agent="copywriter")
        self.assertEqual(len(c.sent_plain), 1)


if __name__ == "__main__":
    unittest.main()
