"""自建「邮箱验证码」注册。

为什么自建（而不是用 Synapse 原生邮箱注册）：
  Synapse 原生的邮箱注册发的是**验证链接**（点链接验证 3pid）；负责人要的是**验证码**体验
  （邮件里给 6 位码、用户在 app 里输）。Synapse 不原生支持验证码，故自建这一层：
    1) 前端填邮箱 → POST /cosmac/register/request-code → 这里生成 6 位码、用 SMTP（Lark）发信。
    2) 前端填用户名+密码+码 → POST /cosmac/register/verify → 这里验码 → 用
       registration_shared_secret 向 Synapse `/_synapse/admin/v1/register` 建号
       （该端点是给程序化建号用的，**不受 enable_registration 开关影响**——所以建完号后
        服务端应把开放注册关掉，强制所有注册都走我们的邮箱验证）。

安全 / 健壮（单实例「够用即止」，与 wf 同口径）：
  · 验证码存**内存**（带 TTL + 线程锁）——单 bot 实例足够；将来多实例再迁 DB。
  · 限频：同邮箱发码有冷却 + 每小时上限；验码有尝试次数上限（防爆破）。
  · 真密钥（SMTP 密码 / registration_shared_secret）只从**服务端 env** 读，绝不进代码/前端/Matrix。

涉及的 env（生产用 systemd Environment / Secret Manager 注入；本地不配则注册不可用、优雅报错）：
  COSMAC_SMTP_HOST / COSMAC_SMTP_PORT(默认465) / COSMAC_SMTP_USER / COSMAC_SMTP_PASSWORD /
  COSMAC_SMTP_FROM(发件地址，如 noreply@guduu.co) / COSMAC_SMTP_FROM_NAME(可选，显示名) /
  COSMAC_REGISTRATION_SHARED_SECRET(= homeserver.yaml 里的 registration_shared_secret)
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import smtplib
import ssl
import threading
import time
from email.message import EmailMessage
from email.utils import formataddr
from typing import Any, Callable, Dict, Optional, Tuple

import requests

from cosmac.config import _env

logger = logging.getLogger("cosmac.registration")

# ── 可调参数（够用即止，不做成配置项）────────────────────────────
_CODE_TTL = 10 * 60          # 验证码有效期（秒）
_RESEND_COOLDOWN = 60        # 同邮箱两次发码的最小间隔（秒）
_MAX_SENDS_PER_HOUR = 5      # 同邮箱每小时最多发码次数（防刷爆 Lark 配额）
_MAX_VERIFY_ATTEMPTS = 5     # 单个码最多验错几次（防爆破）
_HS_TIMEOUT = 15            # 调 Synapse 的超时（秒）

# 邮箱 / 用户名 / 密码 的基本校验
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Matrix localpart 安全子集（小写）。去掉了 `/`——localpart 习惯不含斜杠，且这个值会拼进
# reset 的 user_id / admin URL 路径，留着 `/` 平白增加路径注入面、无正当用途。
_USERNAME_RE = re.compile(r"^[a-z0-9._=\-+]+$")
_USERNAME_MAX = 64           # localpart 长度上限（防超长 localpart 造成异常账号）

# 常见弱密码小表（全网泄露榜高频项；小写比对）。够拦住最烂的那批就行——真正的防线是
# 长度+字符类别+IP限频，不追求大而全的字典（那是 zxcvbn 的活，单实例不引重依赖）。
_COMMON_WEAK = {
    "password", "password1", "passw0rd", "12345678", "123456789", "1234567890",
    "qwerty123", "qwertyuiop", "11111111", "88888888", "66666666", "00000000",
    "abc12345", "a1234567", "iloveyou", "admin123", "root1234", "letmein1",
    "sunshine", "princess", "football", "baseball", "dragon123", "monkey123",
    "qq123456", "wang1234", "zhang123", "asdfghjkl", "1q2w3e4r", "1qaz2wsx",
}


def password_problem(password: str, username: str = "") -> Optional[str]:
    """检查新设密码的强度；不合格返回中文原因，合格返回 None。

    规则（按 NIST 思路——长度优先，不强制大小写符号那种反人类组合）：
      ① 至少 8 位；② 至少两类字符（字母/数字/符号）；③ 不在常见弱密码表；
      ④ 不包含用户名（防 "alice2024" 这类一猜即中）。
    只在**新设密码**时（注册/重置）强制，老账号既有密码不受影响。
    前端 AuthView 有同一套规则的即时提示，这里是服务端真防线（防绕过前端直调 API）。
    """
    pw = password or ""
    if len(pw) < 8:
        return "密码至少 8 位"
    if len(pw) > 512:  # Synapse 硬上限 512;提前拦,别让超长密码走完流程再被英文原文拒(低⑥)
        return "密码过长（最多 512 位）"
    low = pw.lower()
    kinds = sum((
        any(ch.isalpha() for ch in pw),
        any(ch.isdigit() for ch in pw),
        any(not ch.isalnum() for ch in pw),
    ))
    if kinds < 2:
        return "密码太简单：请混用字母、数字或符号中的至少两类"
    if low in _COMMON_WEAK:
        return "这个密码太常见、极易被猜中，请换一个"
    u = (username or "").strip().lower()
    if u and len(u) >= 4 and u in low:
        return "密码不能包含你的用户名"
    return None


class _PendingCode:
    """某邮箱待验证的码 + 限频计数（仅内存）。"""

    __slots__ = ("code", "expires", "attempts", "last_sent", "sent_times")

    def __init__(self) -> None:
        self.code: str = ""
        self.expires: float = 0.0
        self.attempts: int = 0
        self.last_sent: float = 0.0
        self.sent_times: list[float] = []  # 最近一小时的发码时间戳（滑窗限频）


# key（"用途:邮箱小写"）→ _PendingCode；多线程 HTTP server，必须加锁。
# 用「用途」前缀把注册码和找回密码码分开存——注册码不能拿去重置密码，反之亦然。
_store: Dict[str, _PendingCode] = {}
_lock = threading.Lock()

# ── 按客户端 IP 的全局限频（纵深防御）──────────────────────────────
# 为什么：上面的限频是按**邮箱**算的，攻击者枚举不同邮箱即可绕过（刷爆 SMTP 配额、
# 给真实用户狂发骚扰码、放大 6 位码爆破空间）。再叠一层按 IP 的滑窗限频堵住批量枚举。
# 注：nginx 反代后真实 IP 在 X-Forwarded-For，调用方负责取真实 IP 传进来。
_IP_SEND_MAX = 20            # 单 IP 每小时最多触发发码（注册 + 找回合计）
_IP_SEND_WINDOW = 3600
_IP_ATTEMPT_MAX = 30         # 单 IP 每 15 分钟最多验码/登录尝试（限撞库/爆破）
_IP_ATTEMPT_WINDOW = 900
_ip_store: Dict[str, list[float]] = {}   # "桶:ip" → 命中时间戳滑窗
_ip_lock = threading.Lock()


def _prune_ip_store(now: float) -> None:
    """丢弃所有时间戳都过期的 IP 桶，防内存无限增长。调用方需已持 _ip_lock。"""
    dead = [k for k, ts in _ip_store.items()
            if not any(now - t < _IP_SEND_WINDOW for t in ts)]
    for k in dead:
        _ip_store.pop(k, None)


def _ip_rate_ok(bucket: str, ip: str, limit: int, window: int) -> bool:
    """按 IP 滑窗限频；命中上限返回 False。

    ip 为空（拿不到真实 IP，例如本地直连/未配反代）时**不限**，返回 True——宁可放过也别误伤
    全体用户。单实例内存计数，与验证码同口径（够用即止）。
    """
    if not ip:
        return True
    now = time.time()
    key = f"{bucket}:{ip}"
    with _ip_lock:
        times = [t for t in _ip_store.get(key, ()) if now - t < window]
        if len(times) >= limit:
            _ip_store[key] = times
            return False
        times.append(now)
        _ip_store[key] = times
        if len(_ip_store) > 10000:   # 偶发清理，避免字典在长期运行中膨胀
            _prune_ip_store(now)
        return True


def _key(purpose: str, email: str) -> str:
    return f"{purpose}:{email}"


def _gen_code() -> str:
    """生成 6 位数字验证码（用密码学安全随机，避免可预测）。"""
    import secrets
    return f"{secrets.randbelow(1_000_000):06d}"


def turnstile_enabled() -> bool:
    """配了 Cloudflare Turnstile 的 secret 才算启用人机验证（没配则相关校验自动跳过）。"""
    return bool(_env("TURNSTILE_SECRET"))


def _verify_turnstile(token: str, client_ip: str = "") -> bool:
    """向 Cloudflare 校验 Turnstile 令牌。**没配 secret → 直接放行**（功能可插拔,不破坏现有流程）。

    配了 secret 就强制:token 空或校验不过一律 False。校验用服务端 secret,绝不进前端/日志。
    网络异常时保守拒绝(返回 False)——人机验证挡不住就宁可让用户重试,不放过。
    """
    secret = _env("TURNSTILE_SECRET")
    if not secret:
        return True  # 未启用:放行
    token = (token or "").strip()
    if not token:
        return False
    try:
        resp = requests.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={"secret": secret, "response": token, "remoteip": client_ip or ""},
            timeout=10,
        )
        return bool(resp.json().get("success"))
    except Exception:
        logger.warning("Turnstile 校验调用失败", exc_info=True)
        return False


def _smtp_conf() -> Optional[Dict[str, Any]]:
    """读 SMTP 配置；缺关键项则返回 None（注册功能视为未启用）。"""
    host = _env("SMTP_HOST")
    user = _env("SMTP_USER")
    password = _env("SMTP_PASSWORD")
    sender = _env("SMTP_FROM") or user
    if not (host and user and password and sender):
        return None
    try:
        port = int(_env("SMTP_PORT", "465"))
    except ValueError:
        port = 465
    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "from": sender,
        "from_name": _env("SMTP_FROM_NAME", "GuDuu OS"),
    }


def registration_enabled() -> bool:
    """SMTP 与共享密钥都配齐才算「自建注册」可用。"""
    return _smtp_conf() is not None and bool(_env("REGISTRATION_SHARED_SECRET"))


def reset_enabled() -> bool:
    """SMTP 与管理员令牌都配齐才算「找回密码」可用（重置密码要管理员权限）。"""
    return _smtp_conf() is not None and bool(_env("ADMIN_TOKEN"))


def _build_email(code: str, kind: str = "register") -> Tuple[str, str, str]:
    """构造验证码邮件，返回 (主题, 纯文本, HTML)。kind: register（注册）/ reset（找回密码）。

    HTML 用「邮件安全」写法：表格布局 + 全内联样式（Gmail/Outlook 会剥离 <style>、不支持
    flex/grid）。抬头用**纯文字标识**（不外链图片）——邮件客户端默认不加载远程图、且跨域
    外链图会拉低投递评分（更易进垃圾箱），所以不放 logo 图。
    """
    mins = _CODE_TTL // 60
    if kind == "login":
        subject = f"【GuDuu OS】登录安全验证码 {code}"
        heading = "验证是你本人在登录"
        intro = "检测到你的账号在**新设备/新地点**尝试登录。请在登录页输入下面的验证码完成验证："
        plain = (
            f"检测到你的账号在新设备/新地点尝试登录。\n\n"
            f"验证码：{code}\n\n"
            f"{mins} 分钟内有效。如果这不是你本人的操作，说明有人知道了你的密码——请立即修改密码。"
        )
        note = "如果这不是你本人的操作，说明有人可能知道了你的密码，请立即用「忘记密码」修改密码。"
    elif kind == "reset":
        subject = f"【GuDuu OS】重置密码验证码 {code}"
        heading = "重置你的密码"
        intro = "你正在重置 GuDuu OS 的登录密码。请在页面输入下面的验证码："
        plain = (
            f"你正在重置 GuDuu OS 的登录密码。\n\n"
            f"验证码：{code}\n\n"
            f"{mins} 分钟内有效。如果这不是你本人的操作，忽略本邮件即可，密码不会被更改。"
        )
        note = "如果这不是你本人的操作，忽略本邮件即可，你的密码不会被更改。"
    else:
        subject = f"【GuDuu OS】注册验证码 {code}"
        heading = "验证你的邮箱"
        intro = "你正在注册 GuDuu OS。请在页面输入下面的验证码完成注册："
        plain = (
            f"你正在注册 GuDuu OS。\n\n"
            f"验证码：{code}\n\n"
            f"{mins} 分钟内有效。如果这不是你本人的操作，忽略本邮件即可，账号不会有任何变化。"
        )
        note = "如果这不是你本人的操作，忽略本邮件即可，你的账号不会有任何变化。"
    html = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"></head>
<body style="margin:0;background:#f1efe9;font-family:-apple-system,'PingFang SC',sans-serif;">
<div style="padding:32px 16px;">
<table role="presentation" cellpadding="0" cellspacing="0" border="0" align="center" style="width:100%;max-width:480px;margin:0 auto;background:#ffffff;border-radius:16px;border:1px solid #eae6df;">
<tr><td style="padding:30px 36px 8px;">
<div style="font-size:19px;font-weight:600;color:#2c2a26;letter-spacing:.3px;"><span style="color:#c96442;">✦</span>&nbsp;GuDuu OS&nbsp;<span style="color:#c96442;">Star</span></div>
</td></tr>
<tr><td style="padding:14px 36px 0;">
<div style="font-size:20px;font-weight:600;color:#2c2a26;">{heading}</div>
<div style="font-size:14px;line-height:1.7;color:#6b665e;margin-top:10px;">{intro}</div>
</td></tr>
<tr><td style="padding:22px 36px 6px;">
<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="width:100%;background:#faece7;border:1px solid #f0d8cd;border-radius:12px;">
<tr><td align="center" style="padding:20px 12px;">
<div style="font-size:32px;font-weight:700;letter-spacing:10px;color:#993c1d;padding-left:10px;">{code}</div>
</td></tr></table>
<div style="font-size:12px;color:#8a8378;margin-top:10px;text-align:center;">验证码 {mins} 分钟内有效</div>
</td></tr>
<tr><td style="padding:14px 36px 0;">
<div style="font-size:13px;line-height:1.7;color:#8a8378;">{note}</div>
</td></tr>
<tr><td style="padding:22px 36px 28px;">
<div style="border-top:1px solid #eee9e1;padding-top:14px;font-size:12px;color:#ada699;line-height:1.6;">此邮件由系统自动发送，请勿直接回复。<br>© GuDuu OS</div>
</td></tr>
</table>
</div>
</body></html>"""
    return subject, plain, html


def _smtp_send(to_addr: str, subject: str, plain: str, html: str) -> None:
    """用 SMTP（SSL/465 优先）发一封 HTML+纯文本邮件；失败抛异常由调用方兜底。"""
    conf = _smtp_conf()
    if not conf:
        raise RuntimeError("SMTP 未配置")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((conf["from_name"], conf["from"]))
    msg["To"] = to_addr
    msg.set_content(plain)                       # 纯文本兜底（老客户端 / 不渲染 HTML 时显示）
    msg.add_alternative(html, subtype="html")    # 品牌化 HTML 正文（现代客户端显示这个）
    ctx = ssl.create_default_context()
    # 465=SSL 直连；587=STARTTLS。Lark 两个都给，这里按端口择一。
    if conf["port"] == 587:
        with smtplib.SMTP(conf["host"], conf["port"], timeout=20) as s:
            s.starttls(context=ctx)
            s.login(conf["user"], conf["password"])
            s.send_message(msg)
    else:
        with smtplib.SMTP_SSL(conf["host"], conf["port"], context=ctx, timeout=20) as s:
            s.login(conf["user"], conf["password"])
            s.send_message(msg)


def _send_email(to_addr: str, code: str) -> None:
    """发**注册**验证码邮件。"""
    _smtp_send(to_addr, *_build_email(code, "register"))


def _send_reset_email(to_addr: str, code: str) -> None:
    """发**找回密码**验证码邮件。"""
    _smtp_send(to_addr, *_build_email(code, "reset"))


def _issue_code(key: str, send: Callable[[str], None]) -> Tuple[int, Dict[str, Any]]:
    """通用「发码」：限频 + 存码 + 发信。注册/找回密码共用。send(code) 负责真正发信。"""
    now = time.time()
    with _lock:
        pc = _store.get(key) or _PendingCode()
        # 滑窗：清掉一小时前的发码记录，再判每小时上限
        pc.sent_times = [t for t in pc.sent_times if now - t < 3600]
        if pc.last_sent and now - pc.last_sent < _RESEND_COOLDOWN:
            wait = int(_RESEND_COOLDOWN - (now - pc.last_sent))
            # 冷却中：60s 内刚发过，码(TTL 10min)必然仍有效 → code_valid=True（M14）
            return 429, {"error": f"发送太频繁，请 {wait} 秒后再试", "cooldown": wait,
                         "code_valid": True}
        if len(pc.sent_times) >= _MAX_SENDS_PER_HOUR:
            # 每小时上限：这次**不发新码**。仅当仍存在未过期的旧码，才算"有有效码可验"——
            # 否则(旧码已过 TTL)返回 code_valid=False，调用方据此别假装码已发出（M14 自锁修复）。
            code_valid = bool(pc.code and pc.expires > now)
            return 429, {"error": "请求过于频繁，请稍后再试", "code_valid": code_valid}
        code = _gen_code()
        pc.code = code
        pc.expires = now + _CODE_TTL
        pc.attempts = 0
        pc.last_sent = now
        pc.sent_times.append(now)
        _store[key] = pc

    # 发信放锁外（网络 IO 可能慢，别占着锁）
    try:
        send(code)
    except Exception:
        logger.exception("发送验证码邮件失败: %s", key)
        # 发失败就把这次的码作废，避免用户拿不到码却被限频
        with _lock:
            cur = _store.get(key)
            if cur and cur.code == code:
                cur.code = ""
                if cur.sent_times:
                    cur.sent_times.pop()
                cur.last_sent = 0.0
        return 502, {"error": "验证码邮件发送失败，请稍后重试"}

    return 200, {"ok": True, "cooldown": _RESEND_COOLDOWN}


def request_code(
    email: str, *, client_ip: str = "", turnstile: str = ""
) -> Tuple[int, Dict[str, Any]]:
    """发**注册**验证码到邮箱。返回 (http状态, 响应体)。turnstile=前端人机验证令牌。"""
    if not registration_enabled():
        return 503, {"error": "服务器未开启邮箱注册"}
    email = (email or "").strip().lower()
    if not _EMAIL_RE.match(email):
        return 400, {"error": "邮箱格式不正确"}
    # 先过 IP 限频、再打 Cloudflare——否则带假 token 的请求能无限速触发出站 siteverify、占共享线程池
    # (审查中④)。校验/限频都放在 _verify_turnstile 之前。
    if not _ip_rate_ok("send", client_ip, _IP_SEND_MAX, _IP_SEND_WINDOW):
        return 429, {"error": "请求过于频繁，请稍后再试"}
    if not _verify_turnstile(turnstile, client_ip):
        return 400, {"error": "人机验证未通过，请重试"}
    return _issue_code(_key("register", email), lambda c: _send_email(email, c))


def _check_code(email: str, code: str, purpose: str = "register") -> Tuple[bool, Optional[str]]:
    """校验邮箱+码（按用途分桶）；通过返回 (True, None)，否则 (False, 错误文案)。通过即作废。"""
    code = (code or "").strip()
    with _lock:
        pc = _store.get(_key(purpose, email))
        if not pc or not pc.code:
            return False, "请先获取验证码"
        if time.time() > pc.expires:
            pc.code = ""
            return False, "验证码已过期，请重新获取"
        if pc.attempts >= _MAX_VERIFY_ATTEMPTS:
            pc.code = ""
            return False, "验证码错误次数过多，请重新获取"
        if not hmac.compare_digest(pc.code, code):
            pc.attempts += 1
            return False, "验证码不正确"
        # 验过即作废（一次性）
        pc.code = ""
        return True, None


def _synapse_register(hs_url: str, username: str, password: str) -> Tuple[int, Dict[str, Any]]:
    """用 registration_shared_secret 向 Synapse 建号（HMAC nonce 流程）。

    /_synapse/admin/v1/register：先 GET 拿 nonce，再用 HMAC-SHA1 算 mac 后 POST。
    该端点不受 enable_registration 影响，专供程序化建号。
    """
    secret = _env("REGISTRATION_SHARED_SECRET")
    if not secret:
        return 503, {"error": "服务器未配置注册密钥"}
    base = hs_url.rstrip("/")
    url = f"{base}/_synapse/admin/v1/register"
    try:
        r = requests.get(url, timeout=_HS_TIMEOUT)
        nonce = r.json().get("nonce")
        if not nonce:
            return 502, {"error": "注册服务暂不可用"}
        # mac = HMAC_SHA1(secret, nonce \0 user \0 password \0 notadmin)
        mac = hmac.new(secret.encode("utf-8"), digestmod=hashlib.sha1)
        mac.update(b"\x00".join([
            nonce.encode("utf-8"),
            username.encode("utf-8"),
            password.encode("utf-8"),
            b"notadmin",
        ]))
        body = {
            "nonce": nonce,
            "username": username,
            "password": password,
            "admin": False,
            "mac": mac.hexdigest(),
        }
        rr = requests.post(url, json=body, timeout=_HS_TIMEOUT)
        if rr.status_code == 200:
            return 200, rr.json()
        # Synapse 把"用户名已占用"等错误放在 body.errcode/error。
        # ⚠️ 判定要用 **errcode**（M_USER_IN_USE）：Synapse 1.141 的文案是
        # "User ID already taken."——既不含 "in use" 也不含 "exist"，只匹配文本会漏判、
        # 把英文原文 400 直接怼给用户（审查 bug#5，原实现即此病）。文本匹配仅作兜底。
        err = ""
        errcode = ""
        try:
            j = rr.json()
            err = j.get("error", "")
            errcode = j.get("errcode", "")
        except Exception:
            pass
        low = err.lower()
        if (
            errcode == "M_USER_IN_USE"
            or "in use" in low or "taken" in low
            or (rr.status_code == 400 and "exist" in low)
        ):
            return 409, {"error": "该用户名已被占用，请换一个"}
        return rr.status_code if rr.status_code >= 400 else 502, {"error": err or "注册失败"}
    except requests.RequestException:
        logger.exception("调用 Synapse 共享密钥注册失败")
        return 502, {"error": "注册服务暂不可用，请稍后重试"}


def verify_and_register(
    email: str, code: str, username: str, password: str, *, hs_url: str,
    client_ip: str = "",
) -> Tuple[int, Dict[str, Any]]:
    """验码 → 建号。成功返回 (200, {user_id, access_token...})。"""
    if not registration_enabled():
        return 503, {"error": "服务器未开启邮箱注册"}
    email = (email or "").strip().lower()
    username = (username or "").strip().lower()
    if not _EMAIL_RE.match(email):
        return 400, {"error": "邮箱格式不正确"}
    if not username or not _USERNAME_RE.match(username) or len(username) > _USERNAME_MAX:
        return 400, {"error": "用户名只能用小写字母/数字/._-=+，且不超过 64 位"}
    weak = password_problem(password, username)
    if weak:
        return 400, {"error": weak}
    # 按 IP 限制验码尝试（叠加单码 5 次上限，堵住「不断重发刷新尝试计数 + 多邮箱并发」爆破）。
    if not _ip_rate_ok("attempt", client_ip, _IP_ATTEMPT_MAX, _IP_ATTEMPT_WINDOW):
        return 429, {"error": "尝试过于频繁，请稍后再试"}

    ok, msg = _check_code(email, code, purpose="register")
    if not ok:
        return 400, {"error": msg}

    # 一邮一号：验码通过后、**建号前先占位**。
    # 靠 cosmac DB 的邮箱唯一约束原子占位，堵死"先查后建"的 TOCTOU 并发窗口；占位放在建号
    # **之前**，邮箱已被占就直接 409、**根本不建号**——从根上杜绝"同邮箱建出多个账号、映射
    # 只留最后一个"的历史 bug（那正是找回密码只能重置其中一个的病根）。
    # 放在验码之后：未持邮箱的人无法借 409 探测"某邮箱是否已注册"（防枚举）；验码通过=本人，
    # 此时告知"已注册"并引导去登录/找回，是合理的。
    claim = _claim_email(email, username)
    if claim == "taken":
        return 409, {"error": "该邮箱已注册，请直接登录或找回密码"}
    if claim is None:
        # cosmac DB 异常：它与 Synapse 同一套 Postgres，它不可用时建号本也走不通，故 fail-closed
        # ——宁可挡下这次注册，也不在拿不到唯一约束保证时冒险破坏一邮一号。
        return 503, {"error": "注册服务暂不可用，请稍后重试"}

    status, payload = _synapse_register(hs_url, username, password)
    _audit("register", subject=username, ip=client_ip, ok=(status == 200),
           detail="ok" if status == 200 else f"hs_{status}")
    if status != 200 and claim == "claimed" and 400 <= status < 500:
        # 只在「本次新占位 + 确定性失败(4xx,如用户名已占用/参数错)」时回滚占位。
        # ⚠️ 5xx/网络超时是**结果未知**——账号可能已在 Synapse 建成,此时删映射=该账号永远
        # 无法邮箱登录/找回(审查 bug#6)。保住映射,本人重试时 _claim_email 走 "existing"
        # 自愈:账号没建成→重试成功;已建成→报"用户名已占用",可走找回密码拿回账号。
        _release_email(email, username)
    # 建号失败时不还原验证码（已一次性作废）——让用户重新走流程，避免码被复用。
    return status, payload


def _claim_email(email: str, username: str) -> Optional[str]:
    """一邮一号「占位」：把 email→username 写进映射表。建号**之前**调用。

    返回（字符串枚举，调用方按值分流）：
      · ``"claimed"``  —— 邮箱原本空闲，**新占位**成功（建号失败时需回滚这条占位）。
      · ``"existing"`` —— 邮箱**本就绑定本账号**：视为占位成功但**不可回滚**——这是"上次建号
                         结果未知(超时/5xx)后本人重试"的自愈通道；也可能账号早已建成，此时后续
                         建号会撞 M_USER_IN_USE 报「用户名已占用」，但映射必须保住（否则该账号
                         永远无法邮箱登录/找回，见审查 bug#6）。
      · ``"taken"``    —— 已被**别的**账号占（或并发撞唯一约束）；调用方回 409「已注册」。
      · ``None``       —— cosmac DB 异常；调用方 fail-closed（回 503）。
    """
    from sqlalchemy.exc import IntegrityError
    try:
        from cosmac.db import session_scope
        from cosmac.db.email_repo import EmailAlreadyBound, set_email
        try:
            with session_scope() as s:
                # set_email：True=新插入；False=已绑同账号；抛 EmailAlreadyBound=已绑别的账号。
                created = set_email(s, email=email, username=username)
                return "claimed" if created else "existing"
        except EmailAlreadyBound:
            return "taken"
    except IntegrityError:
        # 并发下别人抢先占了同一邮箱，提交时撞唯一约束 → 视为"已被占"。
        return "taken"
    except Exception:
        logger.warning("占位邮箱映射失败（cosmac DB 不可用？）email=%s", email, exc_info=True)
        return None


def _release_email(email: str, username: str) -> None:
    """回滚占位：删掉 email→username 映射（仅当当前确实绑的是它）。尽力而为，失败仅告警不抛。"""
    try:
        from cosmac.db import session_scope
        from cosmac.db.email_repo import clear_email
        with session_scope() as s:
            clear_email(s, email=email, username=username)
    except Exception:
        logger.warning(
            "回滚邮箱占位失败 email=%s（可能残留一条映射，不影响账号）", email, exc_info=True
        )


def _lookup_username(email: str) -> Optional[str]:
    """按邮箱反查用户名 localpart（找回密码用）。查不到/出错返回 None。"""
    try:
        from cosmac.db import session_scope
        from cosmac.db.email_repo import get_username_by_email
        with session_scope() as s:
            return get_username_by_email(s, email)
    except Exception:
        logger.debug("查邮箱→用户名映射失败", exc_info=True)
        return None


# 「限频命中」的审计采样:同一 IP 在窗口内只入库第一条 rate_limited,其余只走日志。
# 否则超限请求(不消耗限频计数、可无限打)每条一次 DB 写 → 表/索引无限膨胀(审查中③)。
_RL_AUDIT_WINDOW = 600
_rl_audit_seen: Dict[str, float] = {}
_rl_audit_lock = threading.Lock()


def _stepup_enabled() -> bool:
    """异地登录二次验证的总开关(env COSMAC_LOGIN_STEPUP=1 才启用;默认关,部署零风险)。"""
    return (_env("LOGIN_STEPUP", "") or "").lower() in ("1", "true", "yes")


def _ip_bucket(ip: str) -> str:
    """把 IP 归并到「地区级」网段桶:IPv4 取前两段(/16)、IPv6 取前 4 组(/64 级)。

    为什么不用精确 IP:手机/家庭宽带的出口 IP 经常变,精确比对会天天误报;/16 近似
    「同运营商同地区」,误报和漏报的折中。将来要更准就换 GeoIP 城市库,这里只动此函数。
    """
    ip = (ip or "").strip().lower()
    if ":" in ip:
        return ":".join(ip.split(":")[:4])
    return ".".join(ip.split(".")[:2])


def _login_risky(username: str, client_ip: str) -> bool:
    """异地判定:当前 IP 网段与该用户**所有**历史成功登录网段都不同 → 可疑。

    无历史(新用户/审计刚上线的老用户)或查询失败 → 不可疑(fail-open:step-up 是增强,
    数据不足/DB 故障时绝不把人锁在门外)。数据来源=阶段0 的认证审计表。
    """
    if not client_ip:
        return False
    try:
        from cosmac.db import session_scope
        from cosmac.db.auth_event_repo import recent_success_ips
        with session_scope() as s:
            ips = recent_success_ips(s, username)
    except Exception:
        logger.debug("读历史登录 IP 失败(按不可疑处理)", exc_info=True)
        return False
    if not ips:
        return False
    cur = _ip_bucket(client_ip)
    return all(_ip_bucket(x) != cur for x in ips)


def _email_for_login(username: str) -> Optional[str]:
    """按用户名反查绑定邮箱(step-up 发码用)。没有/出错返回 None。"""
    try:
        from cosmac.db import session_scope
        from cosmac.db.email_repo import get_email_by_username
        with session_scope() as s:
            return get_email_by_username(s, username)
    except Exception:
        return None


def _mask_email(email: str) -> str:
    """邮箱打码展示(g***@gmail.com):提示发到哪了,又不把完整邮箱亮给可能的攻击者。"""
    try:
        local, dom = email.split("@", 1)
        return f"{local[0]}***@{dom}"
    except Exception:
        return "你的绑定邮箱"


def _revoke_token(hs_url: str, token: str) -> None:
    """尽力撤销一个 Synapse access token(step-up 挑战时,刚登出来的 token 不能留)。失败仅记日志。"""
    if not token:
        return
    try:
        requests.post(
            f"{hs_url.rstrip('/')}/_matrix/client/v3/logout",
            headers={"Authorization": f"Bearer {token}"},
            timeout=_HS_TIMEOUT,
        )
    except Exception:
        logger.debug("撤销 step-up 暂扣 token 失败(该 token 未外泄,仅 Synapse 多一个 device)", exc_info=True)


def _send_login_email(to_addr: str, code: str) -> None:
    """发**登录二次验证**验证码邮件。"""
    _smtp_send(to_addr, *_build_email(code, "login"))


def _stepup_gate(
    username: str, email: Optional[str], code: str, *,
    hs_url: str, client_ip: str, token: str,
) -> Optional[Tuple[int, Dict[str, Any]]]:
    """密码验证通过后的异地二次验证闸。返回 None=放行;返回 (状态,body)=拦截(挑战/发码失败)。

    调用方约定:code 非空时**必须已在登录前验过码**(这里不再验),此闸只处理"要不要发起挑战"。
    ⚠️ token 是刚从 Synapse 拿到的:发起挑战=不把它交给前端,还要尽力撤销(不留悬空凭据)。
    """
    if not _stepup_enabled() or code:
        return None                      # 未启用,或本次已带码验过(第二步) → 放行
    if not _login_risky(username, client_ip):
        return None                      # 常用地区 → 放行
    if not email:
        # 没绑邮箱(老账号)无法二次验证 → 放行但审计留痕,别把人锁死
        _audit("login", subject=username, ip=client_ip, ok=True, detail="stepup_skipped_no_email")
        return None
    _revoke_token(hs_url, token)         # 挑战:先撤刚发的 token
    sc, _sb = _issue_code(_key("login", email), lambda c: _send_login_email(email, c))
    # M14：区分两种 429——① 60s 冷却(code_valid=True，码刚发过仍有效)→ 照常进挑战；② 每小时发码
    # 上限且**无有效码**(code_valid=False)→ 这次没发出码、旧码也过期了，绝不能假装码已发让用户对着
    # 空挑战干等自锁。此时明确告知稍后再试(密码已对，仅安全验证码被限频)。
    if sc == 429 and not _sb.get("code_valid"):
        _audit("login", subject=username, ip=client_ip, ok=False, detail="stepup_send_ratelimited")
        return 429, {"error": "安全验证码发送已达上限，请过一会儿再登录。"}
    if sc not in (200, 429):             # 其它(如 502 发信失败)
        _audit("login", subject=username, ip=client_ip, ok=False, detail="stepup_send_fail")
        return 502, {"error": "安全验证码发送失败，请稍后重试"}
    _audit("login", subject=username, ip=client_ip, ok=False, detail="stepup_challenge")
    return 200, {
        "step_up": True,
        "email_hint": _mask_email(email),
        "error": "",  # 占位:前端统一按 step_up 分支处理
    }


def _audit(kind: str, *, subject: str = "", ip: str = "", ok: bool = False, detail: str = "") -> None:
    """记一条认证审计事件（登录/注册/找回）。best-effort——记日志失败绝不影响认证主流程。

    收口后所有认证都经后端，故这里能拿到可信 IP、成败、主体，为异地检测/风控攒数据。
    绝不记密码/验证码/token（只记 kind/subject/ip/ok/detail）。
    「限频命中」事件按 IP 在 _RL_AUDIT_WINDOW 秒内去重入库（防超限请求刷爆审计表）。
    """
    if detail == "rate_limited" and ip:
        now = time.time()
        with _rl_audit_lock:
            last = _rl_audit_seen.get(ip, 0.0)
            if now - last < _RL_AUDIT_WINDOW:
                logger.info("认证限频命中(已采样,不入库) ip=%s kind=%s", ip, kind)
                return
            _rl_audit_seen[ip] = now
            if len(_rl_audit_seen) > 10000:  # 偶发清理,防字典膨胀
                for k in [k for k, t in _rl_audit_seen.items() if now - t > _RL_AUDIT_WINDOW]:
                    _rl_audit_seen.pop(k, None)
    try:
        from cosmac.db import session_scope
        from cosmac.db.auth_event_repo import record
        with session_scope() as s:
            record(s, kind=kind, subject=subject, ip=ip, ok=ok, detail=detail)
    except Exception:
        logger.debug("写认证审计失败（忽略）：kind=%s", kind, exc_info=True)


def _proxy_synapse_login(
    hs_url: str, username: str, password: str, client_ip: str, server_name: str = ""
) -> Tuple[int, Dict[str, Any]]:
    """经 bot 代理向 Synapse 做密码登录,返回 (对外状态, 对外body)。收口的公共实现。

    ⚠️ 关键(审查高①):收口后所有登录都从 bot(127.0.0.1)打向 Synapse,若不转发真实客户端 IP,
    Synapse 的 rc_login 会按"bot 单一 IP"给**全平台**共享限频(默认 burst 5)→ 几个用户同时登录
    第 N 个就被 Synapse 429。这里带 X-Forwarded-For 让 Synapse 按真实客户端 IP 限频
    (需 Synapse 监听器 x_forwarded: true,本部署 client 监听已开)。
    并**区分状态码**:Synapse 429→回 429、5xx/网络→回 502,只有 401/403 才回"用户名或密码错误"——
    否则被限频的用户会看到"密码错误"、改密码也没用(审查高①)。
    """
    base = hs_url.rstrip("/")
    headers = {}
    if client_ip:
        headers["X-Forwarded-For"] = client_ip
    try:
        resp = requests.post(
            f"{base}/_matrix/client/v3/login",
            json={
                "type": "m.login.password",
                "identifier": {"type": "m.id.user", "user": username},
                "password": password,
                "initial_device_display_name": "GuDuu OS Web",
            },
            headers=headers,
            timeout=_HS_TIMEOUT,
        )
    except requests.RequestException:
        logger.exception("代理 Synapse 登录失败")
        return 502, {"error": "登录服务暂不可用，请稍后重试"}
    if resp.status_code == 200:
        return 200, resp.json()
    if resp.status_code == 429:
        # 透传"太频繁",别误报密码错
        return 429, {"error": "尝试过于频繁，请稍后再试"}
    if resp.status_code >= 500:
        return 502, {"error": "登录服务暂不可用，请稍后重试"}
    # 账号被**锁定**(新版停用):Synapse 回 401 + errcode=M_USER_LOCKED。给专门文案——
    # 落到下面的通用"密码错误"会让被停用的人一直以为记错密码(与 deactivated 同理)。
    try:
        if resp.json().get("errcode") == "M_USER_LOCKED":
            return 403, {
                "error": "该账号已被停用，请联系管理员",
                "errcode": "M_USER_DEACTIVATED",  # 前端已有停用文案处理,复用同一 errcode
            }
    except ValueError:
        pass
    # 401/403 等 → 凭据错。但**先分辨"账号已停用"**:停用会抹掉密码→登录必然 403,若还回
    # "用户名或密码错误",被停用的人会一直以为是自己记错密码(负责人要求明确提示、去找管理员)。
    # 仅停用时给专门文案;正常账号密码错/账号不存在仍回通用文案(不泄露账号是否存在)。
    if server_name:
        try:
            if query_user_deactivated(hs_url, f"@{username}:{server_name}"):
                return 403, {
                    "error": "该账号已被停用，请联系管理员",
                    "errcode": "M_USER_DEACTIVATED",
                }
        except Exception:
            logger.debug("登录失败后查停用状态出错(忽略,回退通用文案)", exc_info=True)
    return 403, {"error": "用户名或密码错误"}


# ── 单端在线（后踢前）────────────────────────────────────────────
# 负责人拍板：同一账号跨浏览器登录时后登录的踢掉先登录的（多端并发存活不符合产品预期）。
# 实现：登录成功后用**这次刚验证过的密码**走 Synapse 的 UIA(user-interactive auth)
# 删掉该账号的其它 devices——旧端 token 立即失效，sync 收到 M_UNKNOWN_TOKEN 后由前端
# 提示"账号已在别处登录"。不需要 admin 权限、不改 Synapse。
#
# 被踢记录存**内存**（单实例够用，与验证码同口径）：前端 token 失效时来查"我是不是被顶
# 号了"，据此把提示从笼统的"登录已失效"换成明确的"账号已在别处登录"。重启丢记录只是
# 提示退化成笼统文案，不影响互斥本身。
_kicked_devices: Dict[Tuple[str, str], float] = {}   # (user_id, device_id) -> 被踢时刻
_kicked_lock = threading.Lock()
_KICKED_TTL = 24 * 3600      # 记录保留 24h：被踢端通常几秒内就会来查，24h 绰绰有余


def _single_session_enabled() -> bool:
    """单端在线(后登录踢先登录)开关。**默认关 = 多设备可同时在线**(标准 Matrix 行为,
    负责人 2026-07-25 拍板改回多设备)。置 COSMAC_SINGLE_SESSION=1 才启用"后踢前"互踢。"""
    return (_env("SINGLE_SESSION", "") or "").lower() in ("1", "true", "yes")


def _kick_other_devices(hs_url: str, username: str, password: str,
                        payload: Dict[str, Any]) -> None:
    """登录成功后踢掉该账号的**其它**设备（单端在线）。best-effort：任何一步失败都只记
    日志、绝不影响本次登录返回——互斥是产品体验，不能因为它把正常登录搞挂。

    payload = Synapse 登录响应（含 access_token / device_id / user_id）。
    删设备走两步 UIA：先裸 POST 拿 session，再带 m.login.password + session 提交。
    """
    token = str(payload.get("access_token") or "")
    new_dev = str(payload.get("device_id") or "")
    user_id = str(payload.get("user_id") or "")
    if not token or not new_dev or not user_id:
        return
    base = hs_url.rstrip("/")
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = requests.get(f"{base}/_matrix/client/v3/devices",
                         headers=headers, timeout=_HS_TIMEOUT)
        if r.status_code != 200:
            return
        others = [
            str(d.get("device_id"))
            for d in (r.json().get("devices") or [])
            if d.get("device_id") and d.get("device_id") != new_dev
        ]
        if not others:
            return
        # UIA 第一步：裸提交换 session（Synapse 固定回 401 + session/flows）
        r1 = requests.post(f"{base}/_matrix/client/v3/delete_devices",
                           json={"devices": others}, headers=headers,
                           timeout=_HS_TIMEOUT)
        auth: Dict[str, Any] = {
            "type": "m.login.password",
            "identifier": {"type": "m.id.user", "user": username},
            "password": password,
        }
        if r1.status_code == 401:
            sess = str((r1.json() or {}).get("session") or "")
            if sess:
                auth["session"] = sess
        elif r1.status_code == 200:
            # 个别部署对 appservice/关闭 UIA 的场景一步就成——直接记录返回
            _record_kicked(user_id, others)
            return
        # UIA 第二步：带密码提交真删
        r2 = requests.post(f"{base}/_matrix/client/v3/delete_devices",
                           json={"devices": others, "auth": auth}, headers=headers,
                           timeout=_HS_TIMEOUT)
        if r2.status_code == 200:
            _record_kicked(user_id, others)
            logger.info("单端在线：%s 登录，踢掉旧设备 %d 台", user_id, len(others))
        else:
            logger.warning("单端在线：删旧设备失败 status=%s user=%s",
                           r2.status_code, user_id)
    except requests.RequestException:
        logger.debug("单端在线：踢旧设备网络失败（忽略，不影响登录）", exc_info=True)


def _record_kicked(user_id: str, device_ids: list) -> None:
    """记录"这些设备是被顶号踢掉的"，供前端失效时查询换专属提示。"""
    now = time.time()
    with _kicked_lock:
        for d in device_ids:
            _kicked_devices[(user_id, d)] = now
        # 惰性清理：过期条目 + 容量兜底（防长期运行膨胀）
        if len(_kicked_devices) > 5000:
            for k in [k for k, t in _kicked_devices.items() if now - t > _KICKED_TTL]:
                _kicked_devices.pop(k, None)


def was_kicked(user_id: str, device_id: str) -> bool:
    """该 (账号, 设备) 是否是最近被"别处登录"踢掉的。给 /cosmac/session/kicked 查询用。"""
    if not user_id or not device_id:
        return False
    with _kicked_lock:
        ts = _kicked_devices.get((user_id, device_id))
        if ts is None:
            return False
        if time.time() - ts > _KICKED_TTL:
            _kicked_devices.pop((user_id, device_id), None)
            return False
        return True


def login_account(
    username: str, password: str, *, hs_url: str, client_ip: str = "",
    code: str = "", server_name: str = "",
) -> Tuple[int, Dict[str, Any]]:
    """账号（用户名+密码）登录**收口到后端**：限频 + 代理 Synapse 登录 + 记审计。

    为什么收口：原来前端直连 Synapse `/_matrix/client/v3/login`，后端看不到登录事件——
    IP 限频、异地检测、审计全都插不进。收口后账号登录也经这里，与邮箱登录同一道防线。
    成功原样返回 Synapse 登录响应（access_token/user_id/device_id），前端据此存会话。
    失败回通用「用户名或密码错误」，不泄露账号是否存在。
    """
    username = (username or "").strip().lower()
    if not username or not password:
        return 403, {"error": "用户名或密码错误"}
    # 在线撞库限频（收口的直接收益：账号登录现在也受这层保护）。
    if not _ip_rate_ok("attempt", client_ip, _IP_ATTEMPT_MAX, _IP_ATTEMPT_WINDOW):
        _audit("login", subject=username, ip=client_ip, ok=False, detail="rate_limited")
        return 429, {"error": "尝试过于频繁，请稍后再试"}
    # 第二步(带码回来):先验码——通过=确实持有绑定邮箱,再走 Synapse 登录。
    # 验码在登录前:码是一次性的,若先登录后验码,码错还得撤 token,顺序反而复杂。
    email = _email_for_login(username)
    if code and email:
        ok2, msg = _check_code(email, code, purpose="login")
        if not ok2:
            _audit("login", subject=username, ip=client_ip, ok=False, detail="stepup_bad_code")
            return 403, {"error": msg}
    st, payload = _proxy_synapse_login(hs_url, username, password, client_ip, server_name)
    if st != 200:
        deact = payload.get("errcode") == "M_USER_DEACTIVATED"
        _audit("login", subject=username, ip=client_ip, ok=False,
               detail="deactivated" if deact else
               {403: "bad_credentials", 429: "hs_rate_limited"}.get(st, "hs_error"))
        return st, payload
    # 密码对了 → 异地二次验证闸(阶段2):可疑且未带码 → 撤 token、发码、要求验证。
    gate = _stepup_gate(username, email, code, hs_url=hs_url, client_ip=client_ip,
                        token=str(payload.get("access_token") or ""))
    if gate is not None:
        return gate
    # 单端在线（后踢前）：仅在显式开启时才踢——默认多设备同时在线(负责人拍板)。
    # 放在 stepup 闸之后——可疑登录还没过二次验证时绝不能把人家正常在用的会话踢下线。
    if _single_session_enabled():
        _kick_other_devices(hs_url, username, password, payload)
    _audit("login", subject=username, ip=client_ip, ok=True,
           detail="ok_stepup" if code else "ok")
    return 200, payload


def login_email(
    email: str, password: str, *, hs_url: str, client_ip: str = "",
    code: str = "", server_name: str = "",
) -> Tuple[int, Dict[str, Any]]:
    """邮箱+密码登录：按邮箱反查用户名 → 用账号密码登 Synapse → 原样返回 Synapse 登录响应
    （含 access_token/user_id/device_id，前端据此存会话）。

    失败一律回通用「邮箱或密码错误」——不区分"邮箱没注册"和"密码错"，避免邮箱枚举。
    只对**注册时存过邮箱映射**的账号有效（老账号没存→当作邮箱或密码错误）。
    """
    email = (email or "").strip().lower()
    if not _EMAIL_RE.match(email) or not password:
        return 403, {"error": "邮箱或密码错误"}
    # 限在线撞库（请求经 bot 转发，Synapse 看到的是同一源 IP，这层得自己挡）。
    if not _ip_rate_ok("attempt", client_ip, _IP_ATTEMPT_MAX, _IP_ATTEMPT_WINDOW):
        _audit("login", subject=email, ip=client_ip, ok=False, detail="rate_limited")
        return 429, {"error": "尝试过于频繁，请稍后再试"}
    username = _lookup_username(email)
    if not username:
        _audit("login", subject=email, ip=client_ip, ok=False, detail="unknown_email")
        return 403, {"error": "邮箱或密码错误"}
    # 第二步(带码回来):先验码再登录(与 login_account 同序)。
    if code:
        ok2, msg = _check_code(email, code, purpose="login")
        if not ok2:
            _audit("login", subject=username, ip=client_ip, ok=False, detail="stepup_bad_code")
            return 403, {"error": msg}
    st, payload = _proxy_synapse_login(hs_url, username, password, client_ip, server_name)
    # 审计 subject 统一用 username(localpart):邮箱登录与账号登录归到同一主体,recent_success_ips
    # 按 username 聚合、异地检测不会把同一人当三个主体(审查证伪C的小瑕疵①)。
    if st == 200:
        # 异地二次验证闸(阶段2):邮箱登录场景邮箱已知,直接用。
        gate = _stepup_gate(username, email, code, hs_url=hs_url, client_ip=client_ip,
                            token=str(payload.get("access_token") or ""))
        if gate is not None:
            return gate
        # 单端在线（后踢前）：仅显式开启才踢，默认多设备（与 login_account 同一道）。
        if _single_session_enabled():
            _kick_other_devices(hs_url, username, password, payload)
        _audit("login", subject=username, ip=client_ip, ok=True,
               detail="ok_email_stepup" if code else "ok_email")
        return 200, payload
    if st == 429:
        _audit("login", subject=username, ip=client_ip, ok=False, detail="hs_rate_limited")
        return 429, {"error": "尝试过于频繁，请稍后再试"}
    if st == 502:
        _audit("login", subject=username, ip=client_ip, ok=False, detail="hs_error")
        return 502, payload
    # 账号已停用 → 保留专门文案(别被下面通用"邮箱或密码错误"盖掉),让用户知道去找管理员。
    if payload.get("errcode") == "M_USER_DEACTIVATED":
        _audit("login", subject=username, ip=client_ip, ok=False, detail="deactivated")
        return st, payload
    _audit("login", subject=username, ip=client_ip, ok=False, detail="bad_credentials")
    return 403, {"error": "邮箱或密码错误"}


def _admin_reset_password(hs_url: str, user_id: str, new_password: str) -> Tuple[int, Dict[str, Any]]:
    """用管理员令牌调 Synapse 重置某账号密码（并登出其所有设备）。

    /_synapse/admin/v1/reset_password/<user_id>：需**服务器管理员** access token
    （env COSMAC_ADMIN_TOKEN）。as_token 权限不够，故单独配一个管理员令牌。
    """
    token = _env("ADMIN_TOKEN")
    if not token:
        return 503, {"error": "服务器未配置管理员令牌"}
    from urllib.parse import quote
    base = hs_url.rstrip("/")
    # user_id 进 URL 路径要编码（纵深防御——localpart 已过白名单正则,此处防未来改动引入注入面）
    url = f"{base}/_synapse/admin/v1/reset_password/{quote(user_id, safe='')}"
    try:
        rr = requests.post(
            url,
            json={"new_password": new_password, "logout_devices": True},
            headers={"Authorization": f"Bearer {token}"},
            timeout=_HS_TIMEOUT,
        )
        if rr.status_code == 200:
            return 200, {"ok": True}
        logger.warning("重置密码失败 %s: %s", rr.status_code, rr.text[:200])
        return (rr.status_code if rr.status_code >= 400 else 502), {"error": "重置失败，请稍后重试"}
    except requests.RequestException:
        logger.exception("调用 Synapse 重置密码失败")
        return 502, {"error": "重置服务暂不可用，请稍后重试"}


def make_room_admin(hs_url: str, room_id: str, user_id: str) -> Tuple[int, Dict[str, Any]]:
    """用服务器管理员令牌把 user_id 提成某房间的管理员(power=100)。

    /_synapse/admin/v1/rooms/<room_id>/make_room_admin —— Synapse 管理 API,借房间内已有的
    本地房间管理员(通常是频道创建者)把目标用户提权并拉进房。给"平台管理员接管任意频道去改
    配置/技能"用(bug14:服务器管理员≠房间管理员,默认在别人建的频道里 power=0、写不了 state)。
    需 COSMAC_ADMIN_TOKEN(同 _admin_reset_password)。
    """
    token = _env("ADMIN_TOKEN")
    if not token:
        return 503, {"error": "服务器未配置管理员令牌"}
    from urllib.parse import quote
    base = hs_url.rstrip("/")
    url = f"{base}/_synapse/admin/v1/rooms/{quote(room_id, safe='')}/make_room_admin"
    try:
        rr = requests.post(
            url,
            json={"user_id": user_id},
            headers={"Authorization": f"Bearer {token}"},
            timeout=_HS_TIMEOUT,
        )
        if rr.status_code == 200:
            return 200, {"ok": True}
        logger.warning("make_room_admin 失败 %s: %s", rr.status_code, rr.text[:200])
        return (rr.status_code if rr.status_code >= 400 else 502), {
            "error": "接管频道失败（该频道可能没有本地管理员）"
        }
    except requests.RequestException:
        logger.exception("调用 make_room_admin 失败")
        return 502, {"error": "接管频道服务暂不可用，请稍后重试"}


def query_user_deactivated(hs_url: str, user_id: str) -> Optional[bool]:
    """查某账号是否已被**停用**（deactivated）。返回 True=已停用 / False=正常或不存在 / None=查不了。

    用 Synapse 管理 API `GET /_synapse/admin/v2/users/<user_id>`（需服务器管理员令牌
    COSMAC_ADMIN_TOKEN）。给登录失败时分辨"密码错" vs "账号已停用"用——停用会抹掉密码,
    登录必然 403,不查一下就只能回笼统的"用户名或密码错误",被停用的人一直以为是自己记错密码。
    任何异常/无令牌都回 None（调用方据此回退通用文案,绝不因这步把登录搞崩）。
    """
    token = _env("ADMIN_TOKEN")
    if not token or not user_id:
        return None
    from urllib.parse import quote
    base = hs_url.rstrip("/")
    url = f"{base}/_synapse/admin/v2/users/{quote(user_id, safe='')}"
    try:
        rr = requests.get(
            url, headers={"Authorization": f"Bearer {token}"}, timeout=_HS_TIMEOUT
        )
    except requests.RequestException:
        logger.debug("查账号停用状态请求异常", exc_info=True)
        return None
    if rr.status_code == 200:
        try:
            # deactivated=旧版注销;locked=新版停用(锁定)。对"停用检测"两者等价:都登不进来。
            j = rr.json()
            return bool(j.get("deactivated") or j.get("locked"))
        except Exception:
            return None
    if rr.status_code == 404:
        return False  # 账号不存在：当作"未停用"，回退通用文案（不泄露"账号不存在"）
    logger.debug("查账号停用状态返回 %s", rr.status_code)
    return None


def list_deactivated_user_ids(
    hs_url: str, *, page_limit: int = 200, max_pages: int = 25
) -> Optional[set]:
    """列出本服务器**所有已停用**账号的 user_id 集合。返回 set / None(查不了)。

    给能力名册过滤用——主 AI 派单不该派给已停用的人(任务落到登不进来的账号上,谁也干不了)。
    分页拉 Synapse 管理 API `GET /_synapse/admin/v2/users?deactivated=true`(该参数=**包含**停用者,
    再按每条的 deactivated 字段挑出停用的)。需管理员令牌 COSMAC_ADMIN_TOKEN。
    **fail-open**：无令牌/任何异常/某页非 200 一律回 None——调用方据此**不过滤**(宁可多列一个停用者,
    也不能因一次查询抖动把整份名册清空、让 AI "没人可派")。max_pages 兜底防超大部署下无限翻页。
    """
    token = _env("ADMIN_TOKEN")
    if not token:
        return None
    base = hs_url.rstrip("/")
    out: set = set()
    frm: Any = 0
    try:
        for _ in range(max_pages):
            url = (
                # locked=true 必带:Synapse 默认排除 locked 用户,而本产品「停用」=lock。
                # 漏了它 → 锁定账号不在结果里 → 名册不过滤 → AI 把任务派给登不进来的人。
                f"{base}/_synapse/admin/v2/users"
                f"?from={frm}&limit={page_limit}&guests=false"
                f"&deactivated=true&locked=true"
            )
            rr = requests.get(
                url, headers={"Authorization": f"Bearer {token}"}, timeout=_HS_TIMEOUT
            )
            if rr.status_code != 200:
                logger.debug("列停用用户返回 %s", rr.status_code)
                return None
            data = rr.json()
            for u in data.get("users") or []:
                # 锁定(locked=新版停用,数据保留)与注销(deactivated=旧版)都算"停用":
                # 两者都登不进来,主 AI 都不该派单给他们。
                if (u.get("deactivated") or u.get("locked")) and u.get("name"):
                    out.add(str(u["name"]))
            nxt = data.get("next_token")
            if nxt is None:  # 没有下一页了
                return out
            frm = nxt
        logger.debug("列停用用户翻页达上限 %s,可能不完整", max_pages)
        return out
    except requests.RequestException:
        logger.debug("列停用用户请求异常", exc_info=True)
        return None
    except Exception:
        logger.debug("解析停用用户列表失败", exc_info=True)
        return None


def get_user_media_bytes(hs_url: str, user_id: str) -> Optional[int]:
    """查某用户在 Synapse 媒体库的总字节数(上传的附件/图片/视频…)。查不了返回 None。

    用管理 API `GET /_synapse/admin/v1/statistics/users/media?search_term=<uid>`(需 ADMIN_TOKEN),
    精确匹配 user_id 取 media_length。给「存储空间配额」用——上传路径是客户端直连 Synapse,
    bot 不在上传链路上,只能事后核算;查不到(未配令牌/网络错)回 None,调用方按 0 处理(不误拦)。
    """
    token = _env("ADMIN_TOKEN")
    if not token:
        return None
    base = hs_url.rstrip("/")
    from urllib.parse import quote
    url = (
        f"{base}/_synapse/admin/v1/statistics/users/media"
        f"?search_term={quote(user_id)}&limit=10"
    )
    try:
        rr = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=_HS_TIMEOUT)
        if rr.status_code != 200:
            logger.debug("查用户媒体统计返回 %s", rr.status_code)
            return None
        for u in (rr.json().get("users") or []):
            if u.get("user_id") == user_id:
                return int(u.get("media_length") or 0)
        return 0  # 没上传过任何媒体
    except Exception:
        logger.debug("查用户媒体统计失败", exc_info=True)
        return None


def reset_request_code(
    email: str, *, client_ip: str = "", turnstile: str = ""
) -> Tuple[int, Dict[str, Any]]:
    """找回密码：发验证码到邮箱。turnstile=前端人机验证令牌。

    防邮箱枚举：无论该邮箱是否注册都返回成功，只有**确实注册过**才真正发信。
    """
    if not reset_enabled():
        return 503, {"error": "服务器未开启密码找回"}
    email = (email or "").strip().lower()
    if not _EMAIL_RE.match(email):
        return 400, {"error": "邮箱格式不正确"}
    # IP 限频在查邮箱是否注册之前——返回 429 不泄露邮箱是否存在。
    # 限频/邮箱校验都在 _verify_turnstile 之前:假 token 请求先被限频挡下,不空耗 Cloudflare 调用(中④)。
    if not _ip_rate_ok("send", client_ip, _IP_SEND_MAX, _IP_SEND_WINDOW):
        return 429, {"error": "请求过于频繁，请稍后再试"}
    if not _verify_turnstile(turnstile, client_ip):
        return 400, {"error": "人机验证未通过，请重试"}
    if not _lookup_username(email):
        # 不泄露"该邮箱有没有注册"，不发信但照样回成功
        return 200, {"ok": True, "cooldown": _RESEND_COOLDOWN}
    return _issue_code(_key("reset", email), lambda c: _send_reset_email(email, c))


def reset_verify(
    email: str, code: str, new_password: str, *, hs_url: str, server_name: str,
    client_ip: str = "",
) -> Tuple[int, Dict[str, Any]]:
    """找回密码：验码 → 重置该邮箱对应账号的密码。成功返回 (200, {ok})。"""
    if not reset_enabled():
        return 503, {"error": "服务器未开启密码找回"}
    email = (email or "").strip().lower()
    if not _EMAIL_RE.match(email):
        return 400, {"error": "邮箱格式不正确"}
    # 只做纯计算规则（不带"含用户名"检查）——那需要查 DB 反查用户名，而此处在 IP 限频
    # **之前**，不能给未限频的请求开 DB 查询面；重置场景该规则价值也低（攻击者拿不到验证码）。
    weak = password_problem(new_password)
    if weak:
        return 400, {"error": weak}
    # 重置码爆破比注册更危险（成功即账号接管）——同样按 IP 限尝试。
    if not _ip_rate_ok("attempt", client_ip, _IP_ATTEMPT_MAX, _IP_ATTEMPT_WINDOW):
        return 429, {"error": "尝试过于频繁，请稍后再试"}

    ok, msg = _check_code(email, code, purpose="reset")
    if not ok:
        return 400, {"error": msg}

    username = _lookup_username(email)
    if not username:
        return 400, {"error": "该邮箱未注册"}
    user_id = f"@{username}:{server_name}"
    st, payload = _admin_reset_password(hs_url, user_id, new_password)
    _audit("reset", subject=email, ip=client_ip, ok=(st == 200),
           detail="ok" if st == 200 else f"hs_{st}")
    return st, payload
