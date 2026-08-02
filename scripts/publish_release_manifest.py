#!/usr/bin/env python3
"""把 GitHub Actions 生成的不可变镜像摘要登记到 Nexus。

脚本只使用标准库，签名算法与 ``nexus.release_artifacts`` 保持一致。密钥从环境读取，
不会出现在命令行参数、构建日志或镜像清单中。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sys
import time
import urllib.request


def _required(name: str) -> str:
    """读取必填环境变量，空值立即终止构建。"""
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError("缺少必填环境变量 " + name)
    return value


def main() -> int:
    """校验 CI 上下文、生成 HMAC 并 POST 清单。"""
    tag = _required("GITHUB_REF_NAME")
    if not re.fullmatch(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", tag):
        raise RuntimeError("只允许从严格 vX.Y.Z tag 发布镜像")
    version = tag[1:]
    payload = {
        "version": version,
        "git_ref": tag,
        "source_commit": _required("GITHUB_SHA").lower(),
        "bot_image": _required("BOT_IMAGE").lower(),
        "web_image": _required("WEB_IMAGE").lower(),
        "platforms": "linux/amd64,linux/arm64",
    }
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    timestamp = str(int(time.time()))
    signature = hmac.new(
        _required("NEXUS_RELEASE_WEBHOOK_SECRET").encode("utf-8"),
        timestamp.encode("ascii") + b"\n" + canonical,
        hashlib.sha256,
    ).hexdigest()
    request = urllib.request.Request(
        _required("NEXUS_RELEASE_MANIFEST_URL"),
        data=canonical,
        headers={
            "Content-Type": "application/json",
            # Cloudflare 会将 Python urllib 的默认 User-Agent 视为高风险机器人。
            # 这里使用稳定、可审计的 CI 标识，避免合法的 HMAC 回调在
            # 到达 Nexus 前被边缘阻断；真正的身份校验仍由下方 HMAC 完成。
            "User-Agent": "GuDuuOS-Release-GitHub-Actions/1.0",
            "Accept": "application/json",
            "X-Nexus-Timestamp": timestamp,
            "X-Nexus-Signature": "sha256=" + signature,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8")
        if response.status not in (200, 201):
            raise RuntimeError("Nexus 拒绝镜像清单：" + body[:500])
    print("Nexus 已登记 " + tag + " 的不可变镜像摘要。")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("发布镜像清单失败：" + str(exc), file=sys.stderr)
        raise SystemExit(1)
