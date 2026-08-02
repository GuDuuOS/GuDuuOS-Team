"""管理员手动调整 Token 的目标账号校验回归测试。

覆盖截图中的真实故障：管理员把不完整/错误账号域的 Matrix ID 当作目标，旧代码仍会按
字符串创建钱包，造成“后台有余额、真实用户为 0”。新逻辑必须只允许当前节点中真实存在
的完整用户 ID；Synapse 暂时无法核验时也不能写账。
"""

from __future__ import annotations

import unittest
from typing import Optional

from cosmac.bots.appservice_bot import CosmacBot
from cosmac.config import CosmacConfig
from cosmac.db import init_engine
from cosmac.wallet import WalletStore

ADMIN = "@admin:dev.example"
USER = "@duxz03:dev.example"


class _FakeClient:
    """只实现钱包管理员端点所需的身份核验和用户存在性能力。"""

    def __init__(self, exists: Optional[bool] = True) -> None:
        self.exists = exists
        self.checked: list = []

    def whoami(self, token: str) -> Optional[str]:
        """测试 token ``admin-token`` 映射到平台管理员。"""
        return ADMIN if token == "admin-token" else None

    def user_exists(self, user_id: str) -> Optional[bool]:
        """记录被核验的完整 ID，并返回测试指定的 Synapse 状态。"""
        self.checked.append(user_id)
        return self.exists


def _bot(exists: Optional[bool] = True) -> CosmacBot:
    """构造使用内存数据库的管理员钱包 Bot。"""
    init_engine("sqlite://", create_all=True)
    bot = CosmacBot(
        CosmacConfig(llm_provider="echo", server_name="dev.example")
    )
    client = _FakeClient(exists)
    bot.client = client
    bot.wallet = WalletStore(client, bot.config.control_room_alias, ttl=0)
    bot._is_platform_admin = lambda user_id: user_id == ADMIN  # type: ignore
    return bot


class WalletAdminTargetTests(unittest.TestCase):
    """手动调整前必须把目标收敛到当前节点真实用户。"""

    def test_rejects_wrong_server_without_creating_wallet(self) -> None:
        """写错账号域直接拒绝，并提示当前节点的完整 ID。"""
        bot = _bot()
        code, out = bot.handle_wallet_admin_adjust(
            "admin-token", {"user_id": "@duxz03:dev", "delta": 200}
        )
        self.assertEqual(code, 400)
        self.assertIn(USER, out["error"])
        self.assertEqual(bot.wallet.balance("@duxz03:dev"), 0)
        self.assertEqual(bot.client.checked, [])

    def test_rejects_nonexistent_user_without_creating_wallet(self) -> None:
        """账号域正确但 Synapse 中无此用户时，不得产生孤立余额或流水。"""
        bot = _bot(False)
        code, out = bot.handle_wallet_admin_adjust(
            "admin-token", {"user_id": USER, "delta": 200}
        )
        self.assertEqual(code, 404)
        self.assertIn("用户不存在", out["error"])
        self.assertEqual(bot.wallet.balance(USER), 0)

    def test_stops_when_synapse_cannot_verify_user(self) -> None:
        """用户核验临时失败时 fail-closed，避免网络抖动期间写错账。"""
        bot = _bot(None)
        code, out = bot.handle_wallet_admin_adjust(
            "admin-token", {"user_id": USER, "delta": 200}
        )
        self.assertEqual(code, 503)
        self.assertIn("没有调整余额", out["error"])
        self.assertEqual(bot.wallet.balance(USER), 0)

    def test_valid_existing_user_receives_balance_and_ledger(self) -> None:
        """真实本地用户仍可正常入账，余额和流水使用同一个完整 ID。"""
        bot = _bot(True)
        code, out = bot.handle_wallet_admin_adjust(
            "admin-token",
            {"user_id": USER, "delta": 200, "note": "活动奖励"},
        )
        self.assertEqual(code, 200)
        self.assertEqual(out["balance"], 200)
        self.assertEqual(bot.wallet.balance(USER), 200)
        rows = bot.wallet.ledger(USER)
        self.assertEqual(rows[0]["delta"], 200)
        self.assertEqual(rows[0]["note"], "活动奖励")


if __name__ == "__main__":
    unittest.main()
