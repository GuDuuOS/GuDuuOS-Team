"""GuDuu Nexus 版本发布中心。

这个模块只负责版本状态机与节点投放记录，不负责在远端服务器执行 shell。真正的升级
由 OEM 宿主机上的 ``distro/update_agent.py`` 主动拉取任务后完成。这样 Nexus 不需要
保存客户 SSH 凭据，也不会因为客户服务器位于 NAT/防火墙后而失效。
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select

from nexus import fleet
from nexus.db import (
    NexusInstance,
    NexusRelease,
    NexusReleaseDeployment,
)
from nexus.fleet import FleetError


_VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_REPORT_STATES = {"downloading", "installing", "success", "failed"}
_ACTIVE_RELEASE_STATES = {"canary", "published"}
# 下载/构建被强制中断时，任务不能永久卡在 installing。超过一小时后允许同一节点
# 再次领取；正常升级一般远低于一小时，这个阈值不会制造并发执行。
_STALE_INSTALL_MS = 60 * 60 * 1000


def _now_ms() -> int:
    """返回统一的毫秒时间戳。"""
    return int(time.time() * 1000)


def _version_tuple(version: str, *, strict: bool = True) -> Tuple[int, int, int]:
    """解析严格的三段 SemVer；节点旧版本异常时可降级为 ``0.0.0``。

    Args:
        version: 不带 ``v`` 的产品版本号。
        strict: 为真时非法版本抛业务错误；为假时返回零版本。
    """
    matched = _VERSION_RE.fullmatch((version or "").strip())
    if matched:
        return tuple(int(matched.group(i)) for i in range(1, 4))  # type: ignore[return-value]
    if strict:
        raise FleetError("NEXUS_BAD_VERSION", "版本号必须是 X.Y.Z（如 1.7.0）")
    return (0, 0, 0)


def _release(s, release_id: int) -> NexusRelease:
    """按编号取版本，不存在时返回统一业务错误。"""
    row = s.get(NexusRelease, int(release_id))
    if row is None:
        raise FleetError("NEXUS_RELEASE_NOT_FOUND", "版本记录不存在", 404)
    return row


def _ensure_deployment(
    s, release: NexusRelease, instance: NexusInstance
) -> NexusReleaseDeployment:
    """幂等创建一个节点投放任务，并保留已有成功/失败记录。"""
    key = {"release_id": release.id, "instance_id": instance.id}
    row = s.get(NexusReleaseDeployment, key)
    if row is None:
        row = NexusReleaseDeployment(
            release_id=release.id,
            instance_id=instance.id,
            status="pending",
            from_version=instance.version or "",
            to_version=release.version,
        )
        s.add(row)
    return row


def _pause_other_active(s, keep_id: int) -> None:
    """激活一个版本时暂停其他活动版本，确保节点一次只面对一个目标。"""
    rows = s.execute(
        select(NexusRelease).where(NexusRelease.status.in_(_ACTIVE_RELEASE_STATES))
    ).scalars()
    now = _now_ms()
    for row in rows:
        if row.id != keep_id:
            row.status = "paused"
            row.updated_ts = now


def create_release(
    s, *, version: str, title: str, notes: str, git_ref: str
) -> Dict[str, Any]:
    """创建草稿版本。

    自动更新只接受与版本号一致的 ``vX.Y.Z`` Git tag，避免超级管理员输入被传成
    任意 git 参数。新版本必须高于历史版本，防止错误回退覆盖整批 OEM 节点。
    """
    version = (version or "").strip()
    target = _version_tuple(version)
    title = (title or "").strip()
    notes = (notes or "").strip()
    git_ref = (git_ref or "").strip()
    if not title:
        raise FleetError("NEXUS_BAD_RELEASE", "版本标题不能为空")
    if not notes:
        raise FleetError("NEXUS_BAD_RELEASE", "更新说明不能为空")
    if git_ref != f"v{version}":
        raise FleetError("NEXUS_BAD_GIT_REF", "Git tag 必须与版本一致（如 v1.7.0）")

    existing = s.execute(select(NexusRelease)).scalars().all()
    if any(row.version == version for row in existing):
        raise FleetError("NEXUS_RELEASE_EXISTS", "该版本已存在", 409)
    if existing and target <= max(_version_tuple(row.version) for row in existing):
        raise FleetError("NEXUS_VERSION_NOT_NEWER", "新版本必须高于已有版本")

    row = NexusRelease(
        version=version,
        title=title[:255],
        notes=notes[:20000],
        git_ref=git_ref,
    )
    s.add(row)
    s.flush()
    return _release_dict(row, [])


def start_canary(s, release_id: int, instance_id: int) -> Dict[str, Any]:
    """把草稿推送给一个灰度节点，开始真实环境监测。"""
    release = _release(s, release_id)
    if release.status not in {"draft", "paused", "canary"}:
        raise FleetError("NEXUS_RELEASE_STATE", "当前版本状态不能重新开始灰度")
    instance = s.get(NexusInstance, int(instance_id))
    if instance is None:
        raise FleetError("NEXUS_INSTANCE_NOT_FOUND", "灰度实例不存在", 404)
    if instance.status != "active":
        raise FleetError("NEXUS_INSTANCE_INACTIVE", "灰度实例当前已停用")

    _pause_other_active(s, release.id)
    release.status = "canary"
    release.canary_instance_id = instance.id
    release.updated_ts = _now_ms()
    _ensure_deployment(s, release, instance)
    s.flush()
    return get_release(s, release.id)


def publish(s, release_id: int) -> Dict[str, Any]:
    """把版本发布给全部处于授权有效状态的 OEM 实例。"""
    release = _release(s, release_id)
    if release.status not in {"draft", "canary", "paused", "published"}:
        raise FleetError("NEXUS_RELEASE_STATE", "当前版本状态不能全量发布")
    _pause_other_active(s, release.id)
    now = _now_ms()
    release.status = "published"
    release.updated_ts = now
    if release.published_ts is None:
        release.published_ts = now

    instances = s.execute(
        select(NexusInstance).where(NexusInstance.status == "active")
    ).scalars()
    for instance in instances:
        deployment = _ensure_deployment(s, release, instance)
        # 人工提前升级到目标或更高版本的节点直接记成功，不再重复构建。
        if _version_tuple(instance.version, strict=False) >= _version_tuple(
            release.version
        ):
            deployment.status = "success"
            deployment.detail = "节点当前版本已达到目标"
            deployment.updated_ts = now
            deployment.finished_ts = now
    s.flush()
    return get_release(s, release.id)


def pause(s, release_id: int) -> Dict[str, Any]:
    """暂停尚未被节点领取的版本；已在执行的节点不会被粗暴终止。"""
    release = _release(s, release_id)
    if release.status not in _ACTIVE_RELEASE_STATES:
        raise FleetError("NEXUS_RELEASE_STATE", "只有灰度或全量发布中的版本可以暂停")
    release.status = "paused"
    release.updated_ts = _now_ms()
    s.flush()
    return get_release(s, release.id)


def retry_failed(s, release_id: int) -> Dict[str, Any]:
    """把指定版本的失败节点明确重置为待处理。"""
    release = _release(s, release_id)
    rows = s.execute(
        select(NexusReleaseDeployment).where(
            NexusReleaseDeployment.release_id == release.id,
            NexusReleaseDeployment.status == "failed",
        )
    ).scalars()
    now = _now_ms()
    for row in rows:
        row.status = "pending"
        row.detail = "管理员已安排重试"
        row.updated_ts = now
        row.finished_ts = None
    s.flush()
    return get_release(s, release.id)


def _deployment_dict(
    row: NexusReleaseDeployment, instances: Dict[int, NexusInstance]
) -> Dict[str, Any]:
    """把节点投放记录转为控制台可直接展示的安全字段。"""
    instance = instances.get(row.instance_id)
    return {
        "instance_id": row.instance_id,
        "domain": instance.domain if instance else f"#{row.instance_id}",
        "status": row.status,
        "from_version": row.from_version,
        "to_version": row.to_version,
        "detail": row.detail,
        "attempts": int(row.attempts or 0),
        "updated_ts": row.updated_ts,
        "finished_ts": row.finished_ts,
    }


def _release_dict(
    row: NexusRelease, deployments: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """组装版本详情及各状态数量，供超级管理员列表一次渲染。"""
    counts = {
        state: sum(1 for item in deployments if item["status"] == state)
        for state in ("pending", "downloading", "installing", "success", "failed", "skipped")
    }
    return {
        "id": row.id,
        "version": row.version,
        "title": row.title,
        "notes": row.notes,
        "git_ref": row.git_ref,
        "status": row.status,
        "canary_instance_id": row.canary_instance_id,
        "created_ts": row.created_ts,
        "updated_ts": row.updated_ts,
        "published_ts": row.published_ts,
        "counts": counts,
        "deployments": deployments,
    }


def get_release(s, release_id: int) -> Dict[str, Any]:
    """读取一个版本及全部节点投放明细。"""
    release = _release(s, release_id)
    rows = s.execute(
        select(NexusReleaseDeployment)
        .where(NexusReleaseDeployment.release_id == release.id)
        .order_by(NexusReleaseDeployment.instance_id)
    ).scalars().all()
    instance_ids = {row.instance_id for row in rows}
    instances = {
        row.id: row
        for row in s.execute(
            select(NexusInstance).where(NexusInstance.id.in_(instance_ids))
        ).scalars()
    } if instance_ids else {}
    return _release_dict(
        release, [_deployment_dict(row, instances) for row in rows]
    )


def list_releases(s) -> List[Dict[str, Any]]:
    """按最新在前列出所有版本与投放状态。"""
    rows = s.execute(select(NexusRelease).order_by(NexusRelease.id.desc())).scalars()
    return [get_release(s, row.id) for row in rows]


def check_update(s, raw_key: str, current_version: str) -> Optional[Dict[str, Any]]:
    """节点用授权 KEY 拉取自己当前唯一可执行的升级任务。

    返回 ``None`` 表示没有更新。节点只会得到已分配给自己的 deployment，无法枚举
    其他 OEM 的版本状态或域名。
    """
    key = fleet._key_by_plain(s, raw_key)  # Nexus 内部共用同一套哈希与吊销校验
    if key.instance_id is None:
        raise FleetError("NEXUS_NOT_REDEEMED", "授权码尚未兑换开通", 403)
    instance = s.get(NexusInstance, key.instance_id)
    if instance is None or instance.status != "active":
        raise FleetError("NEXUS_INSTANCE_INACTIVE", "实例不存在或已停用", 403)

    now = _now_ms()
    deployments = s.execute(
        select(NexusReleaseDeployment)
        .where(NexusReleaseDeployment.instance_id == instance.id)
        .order_by(NexusReleaseDeployment.release_id.desc())
    ).scalars()
    for deployment in deployments:
        release = s.get(NexusRelease, deployment.release_id)
        if release is None or release.status not in _ACTIVE_RELEASE_STATES:
            continue
        if release.status == "canary" and release.canary_instance_id != instance.id:
            continue
        if deployment.status in {"success", "failed", "skipped"}:
            continue
        if deployment.status in {"downloading", "installing"}:
            if now - int(deployment.updated_ts or 0) < _STALE_INSTALL_MS:
                continue
            deployment.status = "pending"
            deployment.detail = "上次安装超时，节点重新领取"
            deployment.updated_ts = now

        if _version_tuple(current_version, strict=False) >= _version_tuple(
            release.version
        ):
            deployment.status = "success"
            deployment.detail = "节点当前版本已达到目标"
            deployment.updated_ts = now
            deployment.finished_ts = now
            instance.version = current_version[:64]
            continue
        return {
            "release_id": release.id,
            "version": release.version,
            "title": release.title,
            "notes": release.notes,
            "git_ref": release.git_ref,
            "published_ts": release.published_ts,
        }
    return None


def report_update(
    s,
    *,
    raw_key: str,
    release_id: int,
    status: str,
    current_version: str = "",
    detail: str = "",
) -> Dict[str, Any]:
    """接收节点的下载、安装、成功或失败状态并更新实例版本。"""
    status = (status or "").strip().lower()
    if status not in _REPORT_STATES:
        raise FleetError("NEXUS_BAD_UPDATE_STATUS", "更新状态不合法")
    key = fleet._key_by_plain(s, raw_key)
    if key.instance_id is None:
        raise FleetError("NEXUS_NOT_REDEEMED", "授权码尚未兑换开通", 403)
    deployment = s.get(
        NexusReleaseDeployment,
        {"release_id": int(release_id), "instance_id": key.instance_id},
    )
    if deployment is None:
        raise FleetError("NEXUS_UPDATE_NOT_ASSIGNED", "该更新未分配给此实例", 403)
    release = _release(s, release_id)

    # 成功状态不可倒退；失败也只能由管理员显式重置，杜绝节点自己形成重试风暴。
    if deployment.status == "success" and status != "success":
        raise FleetError("NEXUS_UPDATE_ALREADY_DONE", "该更新已经成功完成", 409)
    if deployment.status == "failed" and status != "failed":
        raise FleetError("NEXUS_UPDATE_RETRY_REQUIRED", "失败更新需管理员安排重试", 409)

    now = _now_ms()
    if status == "downloading" and deployment.status == "pending":
        deployment.attempts = int(deployment.attempts or 0) + 1
    deployment.status = status
    deployment.detail = (detail or "")[-2000:]
    deployment.updated_ts = now
    if status in {"success", "failed"}:
        deployment.finished_ts = now
    if status == "success":
        instance = s.get(NexusInstance, key.instance_id)
        if instance is not None:
            instance.version = (current_version or release.version)[:64]
    return {"ok": True, "status": deployment.status}
