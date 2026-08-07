"""OEM 干净宿主安装与存量节点宿主代理迁移的回归测试。"""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ENSURE_HOST = ROOT / "distro" / "ensure_host.sh"
MIGRATE_HOST = ROOT / "distro" / "migrate_host_tools.sh"


class InstallerHostTests(unittest.TestCase):
    def _fake_bin(self, root: Path) -> Path:
        fake = root / "bin"
        fake.mkdir()
        (fake / "dpkg").write_text(
            '#!/bin/sh\nexit "${FAKE_DPKG_RESULT:-0}"\n', encoding="utf-8"
        )
        (fake / "id").write_text(
            '#!/bin/sh\n[ "${1:-}" = "-u" ] && { echo 0; exit 0; }\nexec /usr/bin/id "$@"\n',
            encoding="utf-8",
        )
        (fake / "flock").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        (fake / "systemctl").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        for path in fake.iterdir():
            path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return fake

    def _host_check(self, os_release: str, *, dpkg_result: int = 0) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            release = base / "os-release"
            release.write_text(os_release, encoding="utf-8")
            fake = self._fake_bin(base)
            env = dict(os.environ)
            env.update(
                {
                    "GUDUU_OS_RELEASE_FILE": str(release),
                    "FAKE_DPKG_RESULT": str(dpkg_result),
                    "PATH": f"{fake}:/usr/bin:/bin",
                }
            )
            return subprocess.run(
                ["bash", "-c", f'source "{ENSURE_HOST}"; guduu_require_supported_host'],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )

    def test_supported_ubuntu_and_debian(self) -> None:
        self.assertEqual(
            self._host_check('ID=ubuntu\nVERSION_ID="24.04"\n').returncode, 0
        )
        self.assertEqual(
            self._host_check("ID=debian\nVERSION_ID=12\n").returncode, 0
        )

    def test_old_or_unknown_host_is_rejected(self) -> None:
        old = self._host_check("ID=ubuntu\nVERSION_ID=20.04\n", dpkg_result=1)
        self.assertNotEqual(old.returncode, 0)
        self.assertIn("最低支持", old.stdout)
        unknown = self._host_check("ID=centos\nVERSION_ID=9\n")
        self.assertNotEqual(unknown.returncode, 0)
        self.assertIn("仅支持 Ubuntu", unknown.stdout)

    def test_existing_node_migration_preserves_customer_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            fake = self._fake_bin(base)
            target = base / "node"
            distro = target / "distro"
            distro.mkdir(parents=True)
            env_file = distro / ".env"
            env_file.write_text("DOMAIN=oem.example.com\nOEM_SECRET=keep-me\n", encoding="utf-8")
            compose = distro / "docker-compose.yml"
            compose.write_text("# customer compose sentinel\n", encoding="utf-8")
            for name in ("update_agent.py", "apply_images.py", "doctor.sh"):
                (distro / name).write_text(f"old-{name}\n", encoding="utf-8")

            env = dict(os.environ)
            env.update(
                {
                    "PATH": f"{fake}:/usr/bin:/bin",
                    "GUDUU_UPDATE_LOCK": str(base / "guduu-update.lock"),
                    "GUDUU_HOST_TOOLS_VERSION": "1.24.1",
                    "GUDUU_SYSTEMD_DIR": str(base / "systemd"),
                }
            )
            completed = subprocess.run(
                ["bash", str(MIGRATE_HOST), "--install-root", str(target)],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout)
            self.assertEqual(compose.read_text(encoding="utf-8"), "# customer compose sentinel\n")
            saved_env = env_file.read_text(encoding="utf-8")
            self.assertIn("OEM_SECRET=keep-me", saved_env)
            self.assertEqual(saved_env.count("COSMAC_AUTO_UPDATE=0"), 1)
            self.assertIn("_PENDING_FILE", (distro / "update_agent.py").read_text(encoding="utf-8"))
            self.assertEqual(
                (distro / "data" / "update" / "host-tools-version").read_text(encoding="utf-8").strip(),
                "1.24.1",
            )
            shared_state = distro / "data" / "cosmac"
            self.assertTrue(shared_state.is_dir())
            self.assertEqual(stat.S_IMODE(shared_state.stat().st_mode), 0o770)
            backups = list((distro / "data" / "update" / "host-tools-backups").glob("*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(
                (backups[0] / "update_agent.py").read_text(encoding="utf-8"),
                "old-update_agent.py\n",
            )

            # 幂等复跑不得重复追加默认开关，也不能改客户 Compose。
            second = subprocess.run(
                ["bash", str(MIGRATE_HOST), "--install-root", str(target)],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(second.returncode, 0, second.stdout)
            self.assertEqual(env_file.read_text(encoding="utf-8").count("COSMAC_AUTO_UPDATE=0"), 1)
            self.assertEqual(compose.read_text(encoding="utf-8"), "# customer compose sentinel\n")

    def test_systemd_unit_heals_shared_state_and_runs_promptly(self) -> None:
        service = (ROOT / "distro" / "templates" / "guduu-update-agent.service.tpl").read_text()
        timer = (ROOT / "distro" / "templates" / "guduu-update-agent.timer.tpl").read_text()
        installer = (ROOT / "distro" / "install.sh").read_text()
        migrator = MIGRATE_HOST.read_text()
        self.assertIn(
            "ExecStartPre=/usr/bin/install -d -m 0770 {{DISTRO_DIR}}/data/cosmac",
            service,
        )
        self.assertIn("UMask=0007", service)
        self.assertIn("OnActiveSec=30s", timer)
        self.assertIn("systemctl start guduu-update-agent.service", installer)
        self.assertIn("systemctl start guduu-update-agent.service", migrator)
        self.assertIn(
            'install -d -m 0770 "$TARGET_DISTRO/data/cosmac"', migrator
        )
        doctor = (ROOT / "distro" / "doctor.sh").read_text()
        self.assertIn("systemctl is-active --quiet guduu-update-agent.timer", doctor)
        self.assertIn("docker compose exec -T bot test -r /var/lib/cosmac", doctor)

    def test_migrator_accepts_flat_public_installer_layout(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            fake = self._fake_bin(base)
            target = base / "flat-node"
            target.mkdir()
            (target / ".env").write_text("DOMAIN=oem.example.com\n", encoding="utf-8")
            (target / "docker-compose.yml").write_text("# flat layout\n", encoding="utf-8")
            for name in ("update_agent.py", "apply_images.py", "doctor.sh"):
                (target / name).write_text(f"old-{name}\n", encoding="utf-8")
            env = dict(os.environ)
            env.update(
                {
                    "PATH": f"{fake}:/usr/bin:/bin",
                    "GUDUU_UPDATE_LOCK": str(base / "update.lock"),
                    "GUDUU_HOST_TOOLS_VERSION": "1.31.0",
                    "GUDUU_SYSTEMD_DIR": str(base / "systemd"),
                }
            )
            completed = subprocess.run(
                ["bash", str(MIGRATE_HOST), "--install-root", str(target)],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout)
            self.assertTrue((target / "data" / "cosmac").is_dir())
            self.assertEqual(
                (target / "data" / "update" / "host-tools-version")
                .read_text(encoding="utf-8")
                .strip(),
                "1.31.0",
            )

    def test_migrator_can_explicitly_approve_cached_release(self) -> None:
        """旧 bot 卡住时，root 只能批准代理已缓存的当前 release_id。"""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            fake = self._fake_bin(base)
            target = base / "node"
            target.mkdir()
            (target / ".env").write_text("DOMAIN=oem.example.com\n", encoding="utf-8")
            (target / "docker-compose.yml").write_text("# flat layout\n", encoding="utf-8")
            for name in ("update_agent.py", "apply_images.py", "doctor.sh"):
                (target / name).write_text(f"old-{name}\n", encoding="utf-8")
            state = target / "data" / "cosmac"
            state.mkdir(parents=True)
            (state / "pending-update.json").write_text(
                '{"release_id":33,"version":"1.30.0"}', encoding="utf-8"
            )
            env = dict(os.environ)
            env.update(
                {
                    "PATH": f"{fake}:/usr/bin:/bin",
                    "GUDUU_UPDATE_LOCK": str(base / "update.lock"),
                    "GUDUU_HOST_TOOLS_VERSION": "1.31.0",
                    "GUDUU_SYSTEMD_DIR": str(base / "systemd"),
                }
            )
            completed = subprocess.run(
                [
                    "bash",
                    str(MIGRATE_HOST),
                    "--install-root",
                    str(target),
                    "--approve-current",
                ],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout)
            approval = (state / "approved-update.json").read_text(encoding="utf-8")
            self.assertIn('"release_id": 33', approval)
            self.assertNotIn("version", approval)
            self.assertIn("明确批准当前 release #33", completed.stdout)


if __name__ == "__main__":
    unittest.main()
