"""工作区挂接（handle_space_adopt：bot 代写 m.space.child）的授权与回退测试。

背景：凭邀请链接加入工作区的普通成员在 Space 里 power=0，自己写不了 m.space.child——
手动「归入」与 AI 建专班自动挂接都失败（线上实报）。改为 bot 代写。
红线：
  - 请求者必须**同时**是 工作区 与 频道 的已加入成员（fail-closed）；
  - bot 直写失败时走 make_room_admin 提权 + join 后重试；
  - 提权也失败 → 502，不假装成功。
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, Optional, Tuple

from cosmac import registration
from cosmac.bots.appservice_bot import CosmacBot
from cosmac.config import CosmacConfig

SPACE = "!space:h"
ROOM = "!room:h"
MEM = "@mem:h"       # 工作区+频道 双料成员（凭链接加入,Space 里 0 级）
OUT = "@out:h"       # 只在频道、不在工作区


class FakeClient:
    def __init__(self) -> None:
        self.tokens = {"tok_mem": MEM, "tok_out": OUT}
        self._members = {SPACE: {MEM}, ROOM: {MEM, OUT}}
        self.state_calls: list = []
        self.joined: list = []
        self.fail_first_state = False   # True=第一次 set_state_event 失败(bot 无权限场景)

    def whoami(self, token: str) -> Optional[str]:
        return self.tokens.get(token)

    def is_joined_member(self, room_id: str, user_id: str) -> bool:
        return user_id in self._members.get(room_id, set())

    def set_state_event(self, room_id, etype, content, state_key="") -> bool:
        self.state_calls.append((room_id, etype, state_key))
        if self.fail_first_state and len(self.state_calls) == 1:
            return False
        return True

    def join_room(self, room_id: str) -> None:
        self.joined.append(room_id)


def _bot() -> CosmacBot:
    bot = CosmacBot(CosmacConfig(llm_provider="echo", server_name="h"))
    bot.client = FakeClient()
    return bot


class TestSpaceAdopt(unittest.TestCase):
    def setUp(self) -> None:
        self._orig = registration.make_room_admin
        self.promoted: list = []

        def _fake(hs_url, room_id, user_id) -> Tuple[int, Dict[str, Any]]:
            self.promoted.append((room_id, user_id))
            return 200, {"ok": True}

        registration.make_room_admin = _fake  # type: ignore
        self.bot = _bot()

    def tearDown(self) -> None:
        registration.make_room_admin = self._orig  # type: ignore

    def test_member_of_both_adopts_directly(self) -> None:
        code, payload = self.bot.handle_space_adopt(
            "tok_mem", {"space_id": SPACE, "room_id": ROOM})
        self.assertEqual(code, 200, payload)
        # 写的是 Space 的 m.space.child,state_key=频道 id
        self.assertEqual(self.bot.client.state_calls[0], (SPACE, "m.space.child", ROOM))
        self.assertEqual(self.promoted, [])   # 直写成功,无需提权

    def test_promote_and_retry_when_bot_lacks_power(self) -> None:
        self.bot.client.fail_first_state = True
        code, _ = self.bot.handle_space_adopt(
            "tok_mem", {"space_id": SPACE, "room_id": ROOM})
        self.assertEqual(code, 200)
        # 提权的是 bot 自己、在 Space 上;提权后 join + 重试写入
        self.assertEqual(self.promoted, [(SPACE, self.bot.config.bot_user_id)])
        self.assertIn(SPACE, self.bot.client.joined)
        self.assertEqual(len(self.bot.client.state_calls), 2)

    def test_non_space_member_rejected(self) -> None:
        code, _ = self.bot.handle_space_adopt(
            "tok_out", {"space_id": SPACE, "room_id": ROOM})
        self.assertEqual(code, 403)
        self.assertEqual(self.bot.client.state_calls, [])

    def test_non_room_member_rejected(self) -> None:
        self.bot.client._members[ROOM] = set()   # 请求者不在频道里
        code, _ = self.bot.handle_space_adopt(
            "tok_mem", {"space_id": SPACE, "room_id": ROOM})
        self.assertEqual(code, 403)

    def test_bad_ids(self) -> None:
        code, _ = self.bot.handle_space_adopt("tok_mem", {"space_id": "x", "room_id": ROOM})
        self.assertEqual(code, 400)


if __name__ == "__main__":
    unittest.main()
