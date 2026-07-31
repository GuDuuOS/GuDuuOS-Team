"""Nexus 支付渠道配置中心：字段定义、加密存储与安全验证。

本模块只负责“凭据是否完整、能否通过官方认证检查”，不负责创建订单或处理回调。
这层分离非常重要：凭据验证成功并不等于真实收款链路已经完成沙箱验收。控制台会把
两种状态分开显示，避免管理员误开尚未实现验签/幂等履约的渠道。

安全约定：
    - 配置用 ``NEXUS_SECRET_KEY`` 派生 Fernet 密钥后加密入库；
    - 公共返回只包含字段是否已配置，不包含原文或可逆掩码；
    - 远程检查只访问代码内固定的官方 HTTPS 域名，管理员不能填写 API Base；
    - 上游响应只转成固定中文摘要，不把响应体写库或回传，防止意外泄露账号信息。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import requests
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import serialization

from nexus.db import NexusPaymentConfig
from nexus.fleet import FleetError


_HTTP_TIMEOUT_SECONDS = 12
_USER_AGENT = "GuDuu-Nexus-Payment-Config/1.0"

# 字段定义是服务端白名单，也是前端动态表单的数据源。secret=True 的字段无论是否
# “看起来公开”（如 client id）都不回传原值，统一降低配置接口未来扩权时的泄露面。
_PROVIDERS: Dict[str, Dict[str, Any]] = {
    "alipay": {
        "label": "支付宝",
        "summary": "电脑网站支付 · 人民币",
        "docs_url": "https://opendocs.alipay.com/open/270/105898",
        "verification_note": "本地验证 RSA2 密钥格式；真实收款前还需沙箱下单与回调验签。",
        "fields": [
            {"name": "mode", "label": "环境", "type": "select", "secret": False,
             "options": [{"value": "sandbox", "label": "沙箱"}, {"value": "live", "label": "正式"}],
             "default": "sandbox", "help": "建议先使用沙箱应用完成全链路验收。"},
            {"name": "app_id", "label": "应用 AppID", "type": "text", "secret": True,
             "help": "支付宝开放平台应用详情中的 AppID。"},
            {"name": "private_key", "label": "应用私钥（RSA2）", "type": "textarea", "secret": True,
             "help": "应用私钥，不是应用公钥；支持 PKCS#1/PKCS#8 PEM。"},
            {"name": "alipay_public_key", "label": "支付宝公钥", "type": "textarea", "secret": True,
             "help": "用于验证支付宝异步通知，不能填写应用公钥。"},
        ],
    },
    "wechat": {
        "label": "微信支付",
        "summary": "APIv3 Native 扫码 · 人民币",
        "docs_url": "https://github.com/wechatpay-apiv3/wechatpay-java",
        "verification_note": "本地验证商户私钥与 APIv3 字段；真实收款前还需 Native 下单和通知解密验收。",
        "fields": [
            {"name": "merchant_id", "label": "商户号（mchid）", "type": "text", "secret": True,
             "help": "微信支付商户平台中的商户号。"},
            {"name": "app_id", "label": "关联 AppID", "type": "text", "secret": True,
             "help": "已与该商户号绑定的公众号、小程序或开放平台 AppID。"},
            {"name": "merchant_serial", "label": "商户 API 证书序列号", "type": "text", "secret": True,
             "help": "不是平台证书序列号；通常为十六进制字符串。"},
            {"name": "private_key", "label": "商户 API 私钥", "type": "textarea", "secret": True,
             "help": "与商户 API 证书配套的 RSA 私钥 PEM。"},
            {"name": "api_v3_key", "label": "APIv3 密钥", "type": "password", "secret": True,
             "help": "商户平台设置的 32 字节 APIv3 密钥，用于解密回调。"},
        ],
    },
    "stripe": {
        "label": "Stripe",
        "summary": "银行卡 · 多币种",
        "docs_url": "https://docs.stripe.com/keys",
        "verification_note": "保存时向 Stripe /v1/account 发起只读认证，不创建客户或扣款。",
        "fields": [
            {"name": "mode", "label": "环境", "type": "select", "secret": False,
             "options": [{"value": "sandbox", "label": "测试"}, {"value": "live", "label": "正式"}],
             "default": "sandbox", "help": "测试 Key 与正式 Key 必须和环境一致。"},
            {"name": "secret_key", "label": "Secret / Restricted key", "type": "password", "secret": True,
             "help": "服务端密钥（sk_ 或 rk_），优先使用按最小权限创建的 Restricted key。"},
            {"name": "webhook_secret", "label": "Webhook signing secret", "type": "password", "secret": True,
             "help": "对应当前回调端点的 whsec_ 密钥，它与 API key 是两个不同的值。"},
        ],
    },
    "paypal": {
        "label": "PayPal",
        "summary": "PayPal Checkout · 多币种",
        "docs_url": "https://developer.paypal.com/api/rest/authentication",
        "verification_note": "保存时用 Client Credentials 获取短期 access token，不创建订单或扣款。",
        "fields": [
            {"name": "mode", "label": "环境", "type": "select", "secret": False,
             "options": [{"value": "sandbox", "label": "Sandbox"}, {"value": "live", "label": "Live"}],
             "default": "sandbox", "help": "正式环境需要 PayPal Business 账号与 Live 应用。"},
            {"name": "client_id", "label": "Client ID", "type": "password", "secret": True,
             "help": "PayPal Developer Dashboard 中 REST API 应用的 Client ID。"},
            {"name": "client_secret", "label": "Client Secret", "type": "password", "secret": True,
             "help": "与 Client ID 同一应用、同一环境的 Client Secret。"},
            {"name": "webhook_id", "label": "Webhook ID", "type": "password", "secret": True,
             "help": "在该 REST 应用中为 Nexus 回调地址创建 Webhook 后取得。"},
        ],
    },
    "usdt": {
        "label": "USDT（NOWPayments）",
        "summary": "稳定币 · 自动对账",
        "docs_url": "https://documenter.getpostman.com/view/7907941/2s93JusNJt",
        "verification_note": "保存时读取商户可用币种列表；IPN secret 仅做本地完整性检查。",
        "fields": [
            {"name": "api_key", "label": "NOWPayments API Key", "type": "password", "secret": True,
             "help": "NOWPayments 商户后台生成的 API key。"},
            {"name": "ipn_secret", "label": "IPN Secret", "type": "password", "secret": True,
             "help": "用于校验 x-nowpayments-sig 回调签名；不是钱包私钥或助记词。"},
        ],
    },
}


def _now_ms() -> int:
    """返回统一的毫秒时间戳，和 Nexus 其余表保持一致。"""
    return int(time.time() * 1000)


def _fernet() -> Fernet:
    """从环境主密钥派生 Fernet 实例；缺失时宁可拒绝保存也不明文降级。"""
    raw = os.environ.get("NEXUS_SECRET_KEY", "").strip()
    if len(raw) < 32:
        raise FleetError(
            "NEXUS_SECRET_KEY_MISSING",
            "支付配置加密主密钥未配置，请先设置 NEXUS_SECRET_KEY",
            503,
        )
    derived = base64.urlsafe_b64encode(hashlib.sha256(raw.encode("utf-8")).digest())
    return Fernet(derived)


def _encrypt(config: Dict[str, str]) -> bytes:
    """把渠道配置序列化并加密，返回可直接写入 LargeBinary 的字节串。"""
    plain = json.dumps(config, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return _fernet().encrypt(plain)


def _decrypt(row: NexusPaymentConfig) -> Dict[str, str]:
    """解密一行配置；主密钥不匹配时返回可操作错误，不泄露密文细节。"""
    try:
        raw = _fernet().decrypt(bytes(row.encrypted_config))
        data = json.loads(raw.decode("utf-8"))
    except (InvalidToken, ValueError, TypeError, json.JSONDecodeError):
        raise FleetError(
            "NEXUS_SECRET_KEY_INVALID",
            "支付配置无法解密，请核对 NEXUS_SECRET_KEY 是否与保存时一致",
            503,
        )
    if not isinstance(data, dict):
        raise FleetError("NEXUS_PAY_CONFIG_INVALID", "支付配置内容损坏", 500)
    return {str(k): str(v) for k, v in data.items()}


def _definition(provider: str) -> Dict[str, Any]:
    """按白名单取渠道定义，未知渠道统一报业务错误。"""
    definition = _PROVIDERS.get(provider)
    if definition is None:
        raise FleetError("NEXUS_BAD_CHANNEL", "不支持的支付渠道")
    return definition


def _field_names(definition: Dict[str, Any]) -> List[str]:
    """返回渠道允许提交的字段名，拒绝把未知数据顺手塞进密文。"""
    return [str(item["name"]) for item in definition["fields"]]


def _merge_config(
    definition: Dict[str, Any], old: Dict[str, str], submitted: Dict[str, Any]
) -> Dict[str, str]:
    """合并管理员提交；空值保留旧密钥，首次配置缺字段时拒绝保存。"""
    out = dict(old)
    allowed = set(_field_names(definition))
    for name in allowed:
        value = submitted.get(name)
        if value is None or str(value).strip() == "":
            continue
        clean = str(value).strip()
        # PEM/证书体允许较长，其余字段限制 2048；整体请求在 HTTP 层还有 64KB 上限。
        limit = 20_000 if "key" in name else 2_048
        if len(clean) > limit:
            raise FleetError("NEXUS_PAY_CONFIG_TOO_LONG", "支付配置字段过长")
        out[name] = clean

    for field in definition["fields"]:
        name = str(field["name"])
        if name not in out and field.get("default") is not None:
            out[name] = str(field["default"])
        if not out.get(name, "").strip():
            raise FleetError("NEXUS_PAY_CONFIG_INCOMPLETE", f"请填写{field['label']}")
        if field.get("type") == "select":
            choices = {str(option["value"]) for option in field.get("options", [])}
            if out[name] not in choices:
                raise FleetError("NEXUS_PAY_CONFIG_INVALID", f"{field['label']}选项不合法")
    return out


def _pem(value: str, kind: str) -> bytes:
    """兼容平台只给 Base64 主体的情况，把密钥归一成标准 PEM 再交给解析器。"""
    clean = value.strip().replace("\\n", "\n")
    if "-----BEGIN" in clean:
        return clean.encode("utf-8")
    compact = "".join(clean.split())
    if not compact:
        raise ValueError("empty key")
    lines = "\n".join(compact[i:i + 64] for i in range(0, len(compact), 64))
    return f"-----BEGIN {kind}-----\n{lines}\n-----END {kind}-----\n".encode("ascii")


def _load_private(value: str) -> None:
    """解析私钥并兼容支付宝工具常见的无 PEM 头 PKCS#1/PKCS#8 两种导出。"""
    last_error: Optional[Exception] = None
    for kind in ("PRIVATE KEY", "RSA PRIVATE KEY"):
        try:
            serialization.load_pem_private_key(_pem(value, kind), None)
            return
        except (ValueError, TypeError) as error:
            last_error = error
    raise ValueError("bad private key") from last_error


def _load_public(value: str) -> None:
    """解析平台公钥并兼容 SubjectPublicKeyInfo 与 PKCS#1 两种 PEM 包装。"""
    last_error: Optional[Exception] = None
    for kind in ("PUBLIC KEY", "RSA PUBLIC KEY"):
        try:
            serialization.load_pem_public_key(_pem(value, kind))
            return
        except (ValueError, TypeError) as error:
            last_error = error
    raise ValueError("bad public key") from last_error


def _verify_alipay(config: Dict[str, str]) -> Tuple[str, str]:
    """验证支付宝 AppID 与 RSA2 密钥能被解析；不发起可能产生业务数据的请求。"""
    if not re.fullmatch(r"\d{12,24}", config["app_id"]):
        raise ValueError("bad app id")
    _load_private(config["private_key"])
    _load_public(config["alipay_public_key"])
    return "local_valid", "RSA2 密钥格式已验证；待沙箱下单与异步通知验签"


def _verify_wechat(config: Dict[str, str]) -> Tuple[str, str]:
    """验证微信商户标识、APIv3 密钥长度和商户 RSA 私钥格式。"""
    if not re.fullmatch(r"\d{8,15}", config["merchant_id"]):
        raise ValueError("bad merchant id")
    if not re.fullmatch(r"wx[0-9A-Za-z]{8,32}", config["app_id"]):
        raise ValueError("bad app id")
    if not re.fullmatch(r"[0-9A-Fa-f]{16,128}", config["merchant_serial"]):
        raise ValueError("bad certificate serial")
    if len(config["api_v3_key"].encode("utf-8")) != 32:
        raise ValueError("bad api v3 key")
    _load_private(config["private_key"])
    return "local_valid", "APIv3 字段与商户私钥格式已验证；待沙箱交易和通知解密"


def _verify_stripe(config: Dict[str, str]) -> Tuple[str, str]:
    """调用 Stripe 只读账户接口验证服务端 Key 与所选环境。"""
    key = config["secret_key"]
    mode = config["mode"]
    expected = ("sk_test_", "rk_test_") if mode == "sandbox" else ("sk_live_", "rk_live_")
    if not key.startswith(expected):
        raise ValueError("key mode mismatch")
    if not config["webhook_secret"].startswith("whsec_"):
        raise ValueError("bad webhook secret")
    response = requests.get(
        "https://api.stripe.com/v1/account",
        auth=(key, ""),
        headers={"User-Agent": _USER_AGENT},
        timeout=_HTTP_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        raise PermissionError("stripe rejected credentials")
    return "remote_verified", "Stripe 官方认证通过；未创建客户、订单或扣款"


def _verify_paypal(config: Dict[str, str]) -> Tuple[str, str]:
    """用 PayPal Client Credentials 换取短期 token，以验证同环境应用凭据。"""
    host = "api-m.sandbox.paypal.com" if config["mode"] == "sandbox" else "api-m.paypal.com"
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,200}", config["webhook_id"]):
        raise ValueError("bad webhook id")
    response = requests.post(
        f"https://{host}/v1/oauth2/token",
        auth=(config["client_id"], config["client_secret"]),
        data={"grant_type": "client_credentials"},
        headers={"Accept": "application/json", "User-Agent": _USER_AGENT},
        timeout=_HTTP_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        raise PermissionError("paypal rejected credentials")
    try:
        token = response.json().get("access_token", "")
    except ValueError:
        token = ""
    if not token:
        raise PermissionError("paypal returned no token")
    return "remote_verified", "PayPal OAuth 认证通过；未创建订单或扣款"


def _verify_usdt(config: Dict[str, str]) -> Tuple[str, str]:
    """查询 NOWPayments 商户币种列表，验证 API key；不接触钱包私钥。"""
    if len(config["ipn_secret"]) < 8:
        raise ValueError("bad ipn secret")
    response = requests.get(
        "https://api.nowpayments.io/v1/merchant/coins",
        headers={"x-api-key": config["api_key"], "User-Agent": _USER_AGENT},
        timeout=_HTTP_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        raise PermissionError("nowpayments rejected credentials")
    try:
        selected = response.json().get("selectedCurrencies", [])
    except ValueError:
        selected = []
    if not isinstance(selected, list):
        raise PermissionError("nowpayments returned unexpected data")
    return "remote_verified", "NOWPayments 官方认证通过；IPN 回调仍待沙箱联调"


_VERIFIERS = {
    "alipay": _verify_alipay,
    "wechat": _verify_wechat,
    "stripe": _verify_stripe,
    "paypal": _verify_paypal,
    "usdt": _verify_usdt,
}


def _verify(provider: str, config: Dict[str, str]) -> Tuple[str, str]:
    """运行渠道验证并把异常归一成不泄露上游响应的安全状态。"""
    try:
        return _VERIFIERS[provider](config)
    except requests.RequestException:
        return "verification_failed", "暂时无法连接支付平台，请检查网络后重试"
    except PermissionError:
        return "verification_failed", "支付平台拒绝凭据，请核对环境、权限与 Key"
    except (ValueError, TypeError):
        return "verification_failed", "凭据格式不正确，请按字段说明重新填写"


def save_and_verify(s, provider: str, submitted: Dict[str, Any]) -> Dict[str, Any]:
    """保存（加密）并立即验证一个支付渠道，返回不含任何密钥的公开状态。"""
    # 在任何远程认证请求之前确认本机能安全落库；主密钥缺失时不应把管理员刚输入的
    # 凭据发送出去后才失败，更不能退化成明文保存。
    _fernet()
    definition = _definition(provider)
    row = s.get(NexusPaymentConfig, provider)
    old = _decrypt(row) if row is not None else {}
    merged = _merge_config(definition, old, submitted)
    status, message = _verify(provider, merged)
    now = _now_ms()
    if row is None:
        row = NexusPaymentConfig(provider=provider, encrypted_config=b"")
        s.add(row)
    row.encrypted_config = _encrypt(merged)
    row.verify_status = status
    row.verify_message = message
    row.last_checked_ts = now
    row.updated_ts = now
    s.flush()
    return public_config(s, provider)


def verify_existing(s, provider: str) -> Dict[str, Any]:
    """重新验证已保存配置；适合管理员点击“重新检查”，不要求再次输入密钥。"""
    _definition(provider)
    row = s.get(NexusPaymentConfig, provider)
    if row is None:
        raise FleetError("NEXUS_PAY_CONFIG_NOT_FOUND", "该渠道尚未保存配置", 404)
    config = _decrypt(row)
    status, message = _verify(provider, config)
    row.verify_status = status
    row.verify_message = message
    row.last_checked_ts = _now_ms()
    s.flush()
    return public_config(s, provider)


def _public_fields(definition: Dict[str, Any], config: Dict[str, str]) -> List[Dict[str, Any]]:
    """生成前端字段元数据；只返回 configured 布尔值，永不返回密钥或掩码。"""
    fields: List[Dict[str, Any]] = []
    for source in definition["fields"]:
        item = dict(source)
        name = str(item["name"])
        item["configured"] = bool(config.get(name, "").strip())
        # 非敏感 select 可回传当前选项，方便表单保持沙箱/正式选择；其它一律空。
        item["value"] = config.get(name, item.get("default", "")) if item.get("type") == "select" else ""
        fields.append(item)
    return fields


def public_config(s, provider: str, origin: str = "") -> Dict[str, Any]:
    """返回单渠道公开配置状态，供控制台渲染；不包含可逆凭据。"""
    definition = _definition(provider)
    row = s.get(NexusPaymentConfig, provider)
    config = _decrypt(row) if row is not None else {}
    status = str(row.verify_status) if row is not None else "not_configured"
    callback = f"{origin}/nexus/pay/notify/{provider}" if origin else f"/nexus/pay/notify/{provider}"
    return {
        "provider": provider,
        "label": definition["label"],
        "summary": definition["summary"],
        "docs_url": definition["docs_url"],
        "verification_note": definition["verification_note"],
        "configured": row is not None,
        "verify_status": status,
        "verify_message": str(row.verify_message) if row is not None else "尚未填写凭据",
        "last_checked_ts": int(row.last_checked_ts) if row is not None and row.last_checked_ts else None,
        # adapter_ready 在真实下单、回调验签、幂等履约和沙箱验收完成前必须保持 false。
        "adapter_ready": False,
        "callback_url": callback,
        "fields": _public_fields(definition, config),
    }


def list_public(s, origin: str = "") -> List[Dict[str, Any]]:
    """按产品固定顺序返回五个渠道的公开配置状态。"""
    order = ("alipay", "wechat", "stripe", "paypal", "usdt")
    return [public_config(s, provider, origin) for provider in order]


def config_statuses(s) -> Dict[str, str]:
    """返回渠道→验证状态的小字典，供资金总览状态统计复用。"""
    rows = s.query(NexusPaymentConfig).all()
    return {str(row.provider): str(row.verify_status) for row in rows}
