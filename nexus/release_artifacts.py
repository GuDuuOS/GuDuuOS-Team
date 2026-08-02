"""Nexus Docker 镜像清单登记与发布冻结。

日常 OEM 应用发布不再让客户服务器现场构建源码。GitHub Actions 完成镜像构建后，
把不可变摘要清单通过 HMAC 认证登记到 Nexus；版本中心创建节点版本时再冻结副本。
本模块绝不接收或保存 GHCR 密码，节点拉取权限由各宿主机自行保管。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
from typing import Any, Dict, Mapping, Optional

from nexus.db import NexusImageManifest, NexusReleaseArtifact
from nexus.fleet import FleetError


_VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_IMAGE_RE = re.compile(
    r"^ghcr\.io/guduuos/guduu-os-(?:bot|web)@sha256:[0-9a-f]{64}$"
)
_MAX_CLOCK_SKEW_SECONDS = 5 * 60


def canonical_payload(payload: Mapping[str, Any]) -> bytes:
    """返回 webhook 签名使用的稳定 JSON 字节。

    CI 与服务端都按键排序并去掉无意义空格，避免代理改变普通 JSON 排版后导致签名
    不一致。只允许普通 JSON 数据，调用方不能传入自定义对象。
    """
    return json.dumps(
        dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _webhook_secret() -> bytes:
    """读取独立 webhook 密钥；未配置时安全关闭镜像登记入口。"""
    value = os.environ.get("NEXUS_RELEASE_WEBHOOK_SECRET", "").strip()
    if len(value) < 32:
        raise FleetError(
            "NEXUS_RELEASE_WEBHOOK_DISABLED",
            "镜像构建清单入口尚未配置",
            503,
        )
    return value.encode("utf-8")


def verify_webhook(
    payload: Mapping[str, Any], timestamp: str, signature: str
) -> None:
    """校验 CI webhook 的时效和 HMAC-SHA256 签名。

    Args:
        payload: 已解析的 JSON 清单。
        timestamp: CI 发送的 Unix 秒字符串。
        signature: ``sha256=<hex>`` 形式签名。

    Raises:
        FleetError: 时间戳过期、签名缺失或签名不匹配时拒绝。
    """
    try:
        sent_at = int(timestamp)
    except (TypeError, ValueError) as exc:
        raise FleetError("NEXUS_BAD_MANIFEST_AUTH", "构建清单时间戳无效", 401) from exc
    if abs(int(time.time()) - sent_at) > _MAX_CLOCK_SKEW_SECONDS:
        raise FleetError("NEXUS_BAD_MANIFEST_AUTH", "构建清单签名已过期", 401)
    expected = hmac.new(
        _webhook_secret(),
        str(sent_at).encode("ascii") + b"\n" + canonical_payload(payload),
        hashlib.sha256,
    ).hexdigest()
    provided = (signature or "").strip().lower()
    if not hmac.compare_digest("sha256=" + expected, provided):
        raise FleetError("NEXUS_BAD_MANIFEST_AUTH", "构建清单签名无效", 401)


def _validated(payload: Mapping[str, Any]) -> Dict[str, str]:
    """归一化并严格验证来自 CI 的公开交付字段。"""
    values = {
        "version": str(payload.get("version", "")).strip(),
        "git_ref": str(payload.get("git_ref", "")).strip(),
        "source_commit": str(payload.get("source_commit", "")).strip().lower(),
        "bot_image": str(payload.get("bot_image", "")).strip().lower(),
        "web_image": str(payload.get("web_image", "")).strip().lower(),
        "platforms": str(payload.get("platforms", "linux/amd64")).strip(),
    }
    if not _VERSION_RE.fullmatch(values["version"]):
        raise FleetError("NEXUS_BAD_MANIFEST", "镜像清单版本号必须是 X.Y.Z")
    if values["git_ref"] != "v" + values["version"]:
        raise FleetError("NEXUS_BAD_MANIFEST", "镜像清单 Git tag 与版本号不一致")
    if not _COMMIT_RE.fullmatch(values["source_commit"]):
        raise FleetError("NEXUS_BAD_MANIFEST", "镜像清单源码 commit 不合法")
    if not _IMAGE_RE.fullmatch(values["bot_image"]):
        raise FleetError("NEXUS_BAD_MANIFEST", "bot 镜像必须使用受信 GHCR 精确摘要")
    if not _IMAGE_RE.fullmatch(values["web_image"]):
        raise FleetError("NEXUS_BAD_MANIFEST", "web 镜像必须使用受信 GHCR 精确摘要")
    if "linux/amd64" not in values["platforms"].split(","):
        raise FleetError("NEXUS_BAD_MANIFEST", "当前 GCP 节点要求 linux/amd64 镜像")
    return values


def register_manifest(s, payload: Mapping[str, Any]) -> Dict[str, Any]:
    """幂等登记一份 CI 镜像清单，禁止同版本替换摘要。"""
    values = _validated(payload)
    row = s.get(NexusImageManifest, values["version"])
    if row is None:
        row = NexusImageManifest(**values)
        s.add(row)
        s.flush()
    else:
        current = {
            key: str(getattr(row, key))
            for key in (
                "version",
                "git_ref",
                "source_commit",
                "bot_image",
                "web_image",
                "platforms",
            )
        }
        if current != values:
            raise FleetError(
                "NEXUS_MANIFEST_IMMUTABLE",
                "该版本已有不同镜像摘要，禁止覆盖",
                409,
            )
    return manifest_dict(row)


def manifest_dict(row: NexusImageManifest) -> Dict[str, Any]:
    """输出不含凭据的清单字段，供版本后台显示构建状态。"""
    return {
        "version": row.version,
        "git_ref": row.git_ref,
        "source_commit": row.source_commit,
        "bot_image": row.bot_image,
        "web_image": row.web_image,
        "platforms": row.platforms,
        "created_ts": row.created_ts,
    }


def find_manifest(s, version: str) -> Optional[Dict[str, Any]]:
    """按版本读取可用镜像清单；不存在时返回 ``None``。"""
    row = s.get(NexusImageManifest, (version or "").strip())
    return manifest_dict(row) if row is not None else None


def freeze_for_release(s, release_id: int, version: str) -> NexusReleaseArtifact:
    """把版本清单冻结到指定发布记录；仅新节点发布调用。"""
    manifest = s.get(NexusImageManifest, version)
    if manifest is None:
        raise FleetError(
            "NEXUS_IMAGE_MANIFEST_MISSING",
            "该节点版本的 Docker 镜像尚未由 CI 构建登记",
            409,
        )
    row = NexusReleaseArtifact(
        release_id=int(release_id),
        mode="container",
        source_commit=manifest.source_commit,
        bot_image=manifest.bot_image,
        web_image=manifest.web_image,
        platforms=manifest.platforms,
    )
    s.add(row)
    s.flush()
    return row


def artifact_dict(row: Optional[NexusReleaseArtifact]) -> Dict[str, Any]:
    """把冻结交付物转为 API 字段；旧版本明确标记为 legacy_git。"""
    if row is None:
        return {"mode": "legacy_git"}
    return {
        "mode": row.mode,
        "source_commit": row.source_commit,
        "bot_image": row.bot_image,
        "web_image": row.web_image,
        "platforms": row.platforms,
    }
