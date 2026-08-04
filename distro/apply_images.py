#!/usr/bin/env python3
"""OEM 宿主机按不可变 Docker 摘要安装 GuDuu OS 应用版本。

脚本只切换 bot/web，PostgreSQL、Synapse、Caddy 数据和客户 ``.env`` 都留在宿主机。
切换前先做数据库备份并给当前镜像打回撤标签；新容器未通过 ``doctor.sh`` 时立即恢复。
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Mapping, Optional


_VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_IMAGE_RE = re.compile(
    r"^ghcr\.io/guduuos/guduu-os-(?:bot|web)@sha256:[0-9a-f]{64}$"
)
_MIRROR_RE = re.compile(
    r"^registry\.guduu\.co/guduuos/guduu-os-(?:bot|web)@sha256:[0-9a-f]{64}$"
)
_SCRIPT_DIR = Path(__file__).resolve().parent
_ENV_FILE = _SCRIPT_DIR / ".env"
_REGISTRY_FILE = Path("/etc/guduu-registry.env")
_UPDATE_DIR = _SCRIPT_DIR / "data" / "update"
_BACKUP_DIR = _UPDATE_DIR / "backups"
_STATE_FILE = _UPDATE_DIR / "release-state.json"


def _read_env(path: Path) -> Dict[str, str]:
    """读取简单环境文件而不执行 shell，避免仓库令牌或客户配置变成代码。"""
    values: Dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            values[key] = value.strip().strip("'\"")
    return values


def _validate_image(value: str, service: str) -> str:
    """只允许官方 GHCR 仓库的精确摘要，并阻止 bot/web 交叉替换。"""
    image = (value or "").strip().lower()
    expected = "ghcr.io/guduuos/guduu-os-" + service + "@sha256:"
    if not _IMAGE_RE.fullmatch(image) or not image.startswith(expected):
        raise RuntimeError(service + " 镜像不是受信 GHCR 精确摘要")
    return image


def _compose_env(bot_image: str, web_image: str) -> Dict[str, str]:
    """返回仅覆盖镜像引用的子进程环境，不改客户其他配置。"""
    env = dict(os.environ)
    env["COSMAC_BOT_IMAGE"] = bot_image
    env["COSMAC_WEB_IMAGE"] = web_image
    return env


def _run(
    args: List[str],
    *,
    env: Optional[Mapping[str, str]] = None,
    timeout: int = 900,
    input_text: Optional[str] = None,
) -> str:
    """执行固定参数命令；失败时只抛出末尾日志，避免 systemd 日志无限增长。"""
    completed = subprocess.run(
        args,
        cwd=str(_SCRIPT_DIR),
        env=dict(env) if env is not None else None,
        input=input_text,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
        check=False,
    )
    output = completed.stdout or ""
    if completed.returncode != 0:
        raise RuntimeError(
            "命令失败（退出码 %d）：%s\n%s"
            % (completed.returncode, " ".join(args), output[-3000:])
        )
    return output


def _registry_login() -> None:
    """登录节点已配置的只读镜像仓，全程不输出令牌。"""
    values = _read_env(_REGISTRY_FILE)
    user = values.get("GUDUU_REGISTRY_USER", "")
    token = values.get("GUDUU_REGISTRY_TOKEN", "")
    if bool(user) != bool(token):
        raise RuntimeError("/etc/guduu-registry.env 必须同时配置用户和只读令牌")
    if user:
        _run(
            ["docker", "login", "ghcr.io", "--username", user, "--password-stdin"],
            input_text=token + "\n",
            timeout=60,
        )
    mirror_user = values.get("GUDUU_MIRROR_USER", "")
    mirror_token = values.get("GUDUU_MIRROR_TOKEN", "")
    if bool(mirror_user) != bool(mirror_token):
        raise RuntimeError("自建仓用户和只读令牌必须同时配置")
    if mirror_user:
        _run(
            [
                "docker",
                "login",
                "registry.guduu.co",
                "--username",
                mirror_user,
                "--password-stdin",
            ],
            input_text=mirror_token + "\n",
            timeout=60,
        )


def _validate_mirror(value: str, service: str, fallback: str) -> str:
    """校验自建仓引用的服务名与摘要都和 GHCR 灾备引用一致。"""
    image = (value or "").strip().lower()
    expected = "registry.guduu.co/guduuos/guduu-os-" + service + "@sha256:"
    if not _MIRROR_RE.fullmatch(image) or not image.startswith(expected):
        raise RuntimeError(service + " 镜像不是受信自建仓精确摘要")
    if image.rsplit("@", 1)[-1] != fallback.rsplit("@", 1)[-1]:
        raise RuntimeError(service + " 双仓镜像摘要不一致")
    return image


def _pull_with_fallback(
    primary_bot: str,
    primary_web: str,
    fallback_bot: str,
    fallback_web: str,
) -> tuple[str, str]:
    """优先拉自建仓，任一镜像失败则整组回退 GHCR。

    Docker 在拉取 ``@sha256`` 引用时会校验 manifest 内容；因此
    拉取成功本身就是摘要校验，不信任 tag 或 Registry 返回的名称。
    """
    primary_env = _compose_env(primary_bot, primary_web)
    try:
        _run(
            ["docker", "compose", "pull", "bot", "web"],
            env=primary_env,
            timeout=45 * 60,
        )
        return primary_bot, primary_web
    except RuntimeError as exc:
        print(
            "[镜像更新] 自建仓拉取失败，回退 GHCR：" + str(exc),
            file=sys.stderr,
        )
        fallback_env = _compose_env(fallback_bot, fallback_web)
        _run(
            ["docker", "compose", "pull", "bot", "web"],
            env=fallback_env,
            timeout=45 * 60,
        )
        return fallback_bot, fallback_web


def _backup_database() -> Path:
    """流式生成 gzip SQL 备份，并只保留最近十份。

    不通过 shell 管道，避免路径或参数插值；任何备份失败都会在切换容器前终止升级。
    """
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    target = _BACKUP_DIR / ("before-image-update-" + stamp + ".sql.gz")
    process = subprocess.Popen(
        ["docker", "compose", "exec", "-T", "postgres", "pg_dumpall", "-U", "synapse"],
        cwd=str(_SCRIPT_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None
    with gzip.open(target, "wb") as output:
        while True:
            chunk = process.stdout.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)
    stderr = (process.stderr.read() if process.stderr is not None else b"").decode(
        "utf-8", "replace"
    )
    return_code = process.wait(timeout=15 * 60)
    if return_code != 0 or target.stat().st_size < 100:
        target.unlink(missing_ok=True)
        raise RuntimeError("升级前数据库备份失败：" + stderr[-1500:])
    backups = sorted(_BACKUP_DIR.glob("before-image-update-*.sql.gz"))
    for old in backups[:-10]:
        old.unlink(missing_ok=True)
    return target


def _running_image_id(service: str) -> str:
    """取得当前运行服务镜像 ID；没有运行容器时拒绝无保护切换。"""
    container_id = _run(
        ["docker", "compose", "ps", "-q", service], timeout=30
    ).strip()
    if not container_id:
        raise RuntimeError(service + " 当前没有运行容器，无法建立自动回撤点")
    image_id = _run(
        ["docker", "inspect", "--format", "{{.Image}}", container_id], timeout=30
    ).strip()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise RuntimeError("无法读取 " + service + " 当前镜像 ID")
    return image_id


def _write_env_images(bot_image: str, web_image: str) -> None:
    """原子更新 .env 中的两个镜像引用，保留客户配置、顺序和注释。"""
    original = _ENV_FILE.read_text(encoding="utf-8")
    replacements = {
        "COSMAC_BOT_IMAGE": bot_image,
        "COSMAC_WEB_IMAGE": web_image,
        "COSMAC_RELEASE_MODE": "container",
    }
    seen = set()
    output: List[str] = []
    for line in original.splitlines():
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in replacements:
            output.append(key + "=" + replacements[key])
            seen.add(key)
        else:
            output.append(line)
    for key, value in replacements.items():
        if key not in seen:
            output.append(key + "=" + value)
    mode = _ENV_FILE.stat().st_mode & 0o777
    fd, temp_name = tempfile.mkstemp(prefix=".env.", dir=str(_SCRIPT_DIR))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(output) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, mode)
        os.replace(temp_name, _ENV_FILE)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _wait_for_doctor(env: Mapping[str, str], attempts: int = 12) -> None:
    """等待新容器真正就绪后再决定发布成败。

    Docker 的 ``running`` 只代表进程已启动，bot HTTP 端口与 Caddy 路由可能还需要
    数秒初始化。无等待的单次体检会把短暂启动窗口误判为故障，并造成无意义回撤。

    Args:
        env: 本次 Compose 切换使用的镜像环境变量。
        attempts: 最多体检次数，每次间隔五秒。

    Raises:
        RuntimeError: 在等待窗口内始终未能通过完整体检。
    """
    last_error: Optional[RuntimeError] = None
    for attempt in range(max(1, attempts)):
        try:
            _run(["bash", "doctor.sh"], env=env, timeout=10 * 60)
            return
        except RuntimeError as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(5)
    assert last_error is not None
    raise last_error


def apply(
    version: str,
    bot_image: str,
    web_image: str,
    bot_mirror_image: str,
    web_mirror_image: str,
) -> None:
    """执行一次受保护的镜像切换，失败自动回撤并向调用方返回非零。"""
    if not _VERSION_RE.fullmatch(version):
        raise RuntimeError("目标版本必须是 X.Y.Z")
    bot_image = _validate_image(bot_image, "bot")
    web_image = _validate_image(web_image, "web")
    bot_mirror_image = _validate_mirror(bot_mirror_image, "bot", bot_image)
    web_mirror_image = _validate_mirror(web_mirror_image, "web", web_image)
    if not _ENV_FILE.is_file():
        raise RuntimeError("未找到 distro/.env，本机尚未安装")

    _registry_login()
    backup = _backup_database()
    stamp = str(int(time.time()))
    rollback_bot = "guduu-rollback-bot:" + stamp
    rollback_web = "guduu-rollback-web:" + stamp
    _run(["docker", "tag", _running_image_id("bot"), rollback_bot], timeout=30)
    _run(["docker", "tag", _running_image_id("web"), rollback_web], timeout=30)

    selected_bot, selected_web = _pull_with_fallback(
        bot_mirror_image, web_mirror_image, bot_image, web_image
    )
    new_env = _compose_env(selected_bot, selected_web)
    old_env = _compose_env(rollback_bot, rollback_web)
    try:
        print("[镜像更新] 校验新 web 镜像与本机 Caddy 配置……")
        _run(
            [
                "docker", "compose", "run", "--rm", "--no-deps", "web",
                "caddy", "validate", "--config", "/etc/caddy/Caddyfile",
            ],
            env=new_env,
            timeout=5 * 60,
        )
        print("[镜像更新] 切换 bot/web 并运行完整体检……")
        _run(
            ["docker", "compose", "up", "-d", "--no-build", "bot", "web"],
            env=new_env,
            timeout=15 * 60,
        )
        _wait_for_doctor(new_env)
        installed = _run(
            [
                "docker", "compose", "exec", "-T", "bot", "python", "-c",
                "import cosmac; print(cosmac.__version__)",
            ],
            env=new_env,
            timeout=60,
        ).strip().splitlines()[-1]
        if installed != version:
            raise RuntimeError("镜像内版本 %s 与目标 %s 不一致" % (installed, version))
    except Exception as install_error:
        print("[镜像更新] 新版本体检失败，正在自动回撤……", file=sys.stderr)
        try:
            _run(
                ["docker", "compose", "up", "-d", "--no-build", "bot", "web"],
                env=old_env,
                timeout=15 * 60,
            )
            _wait_for_doctor(old_env)
        except Exception as rollback_error:
            raise RuntimeError(
                "新版本失败且自动回撤体检也失败；请立即人工处理。新版本错误：%s；"
                "回撤错误：%s" % (install_error, rollback_error)
            ) from rollback_error
        raise RuntimeError("新版本体检失败，已自动恢复原镜像：" + str(install_error))

    _write_env_images(selected_bot, selected_web)
    _UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(
        json.dumps(
            {
                "version": version,
                "bot_image": bot_image,
                "web_image": web_image,
                "selected_bot_image": selected_bot,
                "selected_web_image": selected_web,
                "rollback_bot": rollback_bot,
                "rollback_web": rollback_web,
                "backup": str(backup),
                "installed_ts": int(time.time()),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    os.chmod(_STATE_FILE, 0o600)
    print("[镜像更新] 已安装 GuDuu OS " + version + "，体检通过。")


def main() -> int:
    """解析来自更新代理的固定参数并执行安装。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--bot-image", required=True)
    parser.add_argument("--web-image", required=True)
    parser.add_argument("--bot-mirror-image", required=True)
    parser.add_argument("--web-mirror-image", required=True)
    args = parser.parse_args()
    try:
        apply(
            args.version,
            args.bot_image,
            args.web_image,
            args.bot_mirror_image,
            args.web_mirror_image,
        )
        return 0
    except Exception as exc:
        print("[镜像更新] " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
