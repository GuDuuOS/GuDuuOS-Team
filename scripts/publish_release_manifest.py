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
from pathlib import Path


def _required(name: str) -> str:
    """读取必填环境变量，空值立即终止构建。"""
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError("缺少必填环境变量 " + name)
    return value


def _release_copy(version: str) -> tuple[str, str]:
    """从仓库 ``DEVLOG.md`` 提取当前 tag 的 OEM 公告标题与正文。

    CI 使用的是 tag 对应的精确 commit，因此这里生成的文案与镜像源码
    天然同版本。文案与镜像摘要一起被 HMAC 签名，中途代理无法篡改。
    """
    header = re.compile(
        r"^##\s+\d{4}-\d{2}-\d{2}\s+—\s+GuDuu OS\s+"
        + re.escape(version)
        + r"\s+\([^)]+\)\s*$"
    )
    lines = Path("DEVLOG.md").read_text(encoding="utf-8").splitlines()
    inside = False
    current: list[str] = []
    items: list[str] = []
    for line in lines:
        if line.startswith("## "):
            if inside:
                break
            inside = bool(header.fullmatch(line))
            continue
        if not inside:
            continue
        if line.startswith("- "):
            if current:
                items.append(" ".join(current))
            current = [line[2:].strip()]
        elif current and line.startswith("  "):
            current.append(line.strip())
    if current:
        items.append(" ".join(current))
    if not items:
        raise RuntimeError("DEVLOG.md 中没有当前版本的可发布说明")
    cleaned = []
    for item in items:
        plain = item.replace("**", "").replace("`", "")
        # Markdown 为了行宽会在中文句子中间换行；上方拼接时保留
        # 了空格，这里只清除“中文→中文”的换行痕迹，不伤及 AI / Docker。
        plain = re.sub(
            r"(?<=[\u4e00-\u9fff，。；：])\s+(?=[\u4e00-\u9fff])", "", plain
        )
        cleaned.append(plain)
    first = re.sub(r"^(新增|修复|优化|变更)(?:（[^）]+）)?：", "", cleaned[0])
    title = re.split(r"[，；。]", first, maxsplit=1)[0].strip()[:80]
    notes = "GuDuu OS " + version + " 更新公告\n\n" + "\n".join(
        "• " + item for item in cleaned
    )
    return title or ("GuDuu OS " + version + " 更新"), notes


def main() -> int:
    """校验 CI 上下文、生成 HMAC 并 POST 清单。"""
    tag = _required("GITHUB_REF_NAME")
    if not re.fullmatch(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", tag):
        raise RuntimeError("只允许从严格 vX.Y.Z tag 发布镜像")
    version = tag[1:]
    release_title, release_notes = _release_copy(version)
    payload = {
        "version": version,
        "git_ref": tag,
        "source_commit": _required("GITHUB_SHA").lower(),
        "bot_image": _required("BOT_IMAGE").lower(),
        "web_image": _required("WEB_IMAGE").lower(),
        "platforms": "linux/amd64,linux/arm64",
        # 版本文案由 tag 内的 DEVLOG 自动生成，随清单一起签名；
        # Nexus 只创建默认未发布草稿，仍保留超管人工审阅门禁。
        "release_title": release_title,
        "release_notes": release_notes,
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
    print("Nexus 已登记 " + tag + " 的不可变镜像摘要与未发布草稿。")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("发布镜像清单失败：" + str(exc), file=sys.stderr)
        raise SystemExit(1)
