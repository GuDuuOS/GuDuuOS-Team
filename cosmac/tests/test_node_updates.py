"""OEM 网页批准宿主更新的文件权限回归测试。"""

from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cosmac.node_updates import write_update_approval


class NodeUpdateApprovalTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
