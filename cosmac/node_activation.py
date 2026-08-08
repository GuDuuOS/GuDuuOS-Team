"""OEM 节点首次激活门禁。

节点拿到的 OEM KEY 只保存在容器环境变量里，浏览器永远不能读取。安装阶段若 Nexus
暂时不可达，节点仍可完成基础安装，但会保持受限态：仅 bootstrap 管理员能登录并通过
本模块让服务器代为向 Nexus 兑换授权；成功后以原子文件持久化激活结果。
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from typing import Any, Dict, Optional

import requests

from cosmac.config import CosmacConfig, _env

_STATE_LOCK = threading.Lock()


def required() -> bool:
    """返回当前节点是否启用了首次激活门禁。默认关闭，避免影响既有实例。"""
    return _env("NODE_ACTIVATION_REQUIRED", "0").strip().lower() in ("1", "true", "yes")


def _path() -> str:
    """返回持久化状态文件；发行版挂载到 bot 容器的独立数据目录。"""
    return _env("NODE_ACTIVATION_STATE_PATH", "/var/lib/cosmac/node-activation.json")


def _read_state() -> Dict[str, Any]:
    try:
        with open(_path(), "r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _write_state(value: Dict[str, Any]) -> None:
    target = _path()
    directory = os.path.dirname(target) or "."
    os.makedirs(directory, mode=0o700, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".activation-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle)
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def instance_id() -> Optional[int]:
    """读取已兑换的节点编号。

    品牌权限与是否启用首次激活门禁是两件事：存量节点可能已有激活
    文件，但暂时没有开启 ``NODE_ACTIVATION_REQUIRED``。因此这里始终读持久化
    状态，不依赖 ``required()``。损坏或缺失时返回 ``None``，上层品牌校验
    必须按未授权处理。
    """
    try:
        value = _read_state()
        if not isinstance(value, dict):
            return None
        raw = value.get("instance_id")
        parsed = int(raw)
        if value.get("activated") is True and parsed > 0:
            return parsed
    except (OSError, ValueError, TypeError):
        pass
    return None


def status() -> Dict[str, Any]:
    """读取不含 KEY 的最小激活状态，损坏状态一律按未激活处理。"""
    if not required():
        return {"required": False, "activated": True}
    try:
        value = _read_state()
        if isinstance(value, dict) and value.get("activated") is True:
            return {"required": True, "activated": True, "instance_id": value.get("instance_id")}
    except (OSError, ValueError, TypeError):
        pass
    return {"required": True, "activated": False}


def allows_public_access() -> bool:
    """注册等公众入口是否可用；未启用门禁的存量节点保持原行为。"""
    return bool(status()["activated"])


def record_instance_id(value: Any) -> int:
    """把 Nexus 已确认的节点编号原子写入持久化状态。

    首次安装和后续心跳都会调用这个入口，从而让没有留下旧版
    激活文件的存量节点自动修复身份。只接受正整数，不会持久化 KEY。
    """
    if isinstance(value, bool):
        raise ValueError("Nexus 实例编号不合法")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("Nexus 实例编号不合法") from error
    if parsed <= 0:
        raise ValueError("Nexus 实例编号不合法")

    with _STATE_LOCK:
        state = _read_state()
        state.update({"activated": True, "instance_id": parsed})
        _write_state(state)
    return parsed


def record_member_policy(value: Any) -> Dict[str, bool]:
    """Persist the Nexus-signed policy returned through the OEM-key heartbeat."""
    if not isinstance(value, dict):
        raise ValueError("节点会员策略不合法")
    required = value.get("lifetime_approval_required")
    if not isinstance(required, bool):
        raise ValueError("节点会员策略不合法")
    policy = {"lifetime_approval_required": required}
    with _STATE_LOCK:
        state = _read_state()
        state["member_policy"] = policy
        _write_state(state)
    return policy


def lifetime_approval_required() -> bool:
    """Whether manual permanent membership grants must be rejected on this node."""
    policy = _read_state().get("member_policy")
    return bool(
        isinstance(policy, dict)
        and policy.get("lifetime_approval_required") is True
    )


def activate(config: CosmacConfig) -> Dict[str, Any]:
    """由节点服务器携带环境中的 KEY 兑换授权并原子保存成功状态。"""
    current = status()
    if current["activated"]:
        return current
    nexus_url = _env("NEXUS_URL").rstrip("/")
    raw_key = _env("OEM_KEY")
    node_region = _env("NODE_REGION")
    if not nexus_url or not raw_key or not node_region:
        raise RuntimeError(
            "节点未配置 Nexus 地址、OEM 授权码或机房地域，请联系平台处理"
        )
    try:
        response = requests.post(
            nexus_url + "/nexus/redeem",
            json={
                "key": raw_key,
                "domain": config.server_name,
                "admin_email": _env("ADMIN_EMAIL"),
                "region": node_region,
            },
            timeout=20,
        )
        payload = response.json() if response.content else {}
    except (requests.RequestException, ValueError) as error:
        raise RuntimeError("暂时无法连接 Nexus，请检查网络后重试") from error
    if not response.ok or not isinstance(payload, dict) or not payload.get("instance_id"):
        raise RuntimeError(str(payload.get("error") or "Nexus 拒绝激活请求"))
    parsed = record_instance_id(payload["instance_id"])
    return {"required": True, "activated": True, "instance_id": parsed}
