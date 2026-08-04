"""GuDuu Nexus 平台功能开关。

这些开关属于运营控制项：超管需要在不重启服务的情况下决定某项 OEM 功能
是否对客户可见，因此持久化到 ``NexusSetting``，不能只放浏览器或环境变量。

``oem_network_visible`` 控制 OEM 门户的层级与归属数据；
``oem_token_grant_request_visible`` 控制 OEM 能否在授权申请里索要平台
Token。两者均默认关闭，而且必须在服务端同步执行，避免只隐藏前端
后被直接调用 API 绕过。
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict

from nexus.db import NexusSetting
from nexus.fleet import FleetError

_SETTING_KEY = "feature_flags"
_DEFAULTS: Dict[str, bool] = {
    # 负责人 2026-08-01 拍板：层级和归属用户数据先隐藏，由超管手动开放。
    "oem_network_visible": False,
    # OEM 可自由选择自己的 API 接入方；平台默认不附赠 Token。
    "oem_token_grant_request_visible": False,
}


def get_flags(s) -> Dict[str, bool]:
    """读取全部公开功能开关。

    参数 ``s`` 是 Nexus SQLAlchemy Session；返回值始终包含当前支持的全部
    布尔开关。数据库缺行、JSON 损坏或旧值类型不正确时都回退安全默认值。
    """
    row = s.get(NexusSetting, _SETTING_KEY)
    stored: Dict[str, Any] = {}
    if row is not None:
        try:
            value = json.loads(row.v or "{}")
            if isinstance(value, dict):
                stored = value
        except (TypeError, ValueError):
            stored = {}
    return {
        name: stored.get(name) if isinstance(stored.get(name), bool) else default
        for name, default in _DEFAULTS.items()
    }


def set_flags(s, data: Dict[str, Any]) -> Dict[str, bool]:
    """由平台超管更新功能开关并返回完整新状态。

    只接受白名单内的布尔字段，避免拼错字段后静默写入无效配置；未提交的字段
    保持原值，便于以后增加更多独立开关。
    """
    if not isinstance(data, dict):
        raise FleetError("NEXUS_FEATURE_FLAGS_INVALID", "功能开关格式不正确")
    unknown = sorted(set(data) - set(_DEFAULTS))
    if unknown:
        raise FleetError(
            "NEXUS_FEATURE_FLAG_UNKNOWN",
            "不支持的功能开关：" + "、".join(unknown),
        )
    current = get_flags(s)
    for name, value in data.items():
        if not isinstance(value, bool):
            raise FleetError(
                "NEXUS_FEATURE_FLAG_INVALID",
                f"{name} 必须是布尔值",
            )
        current[name] = value
    row = s.get(NexusSetting, _SETTING_KEY)
    if row is None:
        row = NexusSetting(k=_SETTING_KEY)
        s.add(row)
    row.v = json.dumps(current, ensure_ascii=False, sort_keys=True)
    row.updated_ts = int(time.time() * 1000)
    return current


def require_oem_network_visible(s) -> None:
    """要求 OEM 层级与用户数据已向客户开放，否则统一返回 403。"""
    if not get_flags(s)["oem_network_visible"]:
        raise FleetError(
            "NEXUS_FEATURE_DISABLED",
            "层级与归属用户数据暂未开放",
            403,
        )


__all__ = ["get_flags", "set_flags", "require_oem_network_visible"]
