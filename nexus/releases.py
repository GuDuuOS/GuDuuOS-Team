"""GuDuu Nexus 版本发布中心。

这个模块只负责版本状态机与节点投放记录，不负责在远端服务器执行 shell。真正的升级
由 OEM 宿主机上的 ``distro/update_agent.py`` 主动拉取任务后完成。这样 Nexus 不需要
保存客户 SSH 凭据，也不会因为客户服务器位于 NAT/防火墙后而失效。
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select

from cosmac import __version__ as PRODUCT_VERSION
from nexus import fleet, release_artifacts
from nexus.db import (
    NexusInstance,
    NexusKeyClaim,
    NexusRelease,
    NexusReleaseArtifact,
    NexusReleaseDeployment,
    NexusReleaseTrack,
)
from nexus.fleet import FleetError


_VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_DEVLOG_HEADER_RE = re.compile(
    r"^##\s+\d{4}-\d{2}-\d{2}\s+—\s+GuDuu OS\s+"
    r"(?P<version>\d+\.\d+\.\d+)\s+\([^)]+\)\s*$"
)
_REPORT_STATES = {"downloading", "installing", "success", "failed"}
_ACTIVE_RELEASE_STATES = {"canary", "published", "rollback"}
_RELEASE_TARGETS = {"nexus", "node"}
# 下载/构建被强制中断时，任务不能永久卡在 installing。超过一小时后允许同一节点
# 再次领取；正常升级一般远低于一小时，这个阈值不会制造并发执行。
_STALE_INSTALL_MS = 60 * 60 * 1000
_DEFAULT_DEVLOG_PATH = Path(__file__).resolve().parents[1] / "DEVLOG.md"


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


def _release_target(s, release: NexusRelease) -> str:
    """读取发布对象；没有扩展记录的历史数据按 OEM 节点版本兼容处理。"""
    track = s.get(NexusReleaseTrack, int(release.id))
    if track is None or track.target not in _RELEASE_TARGETS:
        return "node"
    return str(track.target)


def _require_node_target(s, release: NexusRelease, action: str) -> None:
    """阻止 Nexus 平台公告误进入节点安装、灰度或回撤状态机。"""
    if _release_target(s, release) != "node":
        raise FleetError(
            "NEXUS_RELEASE_TARGET",
            f"Nexus 平台更新不能执行{action}；它只需发布到 OEM 后台",
        )


def _merge_wrapped(chunks: List[str]) -> str:
    """把 Markdown 为控制行宽拆开的片段恢复为自然文本。

    纯中文换行处不应凭空插入空格；边界任一侧是英文/数字时保留一个空格。这个小规则
    既保住“OEM 门户”“Git tag”的中英文间距，也避免“业务群 自动”一类中文断句瑕疵。
    """
    if not chunks:
        return ""
    merged = chunks[0]
    for chunk in chunks[1:]:
        separator = " " if merged[-1:].isascii() or chunk[:1].isascii() else ""
        merged += separator + chunk
    return merged


def _devlog_items(path: Path, version: str) -> List[str]:
    """读取指定版本的 DEVLOG 条目，并把 Markdown 换行整理成公告短句。

    Args:
        path: 开发日志文件路径；独立参数便于单元测试使用临时文件。
        version: 要提取的不带 ``v`` 的三段版本号。

    Returns:
        保持 DEVLOG 顺序的纯文本条目；每个跨行条目会合并为一行。

    Raises:
        FleetError: 文件不可读、找不到当前版本或当前版本没有对外条目时抛出。
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise FleetError(
            "NEXUS_DEVLOG_UNAVAILABLE", "无法读取 DEVLOG.md，暂不能自动生成"
        ) from exc

    inside = False
    current: List[str] = []
    items: List[str] = []
    for line in lines:
        header = _DEVLOG_HEADER_RE.match(line)
        if header:
            if inside:
                break
            inside = header.group("version") == version
            continue
        if inside and line.startswith("## "):
            break
        if not inside:
            continue
        if line.startswith("- "):
            if current:
                items.append(_merge_wrapped(current))
            current = [line[2:].strip()]
        elif current and line.startswith("  "):
            # DEVLOG 为控制行宽会折行；公告应恢复为一条连续的自然语言。
            current.append(line.strip())
    if current:
        items.append(_merge_wrapped(current))
    if not inside:
        raise FleetError(
            "NEXUS_DEVLOG_VERSION_MISSING",
            f"DEVLOG.md 中没有 GuDuu OS {version} 的版本说明",
        )
    if not items:
        raise FleetError(
            "NEXUS_DEVLOG_EMPTY", f"GuDuu OS {version} 尚未填写可发布的更新内容"
        )
    # 门户展示的是纯文本公告，去掉日志中用于代码/强调的 Markdown 符号，避免 OEM
    # 看到面向开发者的排版标记。其他标点与专有名词原样保留，避免改写造成信息失真。
    return [item.replace("**", "").replace("`", "") for item in items]


def build_release_draft(
    s,
    *,
    version: Optional[str] = None,
    devlog_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """根据当前产品版本和 DEVLOG 自动生成一份可审阅的未发布版本草稿。

    这里刻意使用确定性的日志归纳，不依赖外部大模型：发布后台在断网、未配置 AI key
    时仍可生成，且不会把内部版本日志发送给第三方。返回值只回填表单，真正落库仍要
    超级管理员点击“保存为未发布”，保留人工审阅门禁。

    Args:
        s: Nexus SQLAlchemy Session，用于判断该版本是否已经创建。
        version: 测试或运维指定版本；默认读取 ``cosmac.__version__``。
        devlog_path: 测试指定日志路径；默认使用仓库根目录 ``DEVLOG.md``。
    """
    target = (version or PRODUCT_VERSION).strip()
    _version_tuple(target)
    items = _devlog_items(devlog_path or _DEFAULT_DEVLOG_PATH, target)
    first = re.sub(r"^(新增|修复|优化|变更)(?:（[^）]+）)?：", "", items[0])
    first_clause = re.split(r"[，；。]", first, maxsplit=1)[0].strip()
    title = first_clause[:80] or f"GuDuu OS {target} 更新"
    notes = "GuDuu OS " + target + " 更新公告\n\n" + "\n".join(
        "• " + item for item in items
    )
    exists = s.execute(
        select(NexusRelease.id).where(NexusRelease.version == target)
    ).first()
    manifest = release_artifacts.find_manifest(s, target)
    return {
        "version": target,
        "git_ref": "v" + target,
        "title": title,
        "notes": notes,
        "source": "DEVLOG.md",
        "already_exists": exists is not None,
        "image_manifest": manifest,
    }


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
    """激活节点版本时只暂停其他节点轨道，绝不撤下 Nexus 平台公告。"""
    rows = s.execute(
        select(NexusRelease).where(NexusRelease.status.in_(_ACTIVE_RELEASE_STATES))
    ).scalars()
    now = _now_ms()
    for row in rows:
        if row.id != keep_id and _release_target(s, row) == "node":
            row.status = "paused"
            row.updated_ts = now


def create_release(
    s,
    *,
    version: str,
    title: str,
    notes: str,
    git_ref: str,
    target: str = "node",
    delivery_mode: str = "legacy_git",
) -> Dict[str, Any]:
    """创建带明确发布对象的草稿版本。

    自动更新只接受与版本号一致的 ``vX.Y.Z`` Git tag，避免超级管理员输入被传成
    任意 git 参数。新版本必须高于历史版本，防止错误回退覆盖整批 OEM 节点。
    """
    version = (version or "").strip()
    version_order = _version_tuple(version)
    title = (title or "").strip()
    notes = (notes or "").strip()
    git_ref = (git_ref or "").strip()
    target = (target or "").strip().lower()
    if target not in _RELEASE_TARGETS:
        raise FleetError(
            "NEXUS_BAD_RELEASE_TARGET", "更新对象必须是 Nexus 平台或 OEM 节点"
        )
    if not title:
        raise FleetError("NEXUS_BAD_RELEASE", "版本标题不能为空")
    if not notes:
        raise FleetError("NEXUS_BAD_RELEASE", "更新说明不能为空")
    if git_ref != f"v{version}":
        raise FleetError("NEXUS_BAD_GIT_REF", "Git tag 必须与版本一致（如 v1.7.0）")

    existing = s.execute(select(NexusRelease)).scalars().all()
    if any(row.version == version for row in existing):
        raise FleetError("NEXUS_RELEASE_EXISTS", "该版本已存在", 409)
    if existing and version_order <= max(
        _version_tuple(row.version) for row in existing
    ):
        raise FleetError("NEXUS_VERSION_NOT_NEWER", "新版本必须高于已有版本")

    row = NexusRelease(
        version=version,
        title=title[:255],
        notes=notes[:20000],
        git_ref=git_ref,
    )
    s.add(row)
    s.flush()
    s.add(NexusReleaseTrack(release_id=row.id, target=target))
    # Nexus 平台是集中托管公告，不需要节点交付物。新节点版本由门户显式要求
    # container；直接调用未传参数时继续兼容历史测试和救援脚本的 strict Git 模式。
    if target == "node" and delivery_mode == "container":
        row._nexus_artifact = release_artifacts.freeze_for_release(
            s, int(row.id), version
        )
    elif target == "node" and delivery_mode != "legacy_git":
        raise FleetError("NEXUS_BAD_DELIVERY_MODE", "节点交付方式不合法")
    s.flush()
    return _release_dict(row, [], target)


def start_canary(s, release_id: int, instance_id: int) -> Dict[str, Any]:
    """把草稿推送给一个灰度节点，开始真实环境监测。"""
    release = _release(s, release_id)
    _require_node_target(s, release, "节点灰度")
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
    """按发布轨道上线公告，或给全部有效 OEM 实例创建安装任务。"""
    release = _release(s, release_id)
    target = _release_target(s, release)
    if target == "nexus":
        if release.status not in {"draft", "paused", "published"}:
            raise FleetError("NEXUS_RELEASE_STATE", "当前 Nexus 更新不能发布公告")
        now = _now_ms()
        release.status = "published"
        release.updated_ts = now
        if release.published_ts is None:
            release.published_ts = now
        s.flush()
        return get_release(s, release.id)

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


def rollback(s, release_id: int) -> Dict[str, Any]:
    """把全部活动 OEM 节点回撤到一个曾经全量发布过的历史版本。

    回撤复用历史版本冻结的不可变镜像摘要；镜像发布前的旧记录则兼容严格 Git tag。
    同时会重置该版本的逐节点投放状态。这样
    超级管理员看到的始终是“这次回撤”的实时结果，而不是该版本第一次发布时留下的
    success。未全量发布过的草稿/灰度版本不能作为回撤目标，避免把未经验证的代码借
    “回撤”名义推向全舰队。
    """
    release = _release(s, release_id)
    _require_node_target(s, release, "节点回撤")
    if release.published_ts is None:
        raise FleetError(
            "NEXUS_RELEASE_NOT_PUBLISHED",
            "只有曾经全量发布过的历史版本才能回撤",
        )
    if release.status in _ACTIVE_RELEASE_STATES:
        raise FleetError(
            "NEXUS_RELEASE_ALREADY_ACTIVE",
            "该版本已经是当前活动版本，无需回撤",
        )

    _pause_other_active(s, release.id)
    now = _now_ms()
    release.status = "rollback"
    release.canary_instance_id = None
    release.updated_ts = now

    instances = s.execute(
        select(NexusInstance).where(NexusInstance.status == "active")
    ).scalars()
    for instance in instances:
        deployment = _ensure_deployment(s, release, instance)
        deployment.from_version = instance.version or ""
        deployment.to_version = release.version
        deployment.attempts = 0
        deployment.updated_ts = now
        deployment.finished_ts = None
        # 已经处于目标版本的节点不需要重装；其余节点无论高于还是低于目标，都应
        # 精确切换到选中的版本，不能沿用普通升级的“高于目标也算成功”规则。
        if _version_tuple(instance.version, strict=False) == _version_tuple(
            release.version
        ):
            deployment.status = "success"
            deployment.detail = "节点已经处于回撤目标版本"
            deployment.finished_ts = now
        else:
            deployment.status = "pending"
            deployment.detail = "超级管理员已发起版本回撤"
    s.flush()
    return get_release(s, release.id)


def pause(s, release_id: int) -> Dict[str, Any]:
    """暂停节点投放；Nexus 轨道则撤下仍保留在历史列表中的公告。"""
    release = _release(s, release_id)
    target = _release_target(s, release)
    if target == "nexus":
        if release.status != "published":
            raise FleetError("NEXUS_RELEASE_STATE", "只有已发布的平台公告可以撤下")
        release.status = "paused"
        release.updated_ts = _now_ms()
        s.flush()
        return get_release(s, release.id)
    if release.status not in _ACTIVE_RELEASE_STATES:
        raise FleetError("NEXUS_RELEASE_STATE", "只有灰度或全量发布中的版本可以暂停")
    release.status = "paused"
    release.updated_ts = _now_ms()
    s.flush()
    return get_release(s, release.id)


def retry_failed(s, release_id: int) -> Dict[str, Any]:
    """把指定版本的失败节点明确重置为待处理。"""
    release = _release(s, release_id)
    _require_node_target(s, release, "节点重试")
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
    row: NexusRelease, deployments: List[Dict[str, Any]], target: str
) -> Dict[str, Any]:
    """组装版本详情及各状态数量，供超级管理员列表一次渲染。"""
    counts = {
        state: sum(1 for item in deployments if item["status"] == state)
        for state in ("pending", "downloading", "installing", "success", "failed", "skipped")
    }
    # 这个函数没有 Session 参数；调用方先临时附加只读属性，避免为了一个扩展表把所有
    # 组装路径改成额外查询参数。SQLAlchemy 模型允许普通 Python 临时属性。
    artifact = release_artifacts.artifact_dict(
        getattr(row, "_nexus_artifact", None)
    )
    return {
        "id": row.id,
        "version": row.version,
        "title": row.title,
        "notes": row.notes,
        "git_ref": row.git_ref,
        "artifact": artifact,
        "target": target,
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
    release._nexus_artifact = s.get(NexusReleaseArtifact, int(release.id))
    return _release_dict(
        release,
        [_deployment_dict(row, instances) for row in rows],
        _release_target(s, release),
    )


def list_releases(s) -> List[Dict[str, Any]]:
    """按最新在前列出所有版本与投放状态。"""
    rows = s.execute(select(NexusRelease).order_by(NexusRelease.id.desc())).scalars()
    return [get_release(s, row.id) for row in rows]


def list_oem_announcements(s, oem_id: int) -> List[Dict[str, Any]]:
    """合并全租户 Nexus 公告与当前 OEM 节点安装成功公告。

    Nexus 是集中式多租户后台，所以平台更新发布后所有 OEM 立即看到同一条公告，
    不需要也不存在“每个客户安装 Nexus”的投放记录。节点更新仍从“版本说明 + 成功
    投放记录”实时组合，并先经 KEY 归属边收窄实例，不能泄露其他 OEM 的域名。

    Args:
        s: Nexus SQLAlchemy Session。
        oem_id: 当前已登录 OEM 账号编号。

    Returns:
        最新完成在前的公告列表；``target`` 区分 Nexus 平台与 OEM 节点。
    """
    announcements: List[Dict[str, Any]] = []

    # 平台公告面向所有已登录 OEM。只取当前仍为 published 的 Nexus 轨道；撤下公告
    # 会保留历史记录和 published_ts，但不会继续出现在客户门户。
    platform_rows = s.execute(
        select(NexusRelease)
        .where(NexusRelease.status == "published")
        .order_by(NexusRelease.published_ts.desc())
    ).scalars()
    for release in platform_rows:
        if _release_target(s, release) != "nexus":
            continue
        announcements.append(
            {
                "id": f"nexus:{release.id}",
                "release_id": release.id,
                "instance_id": None,
                "domain": "",
                "target": "nexus",
                "version": release.version,
                "title": release.title,
                "notes": release.notes,
                "finished_ts": release.published_ts,
            }
        )

    owned_key_ids = select(NexusKeyClaim.key_id).where(
        NexusKeyClaim.oem_id == int(oem_id)
    )
    instances = s.execute(
        select(NexusInstance).where(NexusInstance.key_id.in_(owned_key_ids))
    ).scalars().all()
    instance_by_id = {row.id: row for row in instances}
    rows: List[NexusReleaseDeployment] = []
    if instance_by_id:
        rows = s.execute(
            select(NexusReleaseDeployment)
            .where(
                NexusReleaseDeployment.instance_id.in_(instance_by_id),
                NexusReleaseDeployment.status == "success",
            )
            .order_by(NexusReleaseDeployment.finished_ts.desc())
            .limit(30)
        ).scalars().all()
    release_ids = {row.release_id for row in rows}
    release_by_id = {
        row.id: row
        for row in s.execute(
            select(NexusRelease).where(NexusRelease.id.in_(release_ids))
        ).scalars()
    } if release_ids else {}
    for row in rows:
        release = release_by_id.get(row.release_id)
        instance = instance_by_id.get(row.instance_id)
        if (
            release is None
            or instance is None
            or _release_target(s, release) != "node"
        ):
            continue
        announcements.append(
            {
                "id": f"{row.release_id}:{row.instance_id}",
                "release_id": row.release_id,
                "instance_id": row.instance_id,
                "domain": instance.domain,
                "target": "node",
                "version": release.version,
                "title": release.title,
                "notes": release.notes,
                "finished_ts": row.finished_ts,
            }
        )
    announcements.sort(
        key=lambda item: int(item.get("finished_ts") or 0), reverse=True
    )
    return announcements[:30]


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
        if _release_target(s, release) != "node":
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

        current_tuple = _version_tuple(current_version, strict=False)
        target_tuple = _version_tuple(release.version)
        reached_target = (
            current_tuple == target_tuple
            if release.status == "rollback"
            else current_tuple >= target_tuple
        )
        if reached_target:
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
            "artifact": release_artifacts.artifact_dict(
                s.get(NexusReleaseArtifact, int(release.id))
            ),
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
    _require_node_target(s, release, "节点状态上报")

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
