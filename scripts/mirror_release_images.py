#!/usr/bin/env python3
"""把 Nexus 已登记的 GHCR 多架构镜像按原摘要同步到自建仓。

该脚本只在 Nexus 宿主机的 systemd 任务中运行，通过本机数据库读取
已经 HMAC 验证的镜像清单。它不把 Docker socket 交给 Nexus Web，也不读取
客户节点凭据。Registry 只监听宿主回环地址，公网写方法由 Caddy 拒绝；同步任务
因此无需保存仓库密码，也不会把上传端点暴露给外部节点。
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from typing import Iterable, Tuple

from nexus import db
from nexus.db import NexusImageManifest


_GHCR_RE = re.compile(
    r"^ghcr\.io/guduuos/guduu-os-(?:bot|web)@sha256:([0-9a-f]{64})$"
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


def _sync_one(source: str, version: str) -> None:
    """同步单个多架构镜像，并同时建立 vX.Y.Z / X.Y.Z 两个标准版本 Tag。"""
    match = _GHCR_RE.fullmatch(source)
    if match is None:
        raise RuntimeError("镜像引用不合法：" + source)
    target = _mirror_ref(source)
    # 宿主同步任务直连回环 Registry，不把 PATCH/PUT 上传流量绕经 Caddy 与
    # Cloudflare；外部节点只看到由 Caddy 限制为匿名只读的 TLS 拉取端点。
    local_repo = _LOCAL_REGISTRY + "/" + target.split("/", 1)[1].split("@", 1)[0]
    if not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", version):
        raise RuntimeError("数据库中出现不合法版本号：" + version)
    for tag in ("v" + version, version):
        local_target = local_repo + ":" + tag
        # copy 到 Tag 才会进入 /tags/list；只 copy @digest 虽能按摘要拉取，却不会有人工可见 Tag。
        _run([
            "skopeo", "copy", "--all", "--preserve-digests",
            "--dest-tls-verify=false",
            "docker://" + source, "docker://" + local_target,
        ])
        raw = _run([
            "skopeo", "inspect", "--raw", "--tls-verify=false",
            "docker://" + local_target,
        ])
        actual = hashlib.sha256(raw).hexdigest()
        if actual != match.group(1):
            raise RuntimeError(
                "自建仓 Tag 摘要不一致：%s 期望 %s，实际 %s"
                % (tag, match.group(1), actual)
            )
    print("已同步并校验 %s（v%s / %s）" % (target, version, version))


def _sources() -> Iterable[Tuple[str, str]]:
    """按版本顺序读取 Nexus 已登记的 bot/web 镜像。"""
    session = db.session()
    try:
        rows = session.query(NexusImageManifest).order_by(
            NexusImageManifest.created_ts.asc()
        )
        for row in rows:
            yield str(row.bot_image), str(row.version)
            yield str(row.web_image), str(row.version)
    finally:
        session.close()


def main() -> int:
    """校验运行环境并幂等同步所有已登记摘要。"""
    database_url = os.environ.get("NEXUS_DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("NEXUS_DATABASE_URL 未配置")
    db.init_engine(database_url)
    seen: set[Tuple[str, str]] = set()
    for source, version in _sources():
        key = (source, version)
        if key not in seen:
            _sync_one(source, version)
            seen.add(key)
    print("双仓同步完成，共校验 %d 个镜像。" % len(seen))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("双仓同步失败：" + str(exc), file=sys.stderr)
        raise SystemExit(1)
