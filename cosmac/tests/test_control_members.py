"""控制室成员对齐（_reconcile_control_members）的回归测试。

守住安全红线：
  - 撤销的管理员（power 50、不在期望集）被降权 + 踢出；
  - 所有者(100) 和 bot 自己**永不**被动；
  - 事件来自非控制室时**完全不动手**（防止有人借 bot 之手踢人）。
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, List, Optional, Tuple

from cosmac.bots.appservice_bot import CosmacBot
from cosmac.config import CosmacConfig

# BOT 必须等于 CosmacConfig 默认 bot_user_id（_reconcile 用它跳过自身）。
# 标识仍是 guduu（stage2 随线上 bot 账号迁移一起改 @cosmac）。
CTRL = "!ctrl:guduu.local"
BOT = "@guduu:guduu.local"
OWNER = "@admin:guduu.local"
A = "@a:guduu.local"
B = "@b:guduu.local"


class FakeClient:
    """假 client：记录 set_power_levels / kick 调用，便于断言。"""

    def __init__(self, alias_room: Optional[str], power_users: Dict[str, int]):
        self._alias_room = alias_room
        self._power_users = power_users
        self.set_pl_calls: List[Dict[str, Any]] = []
        self.kicks: List[Tuple[str, str]] = []
        self.kick_ok = True  # 测失败路径时置 False

    def set_displayname(self, *_a, **_k): pass

    def resolve_alias(self, _alias: str) -> Optional[str]:
        return self._alias_room

    def get_state_event(self, _room_id, event_type, _state_key=""):
        if event_type == "m.room.power_levels":
            # 带上一些其它字段，验证对齐时不会被抹掉
            return {"state_default": 50, "users": dict(self._power_users)}
        return None

    def set_power_levels(self, _room_id: str, content: Dict[str, Any]) -> bool:
        self.set_pl_calls.append(content)
        return True

    def kick(self, _room_id: str, user_id: str, reason: str = "") -> bool:
        self.kicks.append((user_id, reason))
        return self.kick_ok

    # —— 「添加」方向（新管理员补齐）用到 ——
    def is_joined_member(self, _room_id: str, _user_id: str) -> bool:
        return False  # 测试里新管理员一律视为未入房 → 应补邀请

    def invite_user(self, _room_id: str, user_id: str) -> bool:
        self.invites = getattr(self, "invites", [])
        self.invites.append(user_id)
        return True


def _bot(alias_room, power_users) -> CosmacBot:
    bot = CosmacBot(CosmacConfig(llm_provider="echo"))
    bot.client = FakeClient(alias_room, power_users)
    return bot


class TestControlMembers(unittest.TestCase):
    def test_new_admin_granted_and_invited(self) -> None:
        # QA 根因回归:B 刚被设为服务器管理员(进了期望集),但控制室里没有 TA 的 power——
        # 旧对齐只删不加,B 永远拿不到控制室写权限(接管频道 403 → 频道技能保存失败)。
        # 现在:对齐要把 B 提到 50 并补邀请;已有成员/owner/bot 都不动、没人被踢。
        bot = _bot(CTRL, {OWNER: 100, BOT: 100, A: 50})
        bot._reconcile_control_members(CTRL, {"admins": [OWNER, A, B]})
        self.assertEqual(len(bot.client.set_pl_calls), 1)
        self.assertEqual(bot.client.set_pl_calls[0]["users"][B], 50)
        self.assertEqual(bot.client.set_pl_calls[0]["users"][A], 50)
        self.assertEqual(getattr(bot.client, "invites", []), [B])
        self.assertEqual(bot.client.kicks, [])

    def test_revoked_admin_removed(self) -> None:
        # B 不在期望集 → 被降权(从 users 删掉) + 踢出；A 保留；owner/bot 不动
        # （owner 本身也是服务器管理员，故在期望集里——真实不变式）
        bot = _bot(CTRL, {OWNER: 100, BOT: 100, A: 50, B: 50})
        bot._reconcile_control_members(CTRL, {"admins": [OWNER, A]})
        self.assertEqual(bot.client.kicks, [(B, "已撤销服务器管理员，移出控制室")])
        # 写回的 power_levels：B 没了，A/owner/bot 还在，其它字段保留
        self.assertEqual(len(bot.client.set_pl_calls), 1)
        new_users = bot.client.set_pl_calls[0]["users"]
        self.assertNotIn(B, new_users)
        self.assertIn(A, new_users)
        self.assertIn(OWNER, new_users)
        self.assertEqual(bot.client.set_pl_calls[0]["state_default"], 50)

    def test_owner_and_bot_never_touched(self) -> None:
        # owner 在期望集(它是服务器管理员)、bot 是基础设施 → 都不动
        bot = _bot(CTRL, {OWNER: 100, BOT: 100})
        bot._reconcile_control_members(CTRL, {"admins": [OWNER]})
        self.assertEqual(bot.client.kicks, [])
        self.assertEqual(bot.client.set_pl_calls, [])

    def test_non_control_room_ignored(self) -> None:
        # 事件来自别的房间（resolve 出来的控制室 != 事件 room_id）→ 一律不动手
        bot = _bot(CTRL, {OWNER: 100, A: 50})
        bot._reconcile_control_members("!evil:guduu.local", {"admins": []})
        self.assertEqual(bot.client.kicks, [])
        self.assertEqual(bot.client.set_pl_calls, [])

    def test_nothing_to_remove_no_write(self) -> None:
        # 所有有权限的人都在期望集 → 不写 power_levels、不踢人
        bot = _bot(CTRL, {OWNER: 100, BOT: 100, A: 50})
        bot._reconcile_control_members(CTRL, {"admins": [OWNER, A]})
        self.assertEqual(bot.client.kicks, [])
        self.assertEqual(bot.client.set_pl_calls, [])

    def test_kick_failure_logged_as_error(self) -> None:
        # #2：踢出失败时必须报 error（被撤销者仍是成员），不能无条件报成功
        bot = _bot(CTRL, {OWNER: 100, BOT: 100, B: 50})
        bot.client.kick_ok = False  # 模拟踢出失败
        with self.assertLogs("cosmac.appservice_bot", level="ERROR") as cm:
            bot._reconcile_control_members(CTRL, {"admins": [OWNER]})
        self.assertTrue(any("移除失败" in m for m in cm.output))
        # 试过踢 B（结果失败），不会谎报已移除
        self.assertEqual([u for u, _ in bot.client.kicks], [B])

    def test_legacy_power_100_admin_warned(self) -> None:
        # #1：power≥100 的遗留管理员 bot 无权移除 → 必须 warning（不静默当 owner 跳过）
        bot = _bot(CTRL, {OWNER: 100, BOT: 100, A: 100})  # A 被旧 bug 设成了 100
        with self.assertLogs("cosmac.appservice_bot", level="WARNING") as cm:
            bot._reconcile_control_members(CTRL, {"admins": [OWNER]})  # 只有 owner 是管理员
        self.assertTrue(any("需重建" in m for m in cm.output))
        # 无权移除 → 不会去踢 A（踢了也是 403）
        self.assertEqual(bot.client.kicks, [])


if __name__ == "__main__":
    unittest.main()
