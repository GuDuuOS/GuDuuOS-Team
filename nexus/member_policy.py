"""Per-instance membership issuance policy managed by Nexus superadmins."""

from __future__ import annotations

import json
import time
from typing import Any, Dict

from nexus.db import NexusInstance, NexusSetting
from nexus.fleet import FleetError

_SETTING_KEY = "instance_member_policies"
_POLICY_NAME = "lifetime_approval_required"


def _load(s) -> Dict[str, Dict[str, bool]]:
    row = s.get(NexusSetting, _SETTING_KEY)
    if row is None:
        return {}
    try:
        payload = json.loads(row.v or "{}")
    except (TypeError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    result: Dict[str, Dict[str, bool]] = {}
    for raw_instance_id, raw_policy in payload.items():
        try:
            instance_id = int(raw_instance_id)
        except (TypeError, ValueError):
            continue
        if instance_id <= 0 or not isinstance(raw_policy, dict):
            continue
        required = raw_policy.get(_POLICY_NAME)
        if isinstance(required, bool):
            result[str(instance_id)] = {_POLICY_NAME: required}
    return result


def get_policy(s, instance_id: int) -> Dict[str, bool]:
    """Return the effective policy; unconfigured nodes keep direct grants enabled."""
    try:
        parsed = int(instance_id)
    except (TypeError, ValueError) as exc:
        raise FleetError("NEXUS_BAD_INSTANCE", "节点编号不正确") from exc
    if parsed <= 0:
        raise FleetError("NEXUS_BAD_INSTANCE", "节点编号不正确")
    stored = _load(s).get(str(parsed), {})
    return {_POLICY_NAME: bool(stored.get(_POLICY_NAME, False))}


def set_policy(
    s, instance_id: int, lifetime_approval_required: Any
) -> Dict[str, bool]:
    """Persist one node's policy; only a real boolean is accepted."""
    try:
        parsed = int(instance_id)
    except (TypeError, ValueError) as exc:
        raise FleetError("NEXUS_BAD_INSTANCE", "节点编号不正确") from exc
    if parsed <= 0 or s.get(NexusInstance, parsed) is None:
        raise FleetError("NEXUS_INSTANCE_MISSING", "实例不存在", 404)
    if not isinstance(lifetime_approval_required, bool):
        raise FleetError(
            "NEXUS_MEMBER_POLICY_INVALID",
            "终身会员审批开关必须是布尔值",
        )
    policies = _load(s)
    if lifetime_approval_required:
        policies[str(parsed)] = {_POLICY_NAME: True}
    else:
        # 默认就是关闭；删除空配置可避免节点越来越多时
        # 留下无意义记录。
        policies.pop(str(parsed), None)
    row = s.get(NexusSetting, _SETTING_KEY)
    if row is None:
        row = NexusSetting(k=_SETTING_KEY)
        s.add(row)
    row.v = json.dumps(policies, ensure_ascii=False, sort_keys=True)
    row.updated_ts = int(time.time() * 1000)
    s.flush()
    return get_policy(s, parsed)


__all__ = ["get_policy", "set_policy"]
