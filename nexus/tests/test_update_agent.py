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

    def test_customer_update_requires_explicit_approval(self):
        """客户节点缺省不能因收到任务就安装；灰度 opt-in 或当前任务批准才放行。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            original = update_agent._APPROVAL_FILE
            update_agent._APPROVAL_FILE = Path(temp_dir) / "approved.json"
            try:
                self.assertFalse(update_agent._approved(23, {}))
                self.assertTrue(update_agent._approved(23, {"COSMAC_AUTO_UPDATE": "1"}))
                update_agent._APPROVAL_FILE.write_text(
                    '{"release_id":23}', encoding="utf-8"
                )
                self.assertTrue(update_agent._approved(23, {}))
                self.assertFalse(update_agent._approved(24, {}))
            finally:
                update_agent._APPROVAL_FILE = original

    def test_pending_state_repairs_shared_directory_permissions(self):
        """历史 0700 目录会在写通知前修复，pending 文件允许同组 bot 读取。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            original_state = update_agent._STATE_DIR
            state = Path(temp_dir) / "cosmac"
            state.mkdir(mode=0o700)
            update_agent._STATE_DIR = state
            try:
                target = state / "pending-update.json"
                update_agent._write_json_atomic(target, {"release_id": 7})
                self.assertEqual(
                    target.read_text(encoding="utf-8"), '{"release_id": 7}'
                )
                self.assertEqual(target.stat().st_mode & 0o777, 0o660)
                self.assertEqual(state.stat().st_mode & 0o777, 0o770)
            finally:
                update_agent._STATE_DIR = original_state

    def test_update_request_has_fixed_product_user_agent(self):
        """节点代理必须带固定产品标识，避免被 Cloudflare 当成 urllib 机器人。"""
        with mock.patch.object(
            update_agent.urllib.request,
            "urlopen",
            side_effect=RuntimeError("只检查请求，不访问网络"),
        ) as opened:
            with self.assertRaises(RuntimeError):
                update_agent._post("https://nexus.example.com/check", {"key": "x"})
        request = opened.call_args.args[0]
        self.assertEqual(
            request.get_header("User-agent"), "GuDuuOS-Node-Updater/1.0"
        )

    def test_container_artifact_only_accepts_official_exact_digests(self):
        """更新代理不能把 Nexus 字段转换成任意镜像或命令。"""
        update = {
            "artifact": {
                "mode": "container",
                "bot_image": "ghcr.io/guduuos/guduu-os-bot@sha256:" + "a" * 64,
                "web_image": "ghcr.io/guduuos/guduu-os-web@sha256:" + "b" * 64,
                "bot_mirror_image": (
                    "registry.guduu.co/guduuos/guduu-os-bot@sha256:" + "a" * 64
                ),
                "web_mirror_image": (
                    "registry.guduu.co/guduuos/guduu-os-web@sha256:" + "b" * 64
                ),
                "bot_dockerhub_image": (
                    "docker.io/guduu/guduu-os-bot@sha256:" + "a" * 64
                ),
                "web_dockerhub_image": (
                    "docker.io/guduu/guduu-os-web@sha256:" + "b" * 64
                ),
            }
        }
        command = update_agent._artifact_command(update, "1.9.0", "v1.9.0")
        self.assertIn("apply_images.py", command[1])
        self.assertIn("--bot-dockerhub-image", command)
        update["artifact"]["bot_image"] = "evil.example/bot@sha256:" + "a" * 64
        with self.assertRaises(RuntimeError):
            update_agent._artifact_command(update, "1.9.0", "v1.9.0")

    def test_installer_prefers_dockerhub_before_other_registries(self):
        """新节点先用可配置加速器的 Docker Hub，再按固定顺序回退。"""
        installer = (_APPLY_PATH.parent / "install.sh").read_text(encoding="utf-8")
        dockerhub_pull = installer.index('docker pull "$BOT_DOCKERHUB_IMAGE"')
        mirror_pull = installer.index('docker pull "$BOT_MIRROR_IMAGE"')
        ghcr_pull = installer.index('docker pull "$BOT_GHCR_IMAGE"')
        self.assertLess(dockerhub_pull, mirror_pull)
        self.assertLess(mirror_pull, ghcr_pull)
        self.assertIn('artifact["bot_dockerhub_image"]', installer)

    def test_mirror_digest_must_equal_ghcr_digest(self):
        """两个仓的名称即使合法，内容摘要不同也必须拒绝。"""
        update = {
            "artifact": {
                "mode": "container",
                "bot_image": "ghcr.io/guduuos/guduu-os-bot@sha256:" + "a" * 64,
                "web_image": "ghcr.io/guduuos/guduu-os-web@sha256:" + "b" * 64,
                "bot_mirror_image": (
                    "registry.guduu.co/guduuos/guduu-os-bot@sha256:" + "c" * 64
                ),
                "web_mirror_image": (
                    "registry.guduu.co/guduuos/guduu-os-web@sha256:" + "b" * 64
                ),
                "bot_dockerhub_image": (
                    "docker.io/guduu/guduu-os-bot@sha256:" + "a" * 64
                ),
                "web_dockerhub_image": (
                    "docker.io/guduu/guduu-os-web@sha256:" + "b" * 64
                ),
            }
        }
        with self.assertRaisesRegex(RuntimeError, "bot 自建仓"):
            update_agent._artifact_command(update, "1.9.0", "v1.9.0")

    def test_three_registry_pull_falls_back_as_one_pair(self):
        """Docker Hub、自建仓失败时，bot/web 应整组改用 GHCR。"""
        with mock.patch.object(
            apply_images,
            "_run",
            side_effect=[
                RuntimeError("Docker Hub 离线"),
                RuntimeError("平台镜像仓离线"),
                "",
            ],
        ) as run_mock:
            selected = apply_images._pull_with_fallback(
                "docker.io/guduu/guduu-os-bot@sha256:" + "a" * 64,
                "docker.io/guduu/guduu-os-web@sha256:" + "b" * 64,
                "registry.guduu.co/guduuos/guduu-os-bot@sha256:" + "a" * 64,
                "registry.guduu.co/guduuos/guduu-os-web@sha256:" + "b" * 64,
                "ghcr.io/guduuos/guduu-os-bot@sha256:" + "a" * 64,
                "ghcr.io/guduuos/guduu-os-web@sha256:" + "b" * 64,
            )
        self.assertTrue(selected[0].startswith("ghcr.io/"))
        self.assertEqual(run_mock.call_count, 3)

    def test_mirror_login_failure_does_not_block_ghcr_fallback(self):
        """自建仓登录失败时不能在拉取前终止整个更新。"""
        values = {
            "GUDUU_REGISTRY_USER": "ghcr-reader",
            "GUDUU_REGISTRY_TOKEN": "ghcr-token",
            "GUDUU_MIRROR_USER": "mirror-reader",
            "GUDUU_MIRROR_TOKEN": "mirror-token",
        }
        with mock.patch.object(
            apply_images, "_read_env", return_value=values
        ), mock.patch.object(
            apply_images,
            "_run",
            side_effect=["", RuntimeError("自建仓暂时不可用")],
        ) as run_mock:
            apply_images._registry_login()

        self.assertEqual(run_mock.call_count, 2)

    def test_apply_image_validation_and_atomic_env_update(self):
        """镜像执行器严格校验服务名，并只替换 .env 指定字段。"""
        bot = "ghcr.io/guduuos/guduu-os-bot@sha256:" + "a" * 64
        web = "ghcr.io/guduuos/guduu-os-web@sha256:" + "b" * 64
        self.assertEqual(apply_images._validate_image(bot, "bot"), bot)
        self.assertEqual(
            apply_images._validate_dockerhub(
                "docker.io/guduu/guduu-os-bot@sha256:" + "a" * 64,
                "bot",
                bot,
            ),
            "docker.io/guduu/guduu-os-bot@sha256:" + "a" * 64,
        )
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
