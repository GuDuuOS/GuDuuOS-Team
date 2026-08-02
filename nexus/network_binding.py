"""Nexus KEY 的域名与公网 IP 绑定工具。

公网 IP 只用于“是否与申请值一致”的比较，不需要保存原文。本模块统一完成地址规范化、
HMAC 指纹和脱敏展示，避免申请、审批、兑换三个阶段各自实现后产生口径差异。
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os

from nexus import geo


def normalize_ip(value: str) -> str:
    """规范化 IPv4/IPv6；空值允许，非法值返回可读业务错误。"""
    raw = (value or "").strip()
    if not raw or raw == "?":
        return ""
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError as error:
        from nexus.fleet import FleetError

        raise FleetError("NEXUS_BAD_PUBLIC_IP", "计划公网 IP 格式不正确") from error


def fingerprint(value: str) -> str:
    """把规范化 IP 转成不可逆 HMAC；缺主密钥时绝不退化为普通哈希。"""
    normalized = normalize_ip(value)
    if not normalized:
        return ""
    secret = os.environ.get("NEXUS_SECRET_KEY", "").strip()
    if len(secret) < 32:
        from nexus.fleet import FleetError

        raise FleetError(
            "NEXUS_SECRET_KEY_MISSING",
            "公网 IP 安全绑定需要先配置 NEXUS_SECRET_KEY",
            503,
        )
    return hmac.new(
        secret.encode("utf-8"),
        ("nexus-key-ip:" + normalized).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def masked(value: str) -> str:
    """返回仅供界面核对的脱敏网段，不把完整公网地址写入数据库。"""
    normalized = normalize_ip(value)
    return geo.mask_ip(normalized) if normalized else ""
