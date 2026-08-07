"""OEM 网页批准宿主更新的文件权限回归测试。"""

from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cosmac.bots.appservice_bot import CosmacBot
from cosmac.node_updates import write_update_approval


class NodeUpdateApprovalTests(unittest.TestCase):
    @staticmethod
    def _bot(user_id: str = "@admin:example.com") -> CosmacBot:
        """构造只包含更新批准接口所需依赖的轻量 Bot，避免启动 HTTP/Matrix。"""
        bot = object.__new__(CosmacBot)
        bot.client = mock.Mock()
        bot.client.whoami.return_value = user_id
        bot._is_platform_admin = lambda candidate: candidate == user_id
        return bot

    def test_writes_without_chmod_on_host_owned_parent(self) -> None:
        """只有组写权限时也不得尝试 chmod 宿主目录。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "shared" / "approved-update.json"
            target.parent.mkdir(mode=0o770)
            # 旧实现会调用 os.chmod(parent)；模拟该操作被宿主拒绝，新的文件写入
            # 仍应成功，因为创建/替换文件并不要求当前进程拥有父目录。
            with mock.patch("cosmac.node_updates.os.chmod", side_effect=PermissionError):
                write_update_approval(str(target), 33, "@admin:example.com")

            self.assertEqual(
                json.loads(target.read_text(encoding="utf-8")),
                {"release_id": 33, "approved_by": "@admin:example.com"},
            )
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o660)

    def test_replaces_previous_approval_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "approved-update.json"
            target.write_text('{"release_id":32}', encoding="utf-8")
            write_update_approval(str(target), 34, "@owner:example.com")
            self.assertEqual(json.loads(target.read_text())["release_id"], 34)
            self.assertEqual(
                list(Path(temp_dir).glob(".approved-update-*")), []
            )

    def test_handler_writes_current_admin_as_approver(self) -> None:
        """网页批准必须用当前 token 对应的管理员，且一次请求只解析一次身份。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            pending = Path(temp_dir) / "pending-update.json"
            approved = Path(temp_dir) / "approved-update.json"
            pending.write_text('{"release_id":302}', encoding="utf-8")
            bot = self._bot("@release-admin:example.com")
            with mock.patch.dict(
                os.environ,
                {
                    "COSMAC_PENDING_UPDATE_PATH": str(pending),
                    "COSMAC_APPROVED_UPDATE_PATH": str(approved),
                },
            ):
                code, payload = bot.handle_node_update_approve(
                    "valid-token", {"release_id": 302}
                )

            self.assertEqual(code, 200)
            self.assertTrue(payload["approved"])
            self.assertEqual(
                json.loads(approved.read_text(encoding="utf-8"))["approved_by"],
                "@release-admin:example.com",
            )
            bot.client.whoami.assert_called_once_with("valid-token")

    def test_handler_does_not_disguise_code_bug_as_permission_error(self) -> None:
        """NameError 等程序缺陷必须明确报程序异常，不能误导客户调整目录权限。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            pending = Path(temp_dir) / "pending-update.json"
            pending.write_text('{"release_id":303}', encoding="utf-8")
            bot = self._bot()
            with mock.patch.dict(
                os.environ,
                {"COSMAC_PENDING_UPDATE_PATH": str(pending)},
            ), mock.patch(
                "cosmac.node_updates.write_update_approval",
                side_effect=NameError("simulated code bug"),
            ):
                code, payload = bot.handle_node_update_approve(
                    "valid-token", {"release_id": 303}
                )

            self.assertEqual(code, 500)
            self.assertIn("程序异常", payload["error"])
            self.assertNotIn("权限", payload["error"])

    def test_handler_keeps_real_permission_error_actionable(self) -> None:
        """真正的 PermissionError 仍给出目录权限提示，便于宿主管理员处理。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            pending = Path(temp_dir) / "pending-update.json"
            pending.write_text('{"release_id":304}', encoding="utf-8")
            bot = self._bot()
            with mock.patch.dict(
                os.environ,
                {"COSMAC_PENDING_UPDATE_PATH": str(pending)},
            ), mock.patch(
                "cosmac.node_updates.write_update_approval",
                side_effect=PermissionError("read-only"),
            ):
                code, payload = bot.handle_node_update_approve(
                    "valid-token", {"release_id": 304}
                )

            self.assertEqual(code, 500)
            self.assertIn("权限", payload["error"])


if __name__ == "__main__":
    unittest.main()
