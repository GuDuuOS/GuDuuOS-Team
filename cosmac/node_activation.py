"""OEM 节点首次激活门禁。

节点拿到的 OEM KEY 只保存在容器环境变量里，浏览器永远不能读取。安装阶段若 Nexus
暂时不可达，节点仍可完成基础安装，但会保持受限态：仅 bootstrap 管理员能登录并通过
本模块让服务器代为向 Nexus 兑换授权；成功后以原子文件持久化激活结果。
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Dict

import requests

from cosmac.config import CosmacConfig, _env


def required() -> bool:
    """返回当前节点是否启用了首次激活门禁。默认关闭，避免影响既有实例。"""
    return _env("NODE_ACTIVATION_REQUIRED", "0").strip().lower() in ("1", "true", "yes")


def _path() -> str:
    """返回持久化状态文件；发行版挂载到 bot 容器的独立数据目录。"""
    return _env("NODE_ACTIVATION_STATE_PATH", "/var/lib/cosmac/node-activation.json")


def status() -> Dict[str, Any]:
    """读取不含 KEY 的最小激活状态，损坏状态一律按未激活处理。"""
    if not required():
        return {"required": False, "activated": True}
    try:
        with open(_path(), "r", encoding="utf-8") as handle:
            value = json.load(handle)
        if isinstance(value, dict) and value.get("activated") is True:
            return {"required": True, "activated": True, "instance_id": value.get("instance_id")}
    except (OSError, ValueError, TypeError):
        pass
    return {"required": True, "activated": False}


def allows_public_access() -> bool:
    """注册等公众入口是否可用；未启用门禁的存量节点保持原行为。"""
    return bool(status()["activated"])


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
    target = _path()
    os.makedirs(os.path.dirname(target), mode=0o700, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".activation-", dir=os.path.dirname(target))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"activated": True, "instance_id": int(payload["instance_id"])}, handle)
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {"required": True, "activated": True, "instance_id": int(payload["instance_id"])}
