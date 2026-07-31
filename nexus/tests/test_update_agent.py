"""OEM 宿主自动更新代理的输入安全测试。"""

from __future__ import annotations

import tempfile
import unittest
import importlib.util
from pathlib import Path


# 环境里可能安装了同名第三方 ``distro`` 包；按真实文件路径加载，确保测试的是仓库代码。
_AGENT_PATH = Path(__file__).resolve().parents[2] / "distro" / "update_agent.py"
_AGENT_SPEC = importlib.util.spec_from_file_location("guduu_update_agent", _AGENT_PATH)
assert _AGENT_SPEC is not None and _AGENT_SPEC.loader is not None
update_agent = importlib.util.module_from_spec(_AGENT_SPEC)
_AGENT_SPEC.loader.exec_module(update_agent)


class UpdateAgentTest(unittest.TestCase):
    """验证代理只读取数据，不执行 env 内容，并严格限制版本与 HTTPS。"""

    def test_read_env_does_not_execute_shell(self):
        """特殊字符保持普通文本，非法变量名与注释被忽略。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / ".env"
            path.write_text(
                "# comment\nCOSMAC_NEXUS_URL=https://nexus.example.com\n"
                "COSMAC_OEM_KEY='CMK-AAAA-BBBB-CCCC-DDDD'\n"
                "BAD-NAME=$(touch /tmp/never)\n",
                encoding="utf-8",
            )
            values = update_agent._read_env(path)
        self.assertEqual(values["COSMAC_NEXUS_URL"], "https://nexus.example.com")
        self.assertEqual(values["COSMAC_OEM_KEY"], "CMK-AAAA-BBBB-CCCC-DDDD")
        self.assertNotIn("BAD-NAME", values)

    def test_current_version_is_strict_semver(self):
        """版本文件只接受不带预发布后缀的三段 SemVer。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "version.py"
            path.write_text('__version__ = "1.7.0"\n', encoding="utf-8")
            self.assertEqual(update_agent._source_version(path), "1.7.0")
            path.write_text('__version__ = "1.7-rc1"\n', encoding="utf-8")
            with self.assertRaises(RuntimeError):
                update_agent._source_version(path)

    def test_endpoint_requires_https_except_loopback(self):
        """远端明文 HTTP 会泄露 KEY，代理必须拒绝。"""
        self.assertEqual(
            update_agent._validate_endpoint("https://nexus.example.com/"),
            "https://nexus.example.com",
        )
        self.assertEqual(
            update_agent._validate_endpoint("http://127.0.0.1:9100"),
            "http://127.0.0.1:9100",
        )
        with self.assertRaises(RuntimeError):
            update_agent._validate_endpoint("http://nexus.example.com")


if __name__ == "__main__":
    unittest.main()
