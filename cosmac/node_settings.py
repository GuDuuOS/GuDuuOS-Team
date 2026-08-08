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
import re
import unicodedata
from typing import Any, Dict
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken

from cosmac.db import session_scope
from cosmac.db.models import NodeSetting
from cosmac.node_activation import instance_id as activated_instance_id


OFFICIAL_BRAND_INSTANCE_IDS = frozenset({3})

DEFAULT_PUBLIC: Dict[str, Any] = {
    "brand": {"product_name": "GuDuu OS", "company_name": "", "logo_data_url": ""},
    "website": {
        "headline": "让沟通、协作与智能助手在一个地方完成",
        "description": "面向团队的一体化沟通与智能协作平台。",
        "contact_email": "", "contact_phone": "", "contact_address": "",
        "support_url": "", "privacy_url": "", "footer_text": "",
    },
    "email": {
        "host": "", "port": 465, "user": "", "from_address": "",
        "from_name": "GuDuu OS", "security": "ssl",
    },
    "ai": {
        "connection_mode": "direct", "provider": "echo", "model": "",
        "base_url": "",
    },
    "payment": {
        "alipay": {
            "enabled": False, "mode": "sandbox", "app_id": "",
            "notify_url": "", "sign_type": "RSA2",
        },
        "wechat": {
            "enabled": False, "mode": "sandbox", "mch_id": "", "app_id": "",
            "merchant_serial_no": "", "platform_public_key_id": "",
            "notify_url": "",
        },
    },
}


def _is_oem_node() -> bool:
    """官方 OEM 发行版只把授权/基础设施信息放在环境变量。"""
    return bool(os.environ.get("COSMAC_OEM_KEY", "").strip())


def _contains_protected_brand(value: Any) -> bool:
    """识别 GuDuu OS 变体与中富通官方标识。"""
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    compact = re.sub(r"[^a-z0-9]+", "", normalized)
    return "guduuos" in compact or "中富通" in normalized


def _brand_policy() -> Dict[str, Any]:
    """只有官网正式节点 #3 可把 GuDuu OS 作为客户产品品牌。"""
    node_id = activated_instance_id() if _is_oem_node() else None
    allowed = not _is_oem_node() or node_id in OFFICIAL_BRAND_INSTANCE_IDS
    return {
        "instance_id": node_id,
        "reserved_brand_allowed": allowed,
        "reserved_brand": "GuDuu OS",
        "requires_custom_brand": not allowed,
    }


def _validate_customer_brand(value: Any, label: str) -> None:
    policy = _brand_policy()
    if not policy["reserved_brand_allowed"] and _contains_protected_brand(value):
        raise NodeSettingsError(
            f"{label}不得使用 GuDuu OS 保留品牌或中富通官方标识；"
            "仅官网正式节点 #3 可使用"
        )


def _nexus_ai_base_url(provider: str) -> str:
    """由唯一的 Nexus 地址推导网关地址，避免在 .env 再维护三套业务配置。"""
    root = os.environ.get("COSMAC_NEXUS_URL", "").strip().rstrip("/")
    path = {
        "claude": "/gw/anthropic",
        "openai": "/gw/openai",
        "deepseek": "/gw/ark",
        "ark": "/gw/ark",
    }.get(provider, "")
    return root + path if root and path else ""


class NodeSettingsError(ValueError):
    """节点设置缺失、格式不合法或主密钥错误。"""


def _bounded(value: Any, limit: int, label: str) -> str:
    """清理普通配置文本并拒绝静默截断关键支付标识。"""
    clean = str(value or "").strip()
    if len(clean) > limit:
        raise NodeSettingsError(f"{label}不能超过 {limit} 个字符")
    return clean


def _notify_url(value: Any, label: str) -> str:
    """支付平台回调只能使用公开 HTTPS 地址，禁止凭据混入 URL。"""
    clean = _bounded(value, 500, label)
    if not clean:
        return ""
    parsed = urlparse(clean)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise NodeSettingsError(f"{label}必须是无账号密码的 HTTPS 地址")
    return clean


def _public_url(value: Any, label: str) -> str:
    """官网链接仅允许站内绝对路径或无凭据 HTTPS URL。"""
    clean = _bounded(value, 500, label)
    if not clean:
        return ""
    if clean.startswith("/") and not clean.startswith("//"):
        return clean
    parsed = urlparse(clean)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise NodeSettingsError(f"{label}必须是站内路径或无账号密码的 HTTPS 地址")
    return clean


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
            if section == "payment":
                # 支付配置含支付宝/微信两层结构；逐渠道合并，避免旧记录或
                # 增量字段把同渠道的默认键整体覆盖掉。
                for key, item in value.items():
                    if isinstance(item, dict) and isinstance(out[section].get(key), dict):
                        out[section][key].update(item)
                    else:
                        out[section][key] = item
            else:
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
        policy = _brand_policy()
        protected = any(_contains_protected_brand(value) for value in (
            public["brand"].get("product_name"),
            public["brand"].get("company_name"),
            *public["website"].values(),
        ))
        if not policy["reserved_brand_allowed"] and protected:
            # 存量外部 OEM 即使数据库里留有旧默认值，也不能再对外
            # 呈现官方品牌；同时重新打开向导要求客户填写自有品牌。
            public["brand"] = {
                "product_name": "OEM 协作平台",
                "company_name": "",
                "logo_data_url": "",
            }
            public["website"] = dict(DEFAULT_PUBLIC["website"])
        return {
            "setup_completed": bool(row and row.setup_completed and not (
                not policy["reserved_brand_allowed"] and protected
            )),
            "brand": public["brand"],
            "website": public["website"],
            "brand_policy": policy,
        }


def admin_config() -> Dict[str, Any]:
    """返回管理员编辑所需字段；敏感值仅以是否已配置表示。"""
    with session_scope() as session:
        row = session.get(NodeSetting, 1)
        public = _merge_public(row.public_config if row else {})
        if row is None and not _is_oem_node():
            # 非 OEM 本地开发继续兼容旧环境变量。官方 OEM 节点以网页数据库为唯一
            # 业务配置源，旧 .env 即使残留也不得回显或继续生效。
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
                "connection_mode": "direct",
                "provider": provider,
                "model": os.environ.get("COSMAC_LLM_MODEL", ""),
                "base_url": os.environ.get(base_var, "") if base_var else "",
            })
        elif row is None:
            public["ai"].update({
                "connection_mode": "nexus",
                "provider": "deepseek",
                "model": "",
                "base_url": "",
            })
        policy = _brand_policy()
        if not policy["reserved_brand_allowed"]:
            for section, field in (
                ("brand", "product_name"),
                ("brand", "company_name"),
                ("email", "from_name"),
                ("website", "headline"),
                ("website", "description"),
                ("website", "contact_email"),
                ("website", "contact_address"),
                ("website", "support_url"),
                ("website", "privacy_url"),
                ("website", "footer_text"),
            ):
                if _contains_protected_brand(public[section].get(field)):
                    public[section][field] = ""
        secrets = _decrypt(row.encrypted_secrets) if row else {}
        public["setup_completed"] = bool(
            row and row.setup_completed and public["brand"].get("product_name")
        )
        public["brand_policy"] = policy
        allow_env = not _is_oem_node()
        public["email"]["password_configured"] = bool(
            secrets.get("smtp_password")
            or (allow_env and os.environ.get("COSMAC_SMTP_PASSWORD"))
        )
        provider_key = {
            "claude": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY",
            "deepseek": "ARK_API_KEY", "ark": "ARK_API_KEY", "gemini": "GEMINI_API_KEY",
        }.get(str(public["ai"].get("provider") or ""), "")
        public["ai"]["api_key_configured"] = bool(
            secrets.get("ai_api_key")
            or (allow_env and provider_key and os.environ.get(provider_key))
        )
        alipay = public["payment"]["alipay"]
        alipay["private_key_configured"] = bool(secrets.get("alipay_private_key"))
        alipay["alipay_public_key_configured"] = bool(
            secrets.get("alipay_public_key")
        )
        wechat = public["payment"]["wechat"]
        wechat["api_v3_key_configured"] = bool(secrets.get("wechat_api_v3_key"))
        wechat["merchant_private_key_configured"] = bool(
            secrets.get("wechat_merchant_private_key")
        )
        wechat["platform_public_key_configured"] = bool(
            secrets.get("wechat_platform_public_key")
        )
        # 节点支付真实适配器尚未联调完成，必须逐渠道如实告知前端，禁止保存凭据后伪装上线。
        alipay["adapter_ready"] = False
        wechat["adapter_ready"] = False
        public["payment"]["adapter_ready"] = False
        return public


def save_admin_config(body: Dict[str, Any]) -> Dict[str, Any]:
    """校验并保存向导内容；空白密钥保留旧值，显式 ``clear_*`` 才清除。"""
    brand = body.get("brand") if isinstance(body.get("brand"), dict) else {}
    website = body.get("website") if isinstance(body.get("website"), dict) else None
    email = body.get("email") if isinstance(body.get("email"), dict) else {}
    ai = body.get("ai") if isinstance(body.get("ai"), dict) else {}
    payment = body.get("payment") if isinstance(body.get("payment"), dict) else {}

    product_name = str(brand.get("product_name") or "").strip()
    if not product_name or len(product_name) > 80:
        raise NodeSettingsError("产品名称必填，且不能超过 80 个字符")
    company_name = _bounded(brand.get("company_name"), 120, "企业/组织名称")
    from_name = _bounded(email.get("from_name") or product_name, 120, "发件人名称")
    for value, label in (
        (product_name, "产品名称"),
        (company_name, "企业/组织名称"),
        (from_name, "发件人名称"),
    ):
        _validate_customer_brand(value, label)
    logo = str(brand.get("logo_data_url") or "").strip()
    if logo and (not logo.startswith("data:image/") or len(logo) > 700_000):
        raise NodeSettingsError("Logo 必须是 512KB 以内的图片")
    provider = str(ai.get("provider") or "echo").strip().lower()
    if provider not in {"echo", "claude", "openai", "deepseek", "ark", "gemini"}:
        raise NodeSettingsError("不支持的主 AI 提供方")
    connection_mode = str(ai.get("connection_mode") or "direct").strip().lower()
    if connection_mode not in {"nexus", "direct"}:
        raise NodeSettingsError("主 AI 接入方式不正确")
    if connection_mode == "nexus" and provider not in {
        "claude", "openai", "deepseek", "ark",
    }:
        raise NodeSettingsError("Nexus 网关当前只支持 Claude、OpenAI 和 DeepSeek")
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
        current_public = _merge_public(row.public_config if row else {})
        website_input = website if website is not None else current_public["website"]
        website_public = {
            "headline": _bounded(
                website_input.get("headline"), 120, "官网主标题"
            ) or DEFAULT_PUBLIC["website"]["headline"],
            "description": _bounded(
                website_input.get("description"), 500, "官网介绍"
            ) or DEFAULT_PUBLIC["website"]["description"],
            "contact_email": _bounded(
                website_input.get("contact_email"), 320, "联系邮箱"
            ),
            "contact_phone": _bounded(
                website_input.get("contact_phone"), 80, "联系电话"
            ),
            "contact_address": _bounded(
                website_input.get("contact_address"), 300, "联系地址"
            ),
            "support_url": _public_url(
                website_input.get("support_url"), "帮助中心链接"
            ),
            "privacy_url": _public_url(
                website_input.get("privacy_url"), "隐私政策链接"
            ),
            "footer_text": _bounded(
                website_input.get("footer_text"), 240, "页脚版权文案"
            ),
        }
        if bool(body.get("setup_completed")) and _is_oem_node():
            required_oem_fields = (
                (company_name, "企业/组织名称"),
                (str(website_input.get("description") or "").strip(), "官网介绍"),
                (website_public["contact_email"], "联系邮箱"),
                (website_public["contact_phone"], "联系电话"),
                (website_public["contact_address"], "联系地址"),
            )
            missing = [label for value, label in required_oem_fields if not value]
            if missing:
                raise NodeSettingsError(
                    "OEM 首次部署必须填写：" + "、".join(missing)
                )
        if website_public["contact_email"] and not re.fullmatch(
            r"[^\s@]+@[^\s@]+\.[^\s@]+", website_public["contact_email"]
        ):
            raise NodeSettingsError("联系邮箱格式不正确")
        for field, label in (
            ("headline", "官网主标题"),
            ("description", "官网介绍"),
            ("contact_email", "官网联系邮箱"),
            ("contact_address", "官网联系地址"),
            ("support_url", "帮助中心链接"),
            ("privacy_url", "隐私政策链接"),
            ("footer_text", "页脚版权文案"),
        ):
            value = website_public[field]
            _validate_customer_brand(value, label)
        alipay_input = (
            payment.get("alipay")
            if isinstance(payment.get("alipay"), dict)
            else current_public["payment"]["alipay"]
        )
        wechat_input = (
            payment.get("wechat")
            if isinstance(payment.get("wechat"), dict)
            else current_public["payment"]["wechat"]
        )
        old_secrets = _decrypt(row.encrypted_secrets)
        for target, source, clear in (
            ("alipay_private_key", alipay_input.get("private_key"), alipay_input.get("clear_private_key")),
            ("alipay_public_key", alipay_input.get("alipay_public_key"), alipay_input.get("clear_alipay_public_key")),
            ("wechat_api_v3_key", wechat_input.get("api_v3_key"), wechat_input.get("clear_api_v3_key")),
            ("wechat_merchant_private_key", wechat_input.get("merchant_private_key"), wechat_input.get("clear_merchant_private_key")),
            ("wechat_platform_public_key", wechat_input.get("platform_public_key"), wechat_input.get("clear_platform_public_key")),
        ):
            if bool(clear):
                old_secrets.pop(target, None)
            elif str(source or "").strip():
                clean_secret = str(source).strip()
                if len(clean_secret) > 20_000:
                    raise NodeSettingsError("支付密钥或证书内容过长")
                old_secrets[target] = clean_secret

        alipay_enabled = bool(alipay_input.get("enabled"))
        wechat_enabled = bool(wechat_input.get("enabled"))
        alipay_public = {
            "enabled": alipay_enabled,
            "mode": "live" if alipay_input.get("mode") == "live" else "sandbox",
            "app_id": _bounded(alipay_input.get("app_id"), 64, "支付宝 APPID"),
            "notify_url": _notify_url(alipay_input.get("notify_url"), "支付宝通知地址"),
            "sign_type": "RSA2",
        }
        wechat_public = {
            "enabled": wechat_enabled,
            "mode": "live" if wechat_input.get("mode") == "live" else "sandbox",
            "mch_id": _bounded(wechat_input.get("mch_id"), 64, "微信支付商户号"),
            "app_id": _bounded(wechat_input.get("app_id"), 64, "微信支付 AppID"),
            "merchant_serial_no": _bounded(
                wechat_input.get("merchant_serial_no"), 128, "商户证书序列号"
            ),
            "platform_public_key_id": _bounded(
                wechat_input.get("platform_public_key_id"), 128, "微信支付公钥 ID"
            ),
            "notify_url": _notify_url(wechat_input.get("notify_url"), "微信支付通知地址"),
        }
        if alipay_enabled:
            if not alipay_public["app_id"] or not alipay_public["notify_url"]:
                raise NodeSettingsError("启用支付宝前必须填写 APPID 和通知地址")
            if not old_secrets.get("alipay_private_key") or not old_secrets.get(
                "alipay_public_key"
            ):
                raise NodeSettingsError("启用支付宝前必须填写应用私钥和支付宝公钥")
        if wechat_enabled:
            required = (
                wechat_public["mch_id"], wechat_public["app_id"],
                wechat_public["merchant_serial_no"],
                wechat_public["platform_public_key_id"], wechat_public["notify_url"],
            )
            if not all(required):
                raise NodeSettingsError(
                    "启用微信支付前必须填写商户号、AppID、证书序列号、公钥 ID 和通知地址"
                )
            api_v3_key = str(old_secrets.get("wechat_api_v3_key") or "")
            if len(api_v3_key.encode("utf-8")) != 32:
                raise NodeSettingsError("微信支付 APIv3 密钥必须正好是 32 字节")
            if not old_secrets.get("wechat_merchant_private_key") or not old_secrets.get(
                "wechat_platform_public_key"
            ):
                raise NodeSettingsError("启用微信支付前必须填写商户私钥和微信支付平台公钥")
        public = {
            "brand": {
                "product_name": product_name,
                "company_name": company_name,
                "logo_data_url": logo,
            },
            "website": website_public,
            "email": {
                "host": str(email.get("host") or "").strip()[:255],
                "port": smtp_port,
                "user": str(email.get("user") or "").strip()[:320],
                "from_address": str(email.get("from_address") or "").strip()[:320],
                "from_name": from_name,
                "security": "starttls" if email.get("security") == "starttls" else "ssl",
            },
            "ai": {
                "connection_mode": connection_mode,
                "provider": provider,
                "model": str(ai.get("model") or "").strip()[:160],
                "base_url": str(ai.get("base_url") or "").strip()[:500],
            },
            "payment": {"alipay": alipay_public, "wechat": wechat_public},
        }
        for target, source, clear_name in (
            ("smtp_password", email.get("password"), "clear_password"),
            ("ai_api_key", ai.get("api_key"), "clear_api_key"),
        ):
            if bool((email if target == "smtp_password" else ai).get(clear_name)):
                old_secrets.pop(target, None)
            elif str(source or "").strip():
                old_secrets[target] = str(source).strip()
        if connection_mode == "direct" and provider != "echo" and not old_secrets.get(
            "ai_api_key"
        ):
            raise NodeSettingsError("使用自有 AI API 时必须填写 API Key")
        if connection_mode == "nexus" and not os.environ.get(
            "COSMAC_OEM_KEY", ""
        ).strip():
            raise NodeSettingsError("Nexus AI 网关需要节点先完成 OEM 授权")
        row.public_config = public
        row.encrypted_secrets = _encrypt(old_secrets)
        row.setup_completed = bool(body.get("setup_completed", True))
    return admin_config()


def runtime_email() -> Dict[str, Any]:
    """供注册发信路径热读取 SMTP；OEM 节点绝不回退旧 .env。"""
    with session_scope() as session:
        row = session.get(NodeSetting, 1)
        if not row:
            return {"_source": "node_settings"} if _is_oem_node() else {}
        public = _merge_public(row.public_config)["email"]
        public["password"] = _decrypt(row.encrypted_secrets).get("smtp_password", "")
        # 设置行存在后，网页就是唯一真值源。即使管理员留空，
        # 也表示明确停用，调用方不得再按字段回退到旧 .env。
        public["_source"] = "node_settings"
        return public


def runtime_ai() -> Dict[str, Any]:
    """供主 AI 每轮热读取 provider/model/base_url/API key。"""
    with session_scope() as session:
        row = session.get(NodeSetting, 1)
        if not row:
            # OEM 授权已存在但向导未保存时保持 Echo，不能让遗留 .env 绕过网页配置。
            return (
                {
                    "connection_mode": "nexus", "provider": "echo", "model": "",
                    "base_url": "", "api_key": "", "_source": "node_settings",
                }
                if _is_oem_node() else {}
            )
        public = _merge_public(row.public_config)["ai"]
        mode = str(public.get("connection_mode") or "direct")
        provider = str(public.get("provider") or "echo")
        if mode == "nexus":
            public["base_url"] = _nexus_ai_base_url(provider)
            public["api_key"] = os.environ.get("COSMAC_OEM_KEY", "")
        else:
            public["api_key"] = _decrypt(row.encrypted_secrets).get("ai_api_key", "")
        public["_source"] = "node_settings"
        return public


def runtime_payments() -> Dict[str, Any]:
    """供节点支付 adapter 读取支付宝/微信配置；只允许服务端调用。"""
    with session_scope() as session:
        row = session.get(NodeSetting, 1)
        if not row:
            return {}
        payment = _merge_public(row.public_config)["payment"]
        secrets = _decrypt(row.encrypted_secrets)
        alipay = dict(payment["alipay"])
        alipay.update({
            "private_key": secrets.get("alipay_private_key", ""),
            "alipay_public_key": secrets.get("alipay_public_key", ""),
        })
        wechat = dict(payment["wechat"])
        wechat.update({
            "api_v3_key": secrets.get("wechat_api_v3_key", ""),
            "merchant_private_key": secrets.get("wechat_merchant_private_key", ""),
            "platform_public_key": secrets.get("wechat_platform_public_key", ""),
        })
        return {"alipay": alipay, "wechat": wechat, "_source": "node_settings"}
