"""Nexus SSH 单次恢复命令的环境边界测试。"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from nexus import recovery_codes


class RecoveryCodeCliTests(unittest.TestCase):
    """确保 CLI 只解析 DB URL，不把 EnvironmentFile 当 shell 执行。"""

    def test_reads_only_database_url_from_systemd_environment_file(self) -> None:
        """带空格的其他配置不影响 DB URL 读取。"""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "nexus.env"
            path.write_text(
                "NEXUS_DATABASE_URL='postgresql://nexus@localhost/nexus'\n"
                "NEXUS_WEBAUTHN_RP_NAME=GuDuu Nexus\n",
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {}, clear=True):
                recovery_codes._load_database_url(str(path))
                self.assertEqual(
                    os.environ["NEXUS_DATABASE_URL"],
                    "postgresql://nexus@localhost/nexus",
                )

    def test_existing_environment_file_must_include_database_url(self) -> None:
        """生产配置存在时禁止静默回退 SQLite。"""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "nexus.env"
            path.write_text("NEXUS_LISTEN_PORT=9100\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(RuntimeError):
                    recovery_codes._load_database_url(str(path))


if __name__ == "__main__":
    unittest.main()
