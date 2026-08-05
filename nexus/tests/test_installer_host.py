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


if __name__ == "__main__":
    unittest.main()
