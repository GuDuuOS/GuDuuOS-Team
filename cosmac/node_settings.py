"""OEM 节点首次配置向导的安全存储与运行时读取。

公开品牌字段与敏感凭据严格分层：品牌信息直接存 JSON，SMTP 密码、模型 API Key、
支付密钥使用安装器生成的 ``COSMAC_NODE_SETTINGS_SECRET`` 派生 Fernet 密钥加密。
管理接口也只返回 ``*_configured`` 布尔值，永不回传已经保存的密钥原文。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any, Dict

from cryptography.fernet import Fernet, InvalidToken

from cosmac.db import session_scope
from cosmac.db.models import NodeSetting

DEFAULT_PUBLIC: Dict[str, Any] = {
    "brand": {"product_name": "GuDuu OS", "company_name": "", "logo_data_url": ""},
    "email": {
        "host": "", "port": 465, "user": "", "from_address": "",
        "from_name": "GuDuu OS", "security": "ssl",
    },
    "ai": {"provider": "echo", "model": "", "base_url": ""},
    "payment": {"provider": "none", "mode": "sandbox", "merchant_id": ""},
}


class NodeSettingsError(ValueError):
    """节点设置缺失、格式不合法或主密钥错误。"""


def _fernet() -> Fernet:
    """从节点独立主密钥派生 Fernet key；缺失时拒绝明文降级。"""
    secret = os.environ.get("COSMAC_NODE_SETTINGS_SECRET", "").strip()
    if not secret:
        # 1.24.0 以前的节点没有独立设置主密钥；镜像升级不会改宿主 compose/.env，
        # 因此用既有且同样只在服务端保存的管理员令牌做一次兼容派生。新安装永远走独立密钥。
        secret = os.environ.get("COSMAC_ADMIN_TOKEN", "").strip()
    if len(secret) < 32:
        raise NodeSettingsError("节点设置主密钥未配置或长度不足")
    derived = hashlib.sha256(("cosmac-node-settings:v1:" + secret).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def _merge_public(raw: Any) -> Dict[str, Any]:
    """把数据库旧值合入默认结构，避免新增字段后旧节点读取时报错。"""
    out = json.loads(json.dumps(DEFAULT_PUBLIC, ensure_ascii=False))
    if not isinstance(raw, dict):
        return out
    for section in out:
        value = raw.get(section)
        if isinstance(value, dict):
            out[section].update(value)
    return out


def _decrypt(blob: bytes) -> Dict[str, Any]:
    if not blob:
        return {}
    try:
        value = json.loads(_fernet().decrypt(bytes(blob)).decode("utf-8"))
        return value if isinstance(value, dict) else {}
    except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NodeSettingsError("节点设置无法解密，请检查主密钥") from exc


def _encrypt(value: Dict[str, Any]) -> bytes:
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return _fernet().encrypt(raw)


def public_config() -> Dict[str, Any]:
    """返回登录前可读取的品牌配置与向导完成状态，不触碰密钥。"""
    with session_scope() as session:
        row = session.get(NodeSetting, 1)
        public = _merge_public(row.public_config if row else {})
        return {
            "setup_completed": bool(row and row.setup_completed),
            "brand": public["brand"],
        }


def admin_config() -> Dict[str, Any]:
    """返回管理员编辑所需字段；敏感值仅以是否已配置表示。"""
    with session_scope() as session:
        row = session.get(NodeSetting, 1)
        public = _merge_public(row.public_config if row else {})
        if row is None:
            # 存量节点升级后首次打开向导时回显既有非敏感 env，避免保存默认 Echo 后
            # 意外覆盖正在使用的模型/SMTP。密钥仍只显示“已配置”，绝不回填原文。
            try:
                legacy_port = int(os.environ.get("COSMAC_SMTP_PORT", "465") or 465)
            except ValueError:
                legacy_port = 465
            public["email"].update({
                "host": os.environ.get("COSMAC_SMTP_HOST", ""),
                "port": legacy_port,
                "user": os.environ.get("COSMAC_SMTP_USER", ""),
                "from_address": os.environ.get("COSMAC_SMTP_FROM", ""),
                "from_name": os.environ.get("COSMAC_SMTP_FROM_NAME", "GuDuu OS"),
                "security": "starttls" if os.environ.get("COSMAC_SMTP_PORT") == "587" else "ssl",
            })
            provider = os.environ.get("COSMAC_LLM_PROVIDER", "echo") or "echo"
            base_var = {
                "claude": "ANTHROPIC_BASE_URL", "openai": "OPENAI_BASE_URL",
                "deepseek": "ARK_BASE_URL", "ark": "ARK_BASE_URL",
            }.get(provider, "")
            public["ai"].update({
                "provider": provider,
                "model": os.environ.get("COSMAC_LLM_MODEL", ""),
                "base_url": os.environ.get(base_var, "") if base_var else "",
            })
        secrets = _decrypt(row.encrypted_secrets) if row else {}
        public["setup_completed"] = bool(row and row.setup_completed)
        public["email"]["password_configured"] = bool(
            secrets.get("smtp_password") or os.environ.get("COSMAC_SMTP_PASSWORD")
        )
        provider_key = {
            "claude": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY",
            "deepseek": "ARK_API_KEY", "ark": "ARK_API_KEY", "gemini": "GEMINI_API_KEY",
        }.get(str(public["ai"].get("provider") or ""), "")
        public["ai"]["api_key_configured"] = bool(
            secrets.get("ai_api_key") or (provider_key and os.environ.get(provider_key))
        )
        public["payment"]["secret_configured"] = bool(secrets.get("payment_secret"))
        public["payment"]["webhook_configured"] = bool(secrets.get("payment_webhook"))
        # 节点支付真实适配器尚未联调完成，必须如实告知前端，禁止保存凭据后伪装上线。
        public["payment"]["adapter_ready"] = False
        return public


def save_admin_config(body: Dict[str, Any]) -> Dict[str, Any]:
    """校验并保存向导内容；空白密钥保留旧值，显式 ``clear_*`` 才清除。"""
    brand = body.get("brand") if isinstance(body.get("brand"), dict) else {}
    email = body.get("email") if isinstance(body.get("email"), dict) else {}
    ai = body.get("ai") if isinstance(body.get("ai"), dict) else {}
    payment = body.get("payment") if isinstance(body.get("payment"), dict) else {}

    product_name = str(brand.get("product_name") or "").strip()
    if not product_name or len(product_name) > 80:
        raise NodeSettingsError("产品名称必填，且不能超过 80 个字符")
    logo = str(brand.get("logo_data_url") or "").strip()
    if logo and (not logo.startswith("data:image/") or len(logo) > 700_000):
        raise NodeSettingsError("Logo 必须是 512KB 以内的图片")
    provider = str(ai.get("provider") or "echo").strip().lower()
    if provider not in {"echo", "claude", "openai", "deepseek", "ark", "gemini"}:
        raise NodeSettingsError("不支持的主 AI 提供方")
    try:
        smtp_port = int(email.get("port") or 465)
    except (TypeError, ValueError) as exc:
        raise NodeSettingsError("SMTP 端口必须是数字") from exc
    if smtp_port < 1 or smtp_port > 65535:
        raise NodeSettingsError("SMTP 端口超出有效范围")

    with session_scope() as session:
        row = session.get(NodeSetting, 1)
        if row is None:
            row = NodeSetting(id=1)
            session.add(row)
        old_secrets = _decrypt(row.encrypted_secrets)
        public = {
            "brand": {
                "product_name": product_name,
                "company_name": str(brand.get("company_name") or "").strip()[:120],
                "logo_data_url": logo,
            },
            "email": {
                "host": str(email.get("host") or "").strip()[:255],
                "port": smtp_port,
                "user": str(email.get("user") or "").strip()[:320],
                "from_address": str(email.get("from_address") or "").strip()[:320],
                "from_name": str(email.get("from_name") or product_name).strip()[:120],
                "security": "starttls" if email.get("security") == "starttls" else "ssl",
            },
            "ai": {
                "provider": provider,
                "model": str(ai.get("model") or "").strip()[:160],
                "base_url": str(ai.get("base_url") or "").strip()[:500],
            },
            "payment": {
                "provider": str(payment.get("provider") or "none").strip()[:40],
                "mode": "live" if payment.get("mode") == "live" else "sandbox",
                "merchant_id": str(payment.get("merchant_id") or "").strip()[:255],
            },
        }
        for target, source, clear_name in (
            ("smtp_password", email.get("password"), "clear_password"),
            ("ai_api_key", ai.get("api_key"), "clear_api_key"),
            ("payment_secret", payment.get("secret_key"), "clear_secret"),
            ("payment_webhook", payment.get("webhook_secret"), "clear_webhook"),
        ):
            if bool((email if target == "smtp_password" else ai if target == "ai_api_key" else payment).get(clear_name)):
                old_secrets.pop(target, None)
            elif str(source or "").strip():
                old_secrets[target] = str(source).strip()
        row.public_config = public
        row.encrypted_secrets = _encrypt(old_secrets)
        row.setup_completed = bool(body.get("setup_completed", True))
    return admin_config()


def runtime_email() -> Dict[str, Any]:
    """供注册发信路径热读取 SMTP；数据库未配置时返回空字典让调用方回退 env。"""
    with session_scope() as session:
        row = session.get(NodeSetting, 1)
        if not row:
            return {}
        public = _merge_public(row.public_config)["email"]
        public["password"] = _decrypt(row.encrypted_secrets).get("smtp_password", "")
        return public


def runtime_ai() -> Dict[str, Any]:
    """供主 AI 每轮热读取 provider/model/base_url/API key。"""
    with session_scope() as session:
        row = session.get(NodeSetting, 1)
        if not row:
            return {}
        public = _merge_public(row.public_config)["ai"]
        public["api_key"] = _decrypt(row.encrypted_secrets).get("ai_api_key", "")
        return public
