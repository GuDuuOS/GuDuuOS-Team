"""频道认领管理员（handle_channel_claim_admin）的授权回归测试。

守住红线（bot 建的频道里真人主人默认 0 级、改不了房名/配置）：
  - 平台管理员：接管任意频道；
  - 无主频道（除 bot 外无人 ≥50）的成员：可认领为主人；
  - 已有真人管理员的频道：其他成员**不能**抢权（防越权）；
  - 非成员：不能认领。
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, Optional, Tuple

from cosmac import registration
from cosmac.bots.appservice_bot import CosmacBot
from cosmac.config import CosmacConfig

CTRL = "!ctrl:guduu.local"
BOT = "@guduu:guduu.local"          # = CosmacConfig 默认 bot_user_id
ADMIN = "@admin:guduu.local"        # 控制室 100 → 平台管理员
OWNER = "@owner:guduu.local"        # 某频道的真人主人
MEMBER = "@member:guduu.local"      # 频道普通成员
ROOM = "!room:guduu.local"


class FakeClient:
    def __init__(self, room_power_users: Dict[str, int], members: set):
        self._room_power_users = room_power_users
        self._members = members
        self.tokens = {  # access_token → user_id
            "tok_admin": ADMIN,
            "tok_owner": OWNER,
            "tok_member": MEMBER,
        }

    def whoami(self, token: str) -> Optional[str]:
        return self.tokens.get(token)

    def resolve_alias(self, _alias: str) -> Optional[str]:
        return CTRL

    def get_state_event(self, room_id, event_type, _state_key=""):
        if event_type != "m.room.power_levels":
            return None
        if room_id == CTRL:
            # 控制室权限表：只有 ADMIN 是平台管理员（100）
            return {"users": {BOT: 100, ADMIN: 100}}
        # 目标频道权限表
        return {"users": dict(self._room_power_users)}

    def is_joined_member(self, _room_id: str, user_id: str) -> bool:
        return user_id in self._members


def _bot(room_power_users, members) -> CosmacBot:
    bot = CosmacBot(CosmacConfig(llm_provider="echo"))
    bot.client = FakeClient(room_power_users, members)
    return bot


class TestChannelClaimAdmin(unittest.TestCase):
    def setUp(self) -> None:
        # 拦掉真正调 Synapse admin API 的 make_room_admin，记录被提权的人。
        self._orig = registration.make_room_admin
        self.granted: list = []

        def _fake(hs_url, room_id, user_id) -> Tuple[int, Dict[str, Any]]:
            self.granted.append((room_id, user_id))
            return 200, {"ok": True}

        registration.make_room_admin = _fake  # type: ignore

    def tearDown(self) -> None:
        registration.make_room_admin = self._orig  # type: ignore

    def test_platform_admin_takes_over_any_channel(self) -> None:
        # 频道已有主人 OWNER，但平台管理员仍可接管。
        bot = _bot({BOT: 100, OWNER: 100}, {OWNER, ADMIN})
        code, _ = bot.handle_channel_claim_admin("tok_admin", {"room_id": ROOM})
        self.assertEqual(code, 200)
        self.assertEqual(self.granted, [(ROOM, ADMIN)])

    def test_member_claims_ownerless_channel(self) -> None:
        # 无主频道（只有 bot 有权限）→ 成员可认领为主人。
        bot = _bot({BOT: 100}, {OWNER})
        code, _ = bot.handle_channel_claim_admin("tok_owner", {"room_id": ROOM})
        self.assertEqual(code, 200)
        self.assertEqual(self.granted, [(ROOM, OWNER)])

    def test_member_cannot_hijack_owned_channel(self) -> None:
        # 频道已有真人主人 OWNER → 另一个普通成员不能抢权。
        bot = _bot({BOT: 100, OWNER: 100}, {OWNER, MEMBER})
        code, _ = bot.handle_channel_claim_admin("tok_member", {"room_id": ROOM})
        self.assertEqual(code, 403)
        self.assertEqual(self.granted, [])

    def test_non_member_rejected(self) -> None:
        # 非频道成员不能认领。
        bot = _bot({BOT: 100}, set())  # MEMBER 不在成员集
        code, _ = bot.handle_channel_claim_admin("tok_member", {"room_id": ROOM})
        self.assertEqual(code, 403)
        self.assertEqual(self.granted, [])

    def test_bad_room_id(self) -> None:
        bot = _bot({BOT: 100}, {OWNER})
        code, _ = bot.handle_channel_claim_admin("tok_owner", {"room_id": "notaroom"})
        self.assertEqual(code, 400)


if __name__ == "__main__":
    unittest.main()
