"""Nexus 节点发布环境与自动灰度策略。

发布必须明确区分三类节点：开发节点不接收任何自动任务，灰度节点在 CI
登记不可变镜像后自动试装，生产节点只在灰度成功且超管人工确认后才获得
任务。策略保存在 ``NexusSetting``，便于以后增加节点时在超管页修改，
不把客户机器编号硬编码到发布状态机里。
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List

from nexus.db import NexusSetting
from nexus.fleet import FleetError

_SETTING_KEY = "release_policy"
_DEFAULTS: Dict[str, Any] = {
    # 负责人 2026-08-05 确认的初始环境：1=开发，2=公司技术灰度，
    # 3=官网正式节点。生产节点尚未部署也可以先保存编号。
    "development_instance_ids": [1],
    "canary_instance_id": 2,
    "production_instance_ids": [3],
    "auto_canary": True,
    "require_canary_success": True,
    # 新装基线不等于向生产节点发布。0 表示尚未显式指定，
    # 安装器会兼容回退到既有 published/rollback 版本。
    "install_baseline_release_id": 0,
}


def _clean_ids(value: Any, field: str) -> List[int]:
    """校验节点编号数组，返回去重后的升序整数。"""
    if not isinstance(value, list):
        raise FleetError(
            "NEXUS_RELEASE_POLICY_INVALID", f"{field} 必须是节点编号数组"
        )
    cleaned: List[int] = []
    for item in value:
        # bool 是 int 的子类，必须单独拒绝，否则 true 会被误当成节点 1。
        if isinstance(item, bool):
            raise FleetError(
                "NEXUS_RELEASE_POLICY_INVALID", f"{field} 包含无效节点编号"
            )
        try:
            instance_id = int(item)
        except (TypeError, ValueError) as exc:
            raise FleetError(
                "NEXUS_RELEASE_POLICY_INVALID", f"{field} 包含无效节点编号"
            ) from exc
        if instance_id <= 0:
            raise FleetError(
                "NEXUS_RELEASE_POLICY_INVALID", f"{field} 只能填正整数"
            )
        cleaned.append(instance_id)
    if len(cleaned) > 1000:
        raise FleetError("NEXUS_RELEASE_POLICY_INVALID", f"{field} 节点数过多")
    return sorted(set(cleaned))


def _normalize(data: Dict[str, Any]) -> Dict[str, Any]:
    """把完整策略归一化，并阻止一个节点同时承担多个环境。"""
    development = _clean_ids(
        data.get("development_instance_ids"), "开发节点"
    )
    production = _clean_ids(
        data.get("production_instance_ids"), "生产节点"
    )
    raw_canary = data.get("canary_instance_id")
    if isinstance(raw_canary, bool):
        raise FleetError("NEXUS_RELEASE_POLICY_INVALID", "灰度节点编号无效")
    try:
        canary = int(raw_canary or 0)
    except (TypeError, ValueError) as exc:
        raise FleetError(
            "NEXUS_RELEASE_POLICY_INVALID", "灰度节点编号无效"
        ) from exc
    if canary < 0:
        raise FleetError(
            "NEXUS_RELEASE_POLICY_INVALID", "灰度节点编号不能为负数"
        )
    raw_baseline = data.get("install_baseline_release_id")
    if isinstance(raw_baseline, bool):
        raise FleetError("NEXUS_RELEASE_POLICY_INVALID", "新装基线版本编号无效")
    try:
        install_baseline = int(raw_baseline or 0)
    except (TypeError, ValueError) as exc:
        raise FleetError(
            "NEXUS_RELEASE_POLICY_INVALID", "新装基线版本编号无效"
        ) from exc
    if install_baseline < 0:
        raise FleetError(
            "NEXUS_RELEASE_POLICY_INVALID", "新装基线版本编号不能为负数"
        )
    for field in ("auto_canary", "require_canary_success"):
        if not isinstance(data.get(field), bool):
            raise FleetError(
                "NEXUS_RELEASE_POLICY_INVALID", f"{field} 必须是布尔值"
            )
    if set(development) & set(production):
        raise FleetError(
            "NEXUS_RELEASE_POLICY_OVERLAP", "开发节点不能同时属于生产环境"
        )
    if canary and (canary in development or canary in production):
        raise FleetError(
            "NEXUS_RELEASE_POLICY_OVERLAP",
            "灰度节点不能同时属于开发或生产环境",
        )
    if data["auto_canary"] and not canary:
        raise FleetError(
            "NEXUS_RELEASE_POLICY_INVALID", "自动灰度开启时必须指定灰度节点"
        )
    if data["require_canary_success"] and not canary:
        raise FleetError(
            "NEXUS_RELEASE_POLICY_INVALID", "灰度门禁开启时必须指定灰度节点"
        )
    return {
        "development_instance_ids": development,
        "canary_instance_id": canary,
        "production_instance_ids": production,
        "auto_canary": data["auto_canary"],
        "require_canary_success": data["require_canary_success"],
        "install_baseline_release_id": install_baseline,
    }


def get_policy(s) -> Dict[str, Any]:
    """读取策略；旧库没有设置行时使用已确认的 1/2/3 默认值。"""
    row = s.get(NexusSetting, _SETTING_KEY)
    if row is None:
        return _normalize(dict(_DEFAULTS))
    try:
        stored = json.loads(row.v or "{}")
        if not isinstance(stored, dict):
            raise ValueError("release policy is not an object")
        merged = dict(_DEFAULTS)
        merged.update({key: stored[key] for key in _DEFAULTS if key in stored})
        return _normalize(merged)
    except (TypeError, ValueError, FleetError):
        # 运营策略损坏时回到保守默认，不得因一行 JSON 让 CI webhook 失败。
        return _normalize(dict(_DEFAULTS))


def set_policy(s, data: Dict[str, Any]) -> Dict[str, Any]:
    """由超管部分更新发布策略，并返回完整持久化结果。"""
    if not isinstance(data, dict):
        raise FleetError("NEXUS_RELEASE_POLICY_INVALID", "发布策略格式不正确")
    unknown = sorted(set(data) - set(_DEFAULTS))
    if unknown:
        raise FleetError(
            "NEXUS_RELEASE_POLICY_UNKNOWN",
            "不支持的发布策略：" + "、".join(unknown),
        )
    merged = get_policy(s)
    merged.update(data)
    normalized = _normalize(merged)
    row = s.get(NexusSetting, _SETTING_KEY)
    if row is None:
        row = NexusSetting(k=_SETTING_KEY)
        s.add(row)
    row.v = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
    row.updated_ts = int(time.time() * 1000)
    return normalized
