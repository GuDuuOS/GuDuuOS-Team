#!/usr/bin/env python3
"""GuDuu OS OEM 宿主机自动更新代理。

代理由 systemd timer 以 root 身份定时启动：读取发行版 ``.env`` 中已经存在的 Nexus
地址与 OEM KEY，询问母舰是否有分配给本实例的版本。日常版本调用
``apply_images.py`` 安装 Nexus 冻结的 GHCR 精确摘要；更新器自身引导/救援仍调用
``update.sh`` 且只接受严格 ``vX.Y.Z`` Git tag。它不会开放监听端口，也不接受 Nexus
传入任意命令。
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional


_VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_IMAGE_RE = re.compile(
    r"^ghcr\.io/guduuos/guduu-os-(?:bot|web)@sha256:[0-9a-f]{64}$"
)
_MIRROR_RE = re.compile(
    r"^registry\.guduu\.co/guduuos/guduu-os-(?:bot|web)@sha256:[0-9a-f]{64}$"
)
_DOCKERHUB_RE = re.compile(
    r"^docker\.io/guduu/guduu-os-(?:bot|web)@sha256:[0-9a-f]{64}$"
)
_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
_ENV_FILE = _SCRIPT_DIR / ".env"
_VERSION_FILE = _REPO_ROOT / "cosmac" / "__init__.py"
_STATE_DIR = _SCRIPT_DIR / "data" / "cosmac"
_PENDING_FILE = _STATE_DIR / "pending-update.json"
_APPROVAL_FILE = _STATE_DIR / "approved-update.json"


def _ensure_state_dir() -> None:
    """保证宿主代理与 bot 容器共享的状态目录双方都可写。"""
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(_STATE_DIR, 0o770)


def _write_json_atomic(path: Path, value: Dict[str, Any]) -> None:
    """原子写宿主更新状态，避免 bot 正在读取时看见半份 JSON。"""
    _ensure_state_dir()
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.chmod(temp, 0o660)
    temp.replace(path)


def _approved(release_id: int, env: Dict[str, str]) -> bool:
    """客户节点默认手动；固定内部灰度节点 #2 自动执行已分配任务。"""
    instance_id = 0
    try:
        identity = json.loads(
            (_STATE_DIR / "node-activation.json").read_text(encoding="utf-8")
        )
        if identity.get("activated") is True:
            instance_id = int(identity.get("instance_id") or 0)
        if instance_id == 2:
            return True
    except (OSError, ValueError, TypeError, AttributeError, json.JSONDecodeError):
        pass
    # 官网正式节点 #3 始终保留人工确认，即使历史 .env 曾误开自动更新。
    if instance_id != 3 and str(env.get("COSMAC_AUTO_UPDATE") or "").strip() == "1":
        return True
    try:
        value = json.loads(_APPROVAL_FILE.read_text(encoding="utf-8"))
        return int(value.get("release_id") or 0) == release_id
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def _read_env(path: Path = _ENV_FILE) -> Dict[str, str]:
    """读取发行版生成的简单 KEY=VALUE 文件，不执行其中任何 shell 内容。"""
    values: Dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            values[key] = value.strip().strip("'\"")
    return values


def _source_version(path: Path = _VERSION_FILE) -> str:
    """直接从源码读取产品版本，供输入校验与单元测试使用。"""
    text = path.read_text(encoding="utf-8")
    matched = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, re.M)
    if not matched or not _VERSION_RE.fullmatch(matched.group(1)):
        raise RuntimeError("无法读取合法的 GuDuu OS 版本号")
    return matched.group(1)


def _installed_version() -> str:
    """读取当前正在运行的 bot 容器版本，而不是宿主仓库 checkout 版本。

    升级可能在 ``git merge`` 后、容器切换前失败。若只读源码版本，下一轮会误以为
    已安装成功并跳过重建；所以 Docker 不可用时宁可报错，不能用源码值冒充运行值。
    """
    completed = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "bot",
            "python",
            "-c",
            "import cosmac; print(cosmac.__version__)",
        ],
        cwd=str(_SCRIPT_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=30,
        check=False,
    )
    value = (completed.stdout or "").strip().splitlines()
    version = value[-1].strip() if value else ""
    if completed.returncode != 0 or not _VERSION_RE.fullmatch(version):
        raise RuntimeError("无法读取正在运行的 GuDuu OS 容器版本")
    return version


def _post(url: str, payload: Dict[str, Any], timeout: int = 30) -> Dict[str, Any]:
    """向 Nexus 发送 JSON；错误响应只返回服务端公开的业务说明。"""
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            # Cloudflare 会把 urllib 默认的 Python User-Agent 误判为通用机器人。
            # 使用固定产品标识便于边缘规则精确放行，同时不携带 KEY、域名等租户信息。
            "User-Agent": "GuDuuOS-Node-Updater/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8") or "{}")
            return body if isinstance(body, dict) else {}
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8") or "{}")
            message = body.get("error") if isinstance(body, dict) else ""
        except Exception:
            message = ""
        raise RuntimeError(message or f"Nexus 返回 HTTP {exc.code}") from exc


def _validate_endpoint(url: str) -> str:
    """生产只允许 HTTPS；本机回归测试可使用 loopback HTTP。"""
    base = (url or "").strip().rstrip("/")
    if base.startswith("https://"):
        return base
    if base.startswith("http://127.0.0.1") or base.startswith("http://localhost"):
        return base
    raise RuntimeError("NEXUS_URL 必须使用 HTTPS")


def _artifact_command(update: Dict[str, Any], target: str, git_ref: str) -> list:
    """把 Nexus 的受限交付物转换为固定命令参数。

    新版本只能引用官方 bot/web GHCR 仓库的完整 sha256；历史记录没有 artifact 时
    保持严格 Git tag 流程，确保当前已安装的旧代理能够完成第一次平滑升级。
    """
    artifact = update.get("artifact")
    if not isinstance(artifact, dict) or artifact.get("mode") == "legacy_git":
        return ["bash", str(_SCRIPT_DIR / "update.sh"), "--ref", git_ref]
    if artifact.get("mode") != "container":
        raise RuntimeError("Nexus 返回了不支持的节点交付方式")
    bot_image = str(artifact.get("bot_image") or "").strip().lower()
    web_image = str(artifact.get("web_image") or "").strip().lower()
    bot_mirror = str(artifact.get("bot_mirror_image") or "").strip().lower()
    web_mirror = str(artifact.get("web_mirror_image") or "").strip().lower()
    bot_dockerhub = str(
        artifact.get("bot_dockerhub_image") or ""
    ).strip().lower()
    web_dockerhub = str(
        artifact.get("web_dockerhub_image") or ""
    ).strip().lower()
    if (
        not _IMAGE_RE.fullmatch(bot_image)
        or not bot_image.startswith("ghcr.io/guduuos/guduu-os-bot@sha256:")
    ):
        raise RuntimeError("Nexus 返回了不合法的 bot 镜像摘要")
    if (
        not _IMAGE_RE.fullmatch(web_image)
        or not web_image.startswith("ghcr.io/guduuos/guduu-os-web@sha256:")
    ):
        raise RuntimeError("Nexus 返回了不合法的 web 镜像摘要")
    if not _MIRROR_RE.fullmatch(bot_mirror) or not _MIRROR_RE.fullmatch(web_mirror):
        raise RuntimeError("Nexus 返回了不合法的自建仓镜像摘要")
    if not _DOCKERHUB_RE.fullmatch(bot_dockerhub) or not _DOCKERHUB_RE.fullmatch(
        web_dockerhub
    ):
        raise RuntimeError("Nexus 返回了不合法的 Docker Hub 镜像摘要")
    # 三个仓必须指向同一 manifest list；仅比较名字不够，
    # 直接比较 @sha256 后的内容地址才能阻止镜像被调包。
    if bot_mirror.rsplit("@", 1)[-1] != bot_image.rsplit("@", 1)[-1]:
        raise RuntimeError("bot 自建仓与 GHCR 镜像摘要不一致")
    if web_mirror.rsplit("@", 1)[-1] != web_image.rsplit("@", 1)[-1]:
        raise RuntimeError("web 自建仓与 GHCR 镜像摘要不一致")
    if bot_dockerhub.rsplit("@", 1)[-1] != bot_image.rsplit("@", 1)[-1]:
        raise RuntimeError("bot Docker Hub 与 GHCR 镜像摘要不一致")
    if web_dockerhub.rsplit("@", 1)[-1] != web_image.rsplit("@", 1)[-1]:
        raise RuntimeError("web Docker Hub 与 GHCR 镜像摘要不一致")
    return [
        sys.executable,
        str(_SCRIPT_DIR / "apply_images.py"),
        "--version",
        target,
        "--bot-image",
        bot_image,
        "--web-image",
        web_image,
        "--bot-mirror-image",
        bot_mirror,
        "--web-mirror-image",
        web_mirror,
        "--bot-dockerhub-image",
        bot_dockerhub,
        "--web-dockerhub-image",
        web_dockerhub,
    ]


def _report(
    base: str,
    key: str,
    release_id: int,
    status: str,
    *,
    version: str,
    detail: str = "",
) -> None:
    """尽力上报状态；上报失败不能掩盖真正的升级结果。"""
    try:
        _post(
            base + "/nexus/update/report",
            {
                "key": key,
                "release_id": release_id,
                "status": status,
                "current_version": version,
                "detail": detail[-1800:],
            },
        )
    except Exception as exc:
        print(f"[更新代理] 状态上报失败：{exc}", file=sys.stderr)


def run_once() -> int:
    """检查并执行一次更新；返回适合 systemd 记录的进程退出码。"""
    _ensure_state_dir()
    if not _ENV_FILE.is_file():
        print("[更新代理] 未找到 distro/.env，跳过。")
        return 0
    env = _read_env()
    key = env.get("COSMAC_OEM_KEY") or env.get("OEM_KEY") or ""
    nexus_url = env.get("COSMAC_NEXUS_URL") or env.get("NEXUS_URL") or ""
    if not key or not nexus_url:
        print("[更新代理] 当前实例未接入 Nexus，跳过。")
        return 0

    base = _validate_endpoint(nexus_url)
    current = _installed_version()
    result = _post(
        base + "/nexus/update/check",
        {"key": key, "current_version": current},
    )
    update: Optional[Dict[str, Any]] = result.get("update")
    if not isinstance(update, dict):
        _PENDING_FILE.unlink(missing_ok=True)
        print(f"[更新代理] 当前 {current}，没有待安装版本。")
        return 0

    release_id = int(update.get("release_id") or 0)
    target = str(update.get("version") or "")
    git_ref = str(update.get("git_ref") or "")
    if not release_id or not _VERSION_RE.fullmatch(target) or git_ref != f"v{target}":
        raise RuntimeError("Nexus 返回了不合法的版本任务，已拒绝执行")

    # 先把经过格式校验的公开更新信息落到宿主状态目录，OS 后台据此展示“有新版本”。
    # artifact 摘要仍由代理自己持有并复验，浏览器无权篡改安装命令。
    _write_json_atomic(_PENDING_FILE, {
        "release_id": release_id,
        "current_version": current,
        "version": target,
        "title": str(update.get("title") or f"GuDuu OS {target}")[:200],
        "notes": str(update.get("notes") or "")[:8000],
        "git_ref": git_ref,
    })
    if not _approved(release_id, env):
        print(
            f"[更新代理] 发现 {current} → {target}，已发布更新通知；"
            "等待节点管理员在 OS 后台确认安装。"
        )
        return 0

    command = _artifact_command(update, target, git_ref)
    mode = "Docker 摘要" if command[0] == sys.executable else "Git 引导/救援"
    print(f"[更新代理] 收到 {current} → {target}（{mode}）")
    _report(base, key, release_id, "downloading", version=current)
    _report(base, key, release_id, "installing", version=current)
    try:
        completed = subprocess.run(
            command,
            cwd=str(_SCRIPT_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=90 * 60,
            check=False,
        )
    except subprocess.TimeoutExpired:
        detail = "升级超过 90 分钟，代理已停止等待"
        _report(base, key, release_id, "failed", version=current, detail=detail)
        print(f"[更新代理] {detail}", file=sys.stderr)
        return 1

    output = completed.stdout or ""
    if output:
        # systemd 日志只保留末尾，既够排障也避免构建输出无限膨胀。
        print(output[-6000:])
    if completed.returncode != 0:
        detail = f"update.sh 退出码 {completed.returncode}\n{output[-1500:]}"
        _report(base, key, release_id, "failed", version=current, detail=detail)
        _APPROVAL_FILE.unlink(missing_ok=True)
        return completed.returncode or 1

    installed = _installed_version()
    if installed != target:
        detail = f"升级脚本完成，但本机版本为 {installed}，目标为 {target}"
        _report(base, key, release_id, "failed", version=installed, detail=detail)
        print(f"[更新代理] {detail}", file=sys.stderr)
        _APPROVAL_FILE.unlink(missing_ok=True)
        return 1
    _report(base, key, release_id, "success", version=installed, detail="升级完成")
    print(f"[更新代理] 已成功升级到 {installed}。")
    _APPROVAL_FILE.unlink(missing_ok=True)
    _PENDING_FILE.unlink(missing_ok=True)
    return 0


def main() -> int:
    """获取全局文件锁，保证 systemd 手动触发与 timer 不会并发升级。"""
    lock_path = Path(os.environ.get("GUDUU_UPDATE_LOCK", "/var/lock/guduu-update.lock"))
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("[更新代理] 另一个升级任务正在运行，本轮跳过。")
            return 0
        try:
            return run_once()
        except Exception as exc:
            print(f"[更新代理] 检查失败：{exc}", file=sys.stderr)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
