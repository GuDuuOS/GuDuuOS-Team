"""Nexus OEM 邮箱验证、验证码登录与密码找回。

这套身份流程只服务中央 Nexus 的 OEM 企业账号，与各 OEM 节点里的 Matrix 用户注册
完全隔离。验证码使用 Nexus 独立 SMTP 配置发送，数据库只保存 HMAC，不保存验证码原文。

环境变量：
    NEXUS_SMTP_HOST / NEXUS_SMTP_PORT / NEXUS_SMTP_USER / NEXUS_SMTP_PASSWORD
    NEXUS_SMTP_FROM / NEXUS_SMTP_FROM_NAME / NEXUS_SMTP_SECURITY

``NEXUS_SMTP_SECURITY`` 支持 ``ssl``（默认）、``starttls`` 和 ``plain``。生产必须使用
前两种；``plain`` 仅供本机测试邮件服务器。HMAC 使用既有 ``NEXUS_SECRET_KEY``，因此
缺少主密钥或 SMTP 时整项功能明确关闭，绝不降级成把验证码写日志或返回给浏览器。
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import smtplib
import ssl
import time
from email.message import EmailMessage
from email.utils import formataddr
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import delete, select

from nexus import audit, turnstile
from nexus.db import (
    NexusOem,
    NexusOemEmailChallenge,
    NexusOemEmailVerification,
    NexusSession,
)
from nexus.fleet import FleetError

# 邮件码生命周期保持短小：10 分钟、最多尝试 5 次、同邮箱 60 秒冷却且每小时最多 5 封。
_CODE_TTL_MS = 10 * 60 * 1000
_RESEND_COOLDOWN_MS = 60 * 1000
_SEND_WINDOW_MS = 60 * 60 * 1000
_MAX_SENDS_PER_WINDOW = 5
_MAX_ATTEMPTS = 5
_PURPOSES = {"register", "login", "reset"}


def _now_ms() -> int:
    """返回当前毫秒时间戳，便于测试替换和与 Nexus 其他表统一。"""
    return int(time.time() * 1000)


def _smtp_config() -> Optional[Dict[str, Any]]:
    """读取 Nexus 专属 SMTP 配置；缺任一关键字段即返回 ``None``。"""
    host = os.environ.get("NEXUS_SMTP_HOST", "").strip()
    user = os.environ.get("NEXUS_SMTP_USER", "").strip()
    password = os.environ.get("NEXUS_SMTP_PASSWORD", "").strip()
    sender = os.environ.get("NEXUS_SMTP_FROM", "").strip() or user
    if not (host and user and password and sender):
        return None
    try:
        port = int(os.environ.get("NEXUS_SMTP_PORT", "465"))
    except ValueError:
        port = 465
    security = os.environ.get("NEXUS_SMTP_SECURITY", "ssl").strip().lower()
    if security not in {"ssl", "starttls", "plain"}:
        security = "ssl"
    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "sender": sender,
        "sender_name": os.environ.get(
            "NEXUS_SMTP_FROM_NAME", "GuDuu Nexus"
        ).strip()
        or "GuDuu Nexus",
        "security": security,
    }


def enabled() -> bool:
    """只有 SMTP 和 Nexus 主密钥同时就绪时才对前端开放邮箱验证。"""
    return _smtp_config() is not None and len(
        os.environ.get("NEXUS_SECRET_KEY", "").strip()
    ) >= 32


def _normalize_email(email: str) -> str:
    """规范化并做与 OEM 账号层一致的基础邮箱校验。"""
    # 延迟导入避免模块加载时形成 oem ↔ oem_email 循环依赖。
    from nexus.oem import _EMAIL_RE

    value = (email or "").strip().lower()
    if not _EMAIL_RE.match(value):
        raise FleetError("NEXUS_BAD_EMAIL", "邮箱格式不正确")
    return value


def _code_hash(email: str, purpose: str, code: str) -> str:
    """用服务端主密钥计算验证码 HMAC，防数据库泄露后离线枚举六位码。"""
    secret = os.environ.get("NEXUS_SECRET_KEY", "").strip()
    if len(secret) < 32:
        raise FleetError(
            "NEXUS_EMAIL_DISABLED", "邮箱验证服务尚未配置，请联系 GuDuu", 503
        )
    message = f"oem-email:{purpose}:{email}:{code}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def _email_content(code: str, purpose: str) -> Tuple[str, str, str]:
    """构造验证码邮件的主题、纯文本和 HTML；三种用途使用明确不同的文案。"""
    if purpose == "register":
        action = "注册 OEM 企业账号"
        subject = f"【GuDuu Nexus】注册验证码 {code}"
    elif purpose == "login":
        action = "登录 OEM 企业控制台"
        subject = f"【GuDuu Nexus】登录验证码 {code}"
    else:
        action = "重置 OEM 企业账号密码"
        subject = f"【GuDuu Nexus】密码重置验证码 {code}"
    text = (
        f"你正在{action}。\n\n验证码：{code}\n\n"
        "验证码 10 分钟内有效，请勿转发。若非本人操作，请忽略本邮件。"
    )
    html = (
        '<div style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;'
        'max-width:560px;margin:auto;padding:28px;color:#24211f">'
        '<h2 style="margin:0 0 18px;color:#d96f1e">GuDuu Nexus</h2>'
        f'<p>你正在{action}，请在页面输入以下验证码：</p>'
        f'<div style="font:700 32px/1.4 ui-monospace,monospace;letter-spacing:8px;'
        f'padding:18px 22px;background:#f6f0e8;border-radius:12px">{code}</div>'
        '<p style="color:#8a7e72">验证码 10 分钟内有效，请勿转发。'
        '若非本人操作，请忽略本邮件。</p></div>'
    )
    return subject, text, html


def _send_email(to: str, code: str, purpose: str) -> None:
    """通过 SMTP 发送验证码；异常转换成稳定业务错误且绝不记录密码或验证码。"""
    config = _smtp_config()
    if config is None:
        raise FleetError(
            "NEXUS_EMAIL_DISABLED", "邮箱验证服务尚未配置，请联系 GuDuu", 503
        )
    subject, text, html = _email_content(code, purpose)
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((config["sender_name"], config["sender"]))
    message["To"] = to
    message.set_content(text)
    message.add_alternative(html, subtype="html")
    try:
        if config["security"] == "ssl":
            with smtplib.SMTP_SSL(
                config["host"], config["port"], timeout=15,
                context=ssl.create_default_context(),
            ) as smtp:
                smtp.login(config["user"], config["password"])
                smtp.send_message(message)
        else:
            with smtplib.SMTP(config["host"], config["port"], timeout=15) as smtp:
                if config["security"] == "starttls":
                    smtp.starttls(context=ssl.create_default_context())
                smtp.login(config["user"], config["password"])
                smtp.send_message(message)
    except Exception as exc:
        raise FleetError(
            "NEXUS_EMAIL_SEND_FAILED", "验证码邮件发送失败，请稍后重试", 503
        ) from exc


def _account(s, email: str) -> Optional[NexusOem]:
    """按邮箱读取 OEM；是否允许使用由具体业务入口判断。"""
    return s.execute(
        select(NexusOem).where(NexusOem.email == email)
    ).scalar_one_or_none()


def _active_account(s, email: str) -> Optional[NexusOem]:
    """按邮箱查有效 OEM；不存在和停用统一返回 ``None``，避免公开接口枚举状态。"""
    row = _account(s, email)
    return row if row is not None and row.status == "active" else None


def request_code(
    s,
    email: str,
    purpose: str,
    *,
    turnstile_token: str = "",
    source_ip: str = "",
) -> Dict[str, Any]:
    """申请一次邮箱验证码。

    ``login`` / ``reset`` 对不存在或停用账号返回相同成功响应但不发邮件，避免泄露账号
    是否存在；``register`` 对已注册邮箱返回明确冲突，便于真实用户直接去登录或找回。
    """
    if not enabled():
        raise FleetError(
            "NEXUS_EMAIL_DISABLED", "邮箱验证服务尚未配置，请联系 GuDuu", 503
        )
    purpose = (purpose or "").strip().lower()
    if purpose not in _PURPOSES:
        raise FleetError("NEXUS_EMAIL_PURPOSE", "验证码用途不正确")
    # 邮箱格式不是敏感账号状态，先校验可避免用户因拼写错误浪费一次挑战 token。
    normalized = _normalize_email(email)
    # 人机校验仍放在账号查询和 SMTP 之前：既节省邮件成本，也避免利用响应差异枚举账号。
    turnstile.verify(turnstile_token, purpose, source_ip)
    # 注册冲突必须覆盖 active/disabled 两种状态：同一邮箱永远只能对应一个企业账号。
    existing = _account(s, normalized)
    if purpose == "register" and existing is not None:
        raise FleetError("NEXUS_EMAIL_TAKEN", "该邮箱已注册，请直接登录", 409)
    if purpose != "register" and (
        existing is None or existing.status != "active"
    ):
        # 固定响应与真实账号完全相同；不建挑战、不发邮件。
        return {"ok": True, "cooldown_seconds": 60}

    now = _now_ms()
    row = s.get(NexusOemEmailChallenge, (normalized, purpose))
    if row is not None and now - int(row.last_sent_ts) < _RESEND_COOLDOWN_MS:
        wait = max(1, (_RESEND_COOLDOWN_MS - (now - int(row.last_sent_ts))) // 1000)
        raise FleetError("NEXUS_EMAIL_COOLDOWN", f"请等待 {wait} 秒后再发送", 429)
    if row is None:
        row = NexusOemEmailChallenge(email=normalized, purpose=purpose)
        s.add(row)
    if now - int(row.window_started_ts or 0) >= _SEND_WINDOW_MS:
        row.window_started_ts = now
        row.sent_count = 0
    if int(row.sent_count or 0) >= _MAX_SENDS_PER_WINDOW:
        raise FleetError("NEXUS_EMAIL_RATE_LIMIT", "验证码发送过于频繁，请稍后再试", 429)

    code = f"{secrets.randbelow(1_000_000):06d}"
    row.code_hash = _code_hash(normalized, purpose, code)
    row.expires_ts = now + _CODE_TTL_MS
    row.attempts = 0
    row.last_sent_ts = now
    row.sent_count = int(row.sent_count or 0) + 1
    # 先完成 SMTP；若发送失败，HTTP 层会回滚本事务，不留下用户永远收不到的有效码。
    _send_email(normalized, code, purpose)
    return {"ok": True, "cooldown_seconds": 60}


def _consume_code(s, email: str, purpose: str, code: str) -> str:
    """验证并一次性消费邮箱码，成功返回规范化邮箱。"""
    normalized = _normalize_email(email)
    raw_code = (code or "").strip()
    if len(raw_code) != 6 or not raw_code.isdigit():
        raise FleetError("NEXUS_EMAIL_CODE_INVALID", "验证码不正确或已过期", 400)
    row = s.get(NexusOemEmailChallenge, (normalized, purpose))
    now = _now_ms()
    if row is None or int(row.expires_ts) < now or int(row.attempts or 0) >= _MAX_ATTEMPTS:
        if row is not None:
            s.delete(row)
        raise FleetError("NEXUS_EMAIL_CODE_INVALID", "验证码不正确或已过期", 400)
    expected = _code_hash(normalized, purpose, raw_code)
    if not hmac.compare_digest(expected, row.code_hash):
        row.attempts = int(row.attempts or 0) + 1
        if row.attempts >= _MAX_ATTEMPTS:
            s.delete(row)
        raise FleetError("NEXUS_EMAIL_CODE_INVALID", "验证码不正确或已过期", 400)
    s.delete(row)
    return normalized


def _mark_verified(s, account: NexusOem) -> None:
    """幂等记录 OEM 已验证邮箱；邮箱不可在此入口改绑。"""
    row = s.get(NexusOemEmailVerification, int(account.id))
    if row is None:
        s.add(
            NexusOemEmailVerification(
                oem_id=int(account.id), email=account.email, verified_ts=_now_ms()
            )
        )


def register_with_code(
    s,
    *,
    email: str,
    code: str,
    password: str,
    name: str = "",
    inviter: str = "",
    company: str = "",
    contact_name: str = "",
    phone: str = "",
) -> Dict[str, Any]:
    """消费注册码并创建 OEM；账号、层级、档案和验证记录在同一事务提交。"""
    normalized = _consume_code(s, email, "register", code)
    from nexus import oem

    public = oem.register(
        s,
        normalized,
        password,
        name,
        inviter=inviter,
        company=company,
        contact_name=contact_name,
        phone=phone,
    )
    account = s.get(NexusOem, int(public["id"]))
    assert account is not None
    _mark_verified(s, account)
    return public


def login_with_code(s, email: str, code: str) -> Dict[str, Any]:
    """消费登录码并签发 OEM 会话；可作为忘记密码前的无密码登录入口。"""
    normalized = _consume_code(s, email, "login", code)
    account = _active_account(s, normalized)
    if account is None:
        raise FleetError("NEXUS_BAD_CREDENTIALS", "邮箱或验证码不正确", 401)
    from nexus import oem

    _mark_verified(s, account)
    return {"oem": oem.public_oem(account), "token": oem._issue_session(s, account.id)}


def reset_password(
    s, email: str, code: str, new_password: str, source_ip: str = ""
) -> Dict[str, Any]:
    """验证重置码、替换密码并撤销账号所有旧会话。"""
    normalized = _consume_code(s, email, "reset", code)
    account = _active_account(s, normalized)
    if account is None:
        raise FleetError("NEXUS_BAD_CREDENTIALS", "邮箱或验证码不正确", 401)
    from nexus import oem

    problem = oem.password_problem(new_password)
    if problem:
        raise FleetError("NEXUS_WEAK_PASSWORD", problem)
    account.password_hash = oem.hash_password(new_password)
    s.execute(delete(NexusSession).where(NexusSession.oem_id == int(account.id)))
    _mark_verified(s, account)
    audit.record(
        s,
        object_type="oem",
        object_id=int(account.id),
        action="password_reset",
        actor_type="oem",
        actor_label=account.email,
        source_ip=source_ip,
        note="OEM 通过邮箱验证码重置密码；全部旧会话已撤销。",
    )
    return {"ok": True}


__all__ = [
    "enabled",
    "login_with_code",
    "register_with_code",
    "request_code",
    "reset_password",
]
