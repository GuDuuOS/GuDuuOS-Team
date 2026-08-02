"""OEM 宿主自动更新代理的输入安全测试。"""

from __future__ import annotations

import tempfile
import unittest
import importlib.util
from pathlib import Path
from unittest import mock


# 环境里可能安装了同名第三方 ``distro`` 包；按真实文件路径加载，确保测试的是仓库代码。
_AGENT_PATH = Path(__file__).resolve().parents[2] / "distro" / "update_agent.py"
_AGENT_SPEC = importlib.util.spec_from_file_location("guduu_update_agent", _AGENT_PATH)
assert _AGENT_SPEC is not None and _AGENT_SPEC.loader is not None
update_agent = importlib.util.module_from_spec(_AGENT_SPEC)
_AGENT_SPEC.loader.exec_module(update_agent)

_APPLY_PATH = Path(__file__).resolve().parents[2] / "distro" / "apply_images.py"
_APPLY_SPEC = importlib.util.spec_from_file_location("guduu_apply_images", _APPLY_PATH)
assert _APPLY_SPEC is not None and _APPLY_SPEC.loader is not None
apply_images = importlib.util.module_from_spec(_APPLY_SPEC)
_APPLY_SPEC.loader.exec_module(apply_images)


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

    def test_container_artifact_only_accepts_official_exact_digests(self):
        """更新代理不能把 Nexus 字段转换成任意镜像或命令。"""
        update = {
            "artifact": {
                "mode": "container",
                "bot_image": "ghcr.io/guduuos/guduu-os-bot@sha256:" + "a" * 64,
                "web_image": "ghcr.io/guduuos/guduu-os-web@sha256:" + "b" * 64,
            }
        }
        command = update_agent._artifact_command(update, "1.9.0", "v1.9.0")
        self.assertIn("apply_images.py", command[1])
        update["artifact"]["bot_image"] = "evil.example/bot@sha256:" + "a" * 64
        with self.assertRaises(RuntimeError):
            update_agent._artifact_command(update, "1.9.0", "v1.9.0")

    def test_apply_image_validation_and_atomic_env_update(self):
        """镜像执行器严格校验服务名，并只替换 .env 指定字段。"""
        bot = "ghcr.io/guduuos/guduu-os-bot@sha256:" + "a" * 64
        web = "ghcr.io/guduuos/guduu-os-web@sha256:" + "b" * 64
        self.assertEqual(apply_images._validate_image(bot, "bot"), bot)
        with self.assertRaises(RuntimeError):
            apply_images._validate_image(web, "bot")
        with tempfile.TemporaryDirectory() as temp_dir:
            original_path = apply_images._ENV_FILE
            path = Path(temp_dir) / ".env"
            path.write_text("DOMAIN=a.example\nCOSMAC_BOT_IMAGE=old\n", encoding="utf-8")
            apply_images._ENV_FILE = path
            try:
                apply_images._write_env_images(bot, web)
            finally:
                apply_images._ENV_FILE = original_path
            text = path.read_text(encoding="utf-8")
        self.assertIn("DOMAIN=a.example", text)
        self.assertIn("COSMAC_BOT_IMAGE=" + bot, text)
        self.assertIn("COSMAC_WEB_IMAGE=" + web, text)
        self.assertIn("COSMAC_RELEASE_MODE=container", text)

    def test_doctor_waits_for_container_readiness(self):
        """容器刚启动时的短暂失败应重试，不能立即触发回撤。"""
        with mock.patch.object(
            apply_images,
            "_run",
            side_effect=[RuntimeError("尚未就绪"), ""],
        ) as run_mock, mock.patch.object(apply_images.time, "sleep") as sleep_mock:
            apply_images._wait_for_doctor({}, attempts=2)
        self.assertEqual(run_mock.call_count, 2)
        sleep_mock.assert_called_once_with(5)

    def test_doctor_failure_is_returned_after_retry_window(self):
        """真实持续故障在重试窗口结束后仍必须阻断发布。"""
        with mock.patch.object(
            apply_images,
            "_run",
            side_effect=RuntimeError("持续故障"),
        ), mock.patch.object(apply_images.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "持续故障"):
                apply_images._wait_for_doctor({}, attempts=2)


if __name__ == "__main__":
    unittest.main()
