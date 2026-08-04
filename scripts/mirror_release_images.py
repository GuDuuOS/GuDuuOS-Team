#!/usr/bin/env python3
"""把 Nexus 已登记的 GHCR 多架构镜像按原摘要同步到自建仓。

该脚本只在 Nexus 宿主机的 systemd 任务中运行，通过本机数据库读取
已经 HMAC 验证的镜像清单。它不把 Docker socket 交给 Nexus Web，也不读取
客户节点凭据。Registry 登录由 root 预先写入独立 authfile，避免密码出现在
命令行和 journal 中。
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

from nexus import db
from nexus.db import NexusImageManifest


_GHCR_RE = re.compile(
    r"^ghcr\.io/guduuos/guduu-os-(?:bot|web)@sha256:([0-9a-f]{64})$"
)
_AUTH_FILE = Path(
    os.environ.get(
        "GUDUU_MIRROR_AUTHFILE", "/etc/guduu-registry/skopeo-auth.json"
    )
)
_LOCAL_REGISTRY = "localhost:5000"


def _mirror_ref(source: str) -> str:
    """返回与 GHCR 引用同摘要的自建仓引用。"""
    if not _GHCR_RE.fullmatch(source):
        raise RuntimeError("数据库中出现非官方 GHCR 镜像：" + source)
    return "registry.guduu.co/guduuos/" + source.split("/", 2)[-1]


def _run(args: list[str]) -> bytes:
    """执行 skopeo 子进程，失败时只保留有限日志。"""
    completed = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60 * 60,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stdout.decode("utf-8", "replace")[-2000:])
    return completed.stdout


def _sync_one(source: str) -> None:
    """同步单个多架构镜像，并对目标 manifest 原文重算 SHA-256。"""
    match = _GHCR_RE.fullmatch(source)
    if match is None:
        raise RuntimeError("镜像引用不合法：" + source)
    target = _mirror_ref(source)
    # 写入账号只在 Nexus 宿主机使用，直连回环 Registry，
    # 不把 PATCH/PUT 上传流量绕经 Caddy 与 Cloudflare。外部节点仍然只看到
    # registry.guduu.co 的 TLS 拉取端点，且使用独立只读账号。
    local_target = _LOCAL_REGISTRY + "/" + target.split("/", 1)[1]
    auth = ["--authfile", str(_AUTH_FILE)]
    # timer 会周期执行；目标摘要已正确时立即跳过，避免重复
    # 传输大层和占用 GHCR 带宽。inspect 失败通常表示镜像尚未同步，
    # 可以继续 copy；inspect 成功但摘要不同则也重新按原摘要覆盖。
    try:
        existing = _run(
            [
                "skopeo",
                "inspect",
                "--raw",
                "--tls-verify=false",
                *auth,
                "docker://" + local_target,
            ]
        )
    except RuntimeError:
        existing = b""
    if existing and hashlib.sha256(existing).hexdigest() == match.group(1):
        print("已存在且摘要正确，跳过 " + target)
        return
    _run(
        [
            "skopeo",
            "copy",
            "--all",
            "--preserve-digests",
            "--dest-tls-verify=false",
            *auth,
            "docker://" + source,
            "docker://" + local_target,
        ]
    )
    raw = _run(
        [
            "skopeo",
            "inspect",
            "--raw",
            "--tls-verify=false",
            *auth,
            "docker://" + local_target,
        ]
    )
    actual = hashlib.sha256(raw).hexdigest()
    if actual != match.group(1):
        raise RuntimeError(
            "自建仓 manifest 摘要不一致：期望 %s，实际 %s"
            % (match.group(1), actual)
        )
    print("已同步并校验 " + target)


def _sources() -> Iterable[str]:
    """按版本顺序读取 Nexus 已登记的 bot/web 镜像。"""
    session = db.session()
    try:
        rows = session.query(NexusImageManifest).order_by(
            NexusImageManifest.created_ts.asc()
        )
        for row in rows:
            yield str(row.bot_image)
            yield str(row.web_image)
    finally:
        session.close()


def main() -> int:
    """校验运行环境并幂等同步所有已登记摘要。"""
    if not _AUTH_FILE.is_file():
        raise RuntimeError("缺少 root-only skopeo authfile：" + str(_AUTH_FILE))
    database_url = os.environ.get("NEXUS_DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("NEXUS_DATABASE_URL 未配置")
    db.init_engine(database_url)
    seen: set[str] = set()
    for source in _sources():
        if source not in seen:
            _sync_one(source)
            seen.add(source)
    print("双仓同步完成，共校验 %d 个镜像。" % len(seen))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("双仓同步失败：" + str(exc), file=sys.stderr)
        raise SystemExit(1)
