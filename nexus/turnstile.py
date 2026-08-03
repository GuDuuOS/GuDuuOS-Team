"""Nexus OEM 邮箱验证码发送前的 Cloudflare Turnstile 校验。

这个模块只服务中央 Nexus 的 OEM 企业身份入口，不与各 OEM 节点的 Matrix 用户注册
共用密钥。浏览器只能读取 site key；secret、预期域名和最终校验都留在服务端。

环境变量：
    NEXUS_TURNSTILE_SITE_KEY       浏览器渲染小组件使用的公开 site key
    NEXUS_TURNSTILE_SECRET_KEY     服务端调用 Siteverify 使用的 secret
    NEXUS_TURNSTILE_HOSTNAME       预期门户域名，例如 dev-nexus.guduu.co

三个用途使用不同 action，避免某一页面取得的 token 被挪到另一个发码入口。配置不完整
时整个附加防线保持关闭，现有邮箱/IP 限频继续生效，便于先部署代码再由负责人创建组件。
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from nexus.fleet import FleetError

_SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
logger = logging.getLogger("nexus.turnstile")
_ACTIONS = {
    "register": "oem_register_code",
    "login": "oem_login_code",
    "reset": "oem_reset_code",
}


def _config() -> Dict[str, str]:
    """读取并规范化 Turnstile 配置；不在返回值之外缓存 secret。"""
    return {
        "site_key": os.environ.get("NEXUS_TURNSTILE_SITE_KEY", "").strip(),
        "secret_key": os.environ.get("NEXUS_TURNSTILE_SECRET_KEY", "").strip(),
        "hostname": os.environ.get("NEXUS_TURNSTILE_HOSTNAME", "")
        .strip()
        .lower()
        .rstrip("."),
    }


def enabled() -> bool:
    """返回 Nexus OEM Turnstile 是否已完整配置。"""
    config = _config()
    return bool(config["site_key"] and config["secret_key"] and config["hostname"])


def public_config() -> Dict[str, Any]:
    """返回可公开给门户的最小配置，绝不包含 secret 或预期域名。"""
    config = _config()
    active = bool(
        config["site_key"] and config["secret_key"] and config["hostname"]
    )
    return {
        "enabled": active,
        "site_key": config["site_key"] if active else "",
    }


def action_for(purpose: str) -> str:
    """把邮箱验证码用途映射为固定 Turnstile action。

    Args:
        purpose: ``register``、``login`` 或 ``reset``。

    Returns:
        传给 Turnstile 并由服务端再次核验的固定 action。
    """
    action = _ACTIONS.get((purpose or "").strip().lower())
    if action is None:
        raise FleetError("NEXUS_EMAIL_PURPOSE", "验证码用途不正确")
    return action


def verify(token: str, purpose: str, remote_ip: str = "") -> bool:
    """向 Cloudflare Siteverify 验证一次浏览器挑战。

    Args:
        token: 浏览器 Turnstile 小组件返回的一次性 response token。
        purpose: 当前邮箱验证码用途，用来隔离 action。
        remote_ip: 调用方观察到的来源 IP。当前仅为兼容既有调用保留；在源站无法证明
            该值是访客真实 IP 时，绝不能把 Cloudflare 边缘地址提交为 ``remoteip``。

    Returns:
        配置未启用或完整校验通过时返回 ``True``。

    Raises:
        FleetError: 已启用但 token 缺失、Cloudflare 不可达或域名/action 不匹配。
    """
    config = _config()
    if not (config["site_key"] and config["secret_key"] and config["hostname"]):
        # 灰度部署时允许先上代码再创建组件；原有业务限频仍然有效。
        return True

    expected_action = action_for(purpose)
    response_token = (token or "").strip()
    if not response_token:
        raise FleetError(
            "NEXUS_TURNSTILE_REQUIRED", "请先完成人机验证，再发送验证码", 400
        )

    fields = {"secret": config["secret_key"], "response": response_token}
    # ``remoteip`` 在 Cloudflare Siteverify 协议中是可选字段。生产 Nexus 位于
    # Cloudflare → Caddy 之后，而 Caddy 默认会把 X-Forwarded-For 收敛为它直接看到的
    # Cloudflare 边缘地址；把这个地址误当访客 IP 提交会让一个本来有效的浏览器 token
    # 校验失败。这里故意不发送该可选字段，仍严格核验 token、hostname 与 action。
    # 等源站改为只信任 Cloudflare 官方网段并可靠解析 CF-Connecting-IP 后，再评估恢复。
    _ = remote_ip
    request = Request(
        _SITEVERIFY_URL,
        data=urlencode(fields).encode("utf-8"),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "GuDuu-Nexus/Turnstile",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=6) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, ValueError, json.JSONDecodeError) as exc:
        # 已启用时必须 fail closed，避免 Cloudflare 短暂异常变成绕过窗口。
        raise FleetError(
            "NEXUS_TURNSTILE_UNAVAILABLE",
            "人机验证服务暂时不可用，请稍后重试",
            503,
        ) from exc

    hostname = str(payload.get("hostname") or "").strip().lower().rstrip(".")
    action = str(payload.get("action") or "").strip()
    if (
        payload.get("success") is not True
        or hostname != config["hostname"]
        or action != expected_action
    ):
        # 只记录 Cloudflare 返回的分类信息，禁止把一次性 token 或 secret 写入日志。
        # 这能让后续区分 token 过期、重复消费和配置错误，而不用靠用户截图猜测。
        logger.warning(
            "Turnstile 校验失败 errors=%s hostname=%s action=%s expected_hostname=%s "
            "expected_action=%s",
            payload.get("error-codes") or [],
            hostname,
            action,
            config["hostname"],
            expected_action,
        )
        raise FleetError(
            "NEXUS_TURNSTILE_FAILED", "人机验证未通过，请刷新后重试", 400
        )
    return True


__all__ = ["action_for", "enabled", "public_config", "verify"]
