"""GuDuu Nexus HTTP 服务（fleet 端点）。

技术选型与 cosmac bot 保持一致：标准库 ThreadingHTTPServer + 同步逻辑，
不引入 Web 框架——单人维护，栈越少越好。

端点总览：
    公开（实例回连，凭 KEY 鉴权）：
        GET  /nexus/health                       探活
        POST /nexus/redeem     {key,domain,admin_email,region}  兑换开通（install.sh 调）
        POST /nexus/heartbeat  {key,version,stats}        心跳上报（实例定时调）
        GET  /nexus/referral?code=...                    公开校验 OEM 分享码
        GET  /nexus/oem/auth/config                       OEM 邮箱验证能力开关
        POST /nexus/oem/email/request-code                发送注册/登录/重置验证码
        POST /nexus/oem/login/code                        使用邮箱验证码登录
        POST /nexus/oem/password/reset                    使用邮箱验证码重置密码
        POST /nexus/user/attribution {key,referral_code,user_id} 用户归属上报
        POST /nexus/update/check   {key,current_version}  拉取已分配的版本更新
        POST /nexus/update/report  {key,release_id,status,...} 上报更新结果
        POST /nexus/release/manifest  CI 用独立 HMAC 登记不可变镜像摘要
    管理（console 用，须具名管理员会话；SSH 单次码仅用于首次建号和恢复）：
        POST /nexus/admin/keys       {count,note,token_grant}  签发 KEY（明文仅此一次）
        POST /nexus/admin/revoke     {key_id}                  吊销 KEY
        GET  /nexus/admin/keys                                 KEY 列表
        GET  /nexus/admin/instances                            实例列表（含余额）
        POST /nexus/admin/instance_member_policy               逐节点终身会员审批策略
        POST /nexus/admin/topup      {instance_id,tokens,note} 手动充值
        GET  /nexus/admin/finance_summary                      资金经营汇总
        GET  /nexus/admin/finance_ledger                       节点充值财务清单
        GET  /nexus/admin/payment_configs                      支付配置字段与验证状态
        POST /nexus/admin/payment_config {provider,config|action} 加密保存/重新验证
        GET/POST /nexus/admin/features                         OEM 功能可见性开关
        GET  /nexus/admin/hierarchy                            OEM/用户完整归属边
        GET/POST /nexus/admin/releases                         版本发布中心
        GET  /nexus/admin/release_draft                        从 DEVLOG 自动生成版本草稿
        POST /nexus/admin/release_action                       灰度/全量/回撤/暂停/重试
    OEM 门户（须 OEM 会话，且所有数据按当前企业服务端隔离）：
        GET  /nexus/oem/me                                  自有实例/KEY/订单等总览
        GET  /nexus/oem/instance                            自有单节点的完整运行快照
        GET  /nexus/oem/network                             自己的下级 OEM 与归属用户清单

安全：
    - 具名管理员账号保存在 Nexus DB；浏览器会话走安全 Cookie，可撤销且 12 小时过期；
    - 忘记密码时必须 SSH 运行 ``python -m nexus.recovery_codes``；单次码
      只换取 30 分钟恢复 Cookie，网页不接受长期管理令牌；
    - 兑换端点按 IP 限频（内存桶），防 KEY 爆破；
    - 生产部署躲在 Caddy 后面收 TLS，本服务只听内网。
"""

from __future__ import annotations

import hmac
import ipaddress
import io
import json
import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, quote, urlsplit

from nexus import (
    admin_auth,
    audit,
    db,
    entitlements,
    features,
    fleet,
    geo,
    manual_transfer,
    member_policy,
    oem as oem_svc,
    oem_email,
    oem_finance,
    pay,
    passkeys,
    payment_config,
    release_artifacts,
    release_policy,
    releases,
    turnstile,
)
from nexus.fleet import FleetError

logger = logging.getLogger("nexus.service")

# ---------- 内存限频桶（单实例部署够用；多实例部署时换 Redis，P2 再说）----------
_BUCKET_LOCK = threading.Lock()
_BUCKET: Dict[str, list] = {}
_REDEEM_MAX_PER_HOUR = 10
# OEM 注册/登录：按 IP 每小时 30 次（防账号枚举/密码爆破，正常人用不到这么多）
_AUTH_MAX_PER_HOUR = 30


def _rate_ok(ip: str) -> bool:
    """同一 IP 每小时最多 10 次兑换尝试（成功失败都计）。"""
    now = time.time()
    with _BUCKET_LOCK:
        window = [t for t in _BUCKET.get(ip, []) if now - t < 3600]
        if len(window) >= _REDEEM_MAX_PER_HOUR:
            _BUCKET[ip] = window
            return False
        window.append(now)
        _BUCKET[ip] = window
        return True


def _auth_rate_ok(ip: str) -> bool:
    """OEM 注册/登录限频（独立桶，key 前缀 auth: 与兑换桶隔开）。"""
    now = time.time()
    key = "auth:" + ip
    with _BUCKET_LOCK:
        window = [t for t in _BUCKET.get(key, []) if now - t < 3600]
        if len(window) >= _AUTH_MAX_PER_HOUR:
            _BUCKET[key] = window
            return False
        window.append(now)
        _BUCKET[key] = window
        return True


def _dash_token() -> str:
    """读取只读大屏令牌。

    独立函数让大屏鉴权与管理员鉴权保持清晰边界，禁止将管理
    会话或 SSH 恢复凭据复用到长时间展示的大屏页面。
    """
    return os.environ.get("NEXUS_DASH_TOKEN", "").strip()


class NexusHandler(BaseHTTPRequestHandler):
    """所有 /nexus/（fleet）与 /gw/（LLM 网关）端点的处理器。

    一请求一 DB Session，出错整体回滚；网关走 gateway.handle_post（内部
    自管短连 Session——LLM 转发耗时长，不能套在这里的会话包装里）。
    """

    server_version = "GuDuuNexus/0.1"
    # HTTP/1.1：网关流式回传要用 chunked 编码（HTTP/1.0 不支持）。
    # 代价是所有响应必须带 Content-Length 或 chunked——本文件的 _json/_err
    # 都带 Content-Length，勿新增裸响应。
    protocol_version = "HTTP/1.1"

    # ---- 基础工具 ----

    def _json(self, status: int, payload: Dict[str, Any]) -> None:
        # Session 包装会据此判断管理写操作是否真正成功，再追加全局审计事件。
        self._last_response_status = int(status)
        if getattr(self, "_defer_json_response", False):
            # 数据库事务内先暂存响应；只有 commit 成功后才真正写入 socket，避免浏览器
            # 收到成功后立即发起下一请求，却仍读到尚未提交的旧状态。
            self._pending_json_response = (int(status), payload)
            return
        self._send_json(status, payload)

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        """立即发送 JSON；事务包装之外以及 commit 完成后使用。"""
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # API 响应可能包含会话令牌、余额等敏感数据，任何层级都不应缓存。
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for cookie in getattr(self, "_pending_set_cookies", []):
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def _err(self, status: int, code: str, msg: str) -> None:
        self._json(status, {"errcode": code, "error": msg})

    def _read_body(self) -> Dict[str, Any]:
        try:
            n = min(int(self.headers.get("Content-Length") or 0), 64 * 1024)
            raw = self.rfile.read(n) if n else b"{}"
            data = json.loads(raw.decode("utf-8") or "{}")
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _read_large_json(self, max_bytes: int) -> Optional[Dict[str, Any]]:
        """读取受控的大 JSON 请求，专供 Base64 图片上传接口。

        普通管理接口仍限制 64KB；只有凭证上传明确放宽到约 11MB（8MB 图片经 Base64
        膨胀后），避免无意中把整个服务的请求体上限一起放大。失败时本函数已经发送
        HTTP 错误，调用者收到 ``None`` 后必须立即返回。
        """
        try:
            size = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            size = 0
        if size <= 0 or size > int(max_bytes):
            self._err(
                413,
                "NEXUS_TRANSFER_BODY_TOO_BIG",
                "转账凭证请求为空或超过大小限制",
            )
            return None
        try:
            payload = json.loads(self.rfile.read(size).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._err(400, "NEXUS_BAD_JSON", "请求内容不是有效 JSON")
            return None
        if not isinstance(payload, dict):
            self._err(400, "NEXUS_BAD_JSON", "请求内容必须是对象")
            return None
        return payload

    def _client_ip(self) -> str:
        """返回可用于限流、审计与 KEY IP 绑定的可信来源地址。

        Nexus 只监听本机，由宿主 Caddy 在确认 Cloudflare 来源后把解析结果覆盖写入
        ``X-Nexus-Client-IP``。项目专属头避免 Caddy 2.6 对常见
        ``X-Real-IP`` 的内置代理处理。这里绝不直接读取客户端
        可伪造的 ``X-Forwarded-For``；只有 TCP 对端确为 loopback 时
        才接收 Caddy 写入的单值专属头。开发直连同样会
        安全地回退到对端地址，避免测试环境必须伪造反代头。
        """
        peer = self.client_address[0] if self.client_address else ""
        try:
            peer_is_loopback = bool(peer) and ipaddress.ip_address(peer).is_loopback
        except ValueError:
            peer_is_loopback = False
        if peer_is_loopback:
            supplied = (
                self.headers.get("X-Nexus-Client-IP")
                or self.headers.get("X-Real-IP")
                or ""
            ).strip()
            try:
                # 只接受一个规范 IP，拒绝逗号链和任意文本，确保审计/绑定口径稳定。
                return str(ipaddress.ip_address(supplied)) if supplied else peer
            except ValueError:
                pass
        return peer or "?"

    def _admin_permission(self) -> str:
        """把管理 API 归到稳定职责域，未知接口默认落入最高敏感的安全域。"""
        path = self.path.split("?", 1)[0]
        method = self.command.upper()
        write = method not in ("GET", "HEAD", "OPTIONS")
        if path in (
            "/nexus/admin/me",
            "/nexus/admin/passkeys",
            "/nexus/admin/auth/logout",
            "/nexus/admin/passkey/register/options",
            "/nexus/admin/passkey/register/verify",
            "/nexus/admin/passkey/delete",
        ):
            return ""
        if path == "/nexus/admin/audit":
            return "audit.read"
        if path in (
            "/nexus/admin/orders",
            "/nexus/admin/withdrawals",
            "/nexus/admin/finance_summary",
            "/nexus/admin/finance_ledger",
            "/nexus/admin/payment_configs",
            "/nexus/admin/pricing",
            "/nexus/admin/oem_commercial_terms",
            "/nexus/admin/manual_transfer/recognize",
            "/nexus/admin/manual_transfers",
            "/nexus/admin/topup_transfer_decide",
            "/nexus/admin/withdrawal_decide",
            "/nexus/admin/payment_config",
            "/nexus/admin/token_purchase_requests",
            "/nexus/admin/token_purchase_decide",
        ) or path.startswith("/nexus/admin/manual_transfer_voucher/"):
            return "finance.write" if write else "finance.read"
        if path in (
            "/nexus/admin/releases",
            "/nexus/admin/release_draft",
            "/nexus/admin/release_policy",
            "/nexus/admin/release_action",
        ):
            return "release.write" if write else "release.read"
        if path in (
            "/nexus/admin/admins",
            "/nexus/admin/admin_status",
            "/nexus/admin/admin_password",
            "/nexus/admin/admin_role",
            "/nexus/admin/instance_member_policy",
        ):
            return "security.write" if write else "security.read"
        if path.startswith("/nexus/admin/"):
            return "operations.write" if write else "operations.read"
        return ""

    def _check_admin(self) -> bool:
        """只接受具名管理员会话或 SSH 单次码换取的短期恢复会话。

        每次成功鉴权都会把当前操作人写到 handler，后续业务审计直接使用真实姓名。
        服务端不再保留任何长期 HTTP 恢复凭据，避免泄露后成为永久后门。
        """
        bearer_token = self._bearer()
        cookie_token = self._cookie_value(self._admin_cookie_name())
        token = bearer_token or cookie_token
        s = db.session()
        try:
            account = admin_auth.resolve_session(s, token)
            if account is not None:
                self._admin_actor_id = int(account.id)
                self._admin_actor_label = account.display_name
                self._admin_role = getattr(account, "role", "superadmin")
                self._admin_auth_kind = (
                    "recovery_cookie"
                    if int(account.id) == 0
                    else (
                        "passkey_cookie"
                        if cookie_token.startswith("nxp_")
                        else ("named_cookie" if cookie_token else "named_session")
                    )
                )
                self._admin_session_token = token
                # Cookie 会由浏览器自动携带，因此所有管理写操作额外要求自定义请求头。
                # 跨站表单不能设置该头，配合 SameSite=Strict 形成双层 CSRF 防护。
                if (
                    cookie_token
                    and self.command == "POST"
                    and self.headers.get("X-Nexus-CSRF") != "1"
                ):
                    self._err(403, "NEXUS_CSRF", "管理请求缺少安全校验头")
                    return False
                permission = self._admin_permission()
                if not admin_auth.has_permission(self._admin_role, permission):
                    self._err(
                        403,
                        "NEXUS_ADMIN_PERMISSION_DENIED",
                        "当前管理员角色无权执行此操作",
                    )
                    return False
                return True
            has_named_admin = admin_auth.active_count(s) > 0
        finally:
            s.close()
        if not has_named_admin:
            self._err(
                503,
                "NEXUS_ADMIN_DISABLED",
                "请先从服务器 SSH 生成单次恢复码并创建首个管理员",
            )
        else:
            self._err(401, "NEXUS_FORBIDDEN", "管理员登录已失效")
        return False

    def _admin_actor(self) -> str:
        """返回当前管理员审计显示名；仅在 ``_check_admin`` 成功后调用。"""
        return str(getattr(self, "_admin_actor_label", "平台超级管理员"))

    @staticmethod
    def _admin_cookie_name() -> str:
        """生产使用 ``__Host-`` 前缀；本机 HTTP 浏览器测试可显式关闭 Secure。"""
        secure = os.environ.get("NEXUS_COOKIE_SECURE", "1").strip() != "0"
        return "__Host-NexusAdmin" if secure else "NexusAdminTest"

    def _cookie_value(self, name: str) -> str:
        """安全解析指定 Cookie；畸形请求按未携带处理。"""
        raw = self.headers.get("Cookie") or ""
        if not raw:
            return ""
        try:
            jar = SimpleCookie()
            jar.load(raw)
            item = jar.get(name)
            return item.value if item is not None else ""
        except Exception:
            return ""

    def _set_admin_cookie(self, token: str, max_age: Optional[int] = None) -> None:
        """下发 JavaScript 无法读取的管理员会话 Cookie。

        正常登录不设置 ``Max-Age``，关闭浏览器即清除；服务端仍执行 12 小时或
        30 分钟绝对过期。只有退出时传 0，让浏览器立即删除现有 Cookie。
        """
        secure = os.environ.get("NEXUS_COOKIE_SECURE", "1").strip() != "0"
        parts = [
            f"{self._admin_cookie_name()}={token}",
            "Path=/",
            "HttpOnly",
            "SameSite=Strict",
        ]
        if max_age is not None:
            parts.append(f"Max-Age={max(0, int(max_age))}")
        if secure:
            parts.append("Secure")
        self._pending_set_cookies.append("; ".join(parts))

    def _clear_admin_cookie(self) -> None:
        """退出时让浏览器立即删除管理员 Cookie。"""
        self._set_admin_cookie("", 0)

    def _reset_request_context(self) -> None:
        """清空同一 HTTP keep-alive 连接上一个请求留下的身份信息。

        ``BaseHTTPRequestHandler`` 会在同一 TCP 连接复用 handler；若不主动清理，先用
        恢复会话访问、再提交公开登录请求时，后一个请求可能被错误记成恢复管理员操作。
        """
        self._admin_actor_id = 0
        self._admin_actor_label = ""
        self._admin_auth_kind = ""
        self._admin_role = ""
        self._admin_session_token = ""
        self._last_response_status = 0
        self._pending_set_cookies = []
        self._defer_json_response = False
        self._pending_json_response = None

    def _bearer(self) -> str:
        """取 Authorization: Bearer <token> 里的 token（无则空串）。"""
        got = self.headers.get("Authorization") or ""
        return got[7:] if got.startswith("Bearer ") else ""

    def _oem(self, s):
        """解析 OEM 会话令牌 → OEM 账号。无效则回 401 并返回 None。

        供 /nexus/oem/* 端点在 _with_session 内调用（需要 Session 查会话表）。
        """
        oem = oem_svc.resolve_session(s, self._bearer())
        if oem is None:
            self._err(401, "NEXUS_FORBIDDEN", "请先登录")
            return None
        return oem

    def _check_dash(self) -> bool:
        """大屏端点只接受只读令牌 ``NEXUS_DASH_TOKEN``。

        管理令牌绝不能在大屏页面里使用：大屏展示的数据面更大、运行时间更长，一旦页面
        再出现 XSS，泄露管理员令牌会直接危及 KEY 与钱包。管理员进入大屏时先经受保护的
        兑换端点取得只读令牌，权限始终保持最小化。
        """
        got = self.headers.get("Authorization") or ""
        token = got[7:] if got.startswith("Bearer ") else ""
        dash = _dash_token()
        if dash and token and hmac.compare_digest(token, dash):
            return True
        if not dash:
            self._err(503, "NEXUS_DASH_DISABLED", "NEXUS_DASH_TOKEN 未配置")
        else:
            self._err(401, "NEXUS_FORBIDDEN", "大屏令牌无效")
        return False

    # 屏蔽默认的逐请求 stderr 日志，统一走 logging
    def log_message(self, fmt: str, *args: Any) -> None:
        logger.info("%s %s", self._client_ip(), fmt % args)

    def _public_origin(self) -> str:
        """根据反代头生成当前 Nexus 公网 origin，并拒绝异常 Host 注入分享链接。"""
        host = (
            self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or ""
        ).strip()
        host = host.split(",", 1)[0].strip()
        if not host or any(
            c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-:"
            for c in host
        ):
            raise FleetError("NEXUS_BAD_HOST", "请求 Host 不合法")
        forwarded = (
            (self.headers.get("X-Forwarded-Proto") or "").split(",", 1)[0].strip()
        )
        scheme = (
            forwarded
            if forwarded in ("http", "https")
            else ("http" if host.startswith(("127.0.0.1", "localhost")) else "https")
        )
        return f"{scheme}://{host}"

    def _request_host(self) -> str:
        """返回不含端口的小写请求主机名，用于管理域名的服务端边界判断。"""
        host = (
            (self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or "")
            .split(",", 1)[0]
            .strip()
            .lower()
        )
        # 当前生产只使用普通 DNS 主机名；测试里的 127.0.0.1:port 也可稳定去端口。
        return host.rsplit(":", 1)[0] if ":" in host else host

    @staticmethod
    def _admin_public_url() -> str:
        """读取独立管理站公开地址；留空代表兼容尚未迁移的单域名环境。"""
        return os.environ.get("NEXUS_ADMIN_PUBLIC_URL", "").strip().rstrip("/")

    def _is_admin_host(self) -> bool:
        """判断当前请求是否来自配置好的独立管理主机。"""
        public_url = self._admin_public_url()
        if not public_url:
            return True
        return self._request_host() == (urlsplit(public_url).hostname or "").lower()

    def _require_admin_host(self, path: str) -> bool:
        """启用独立域名后，阻止从 OEM 域名绕过 Cloudflare Access 调管理 API。"""
        if not path.startswith("/nexus/admin/") or self._is_admin_host():
            return True
        # 返回 404 而非暴露管理域名或鉴权状态，降低普通入口的信息泄露。
        self._err(404, "NEXUS_UNKNOWN", "未知端点")
        return False

    def _redirect(self, location: str) -> None:
        """发送不缓存的 302；用于两个控制台域名之间的安全入口分流。"""
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ---- 路由 ----

    def do_GET(self) -> None:  # noqa: N802  # http.server 命名约定
        self._reset_request_context()
        path = self.path.split("?", 1)[0]
        if not self._require_admin_host(path):
            return
        if path == "/nexus/health":
            self._json(200, {"ok": True, "ts": int(time.time() * 1000)})
            return
        if path == "/nexus/regions":
            # 安装器在兑换 KEY 之前也需要校验地域。字典不含客户数据或密钥，
            # 公开只读返回可避免安装脚本复制一份容易过期的地区列表。
            self._json(200, {"regions": geo.options()})
            return
        if path == "/nexus/referral":
            qs = parse_qs(urlsplit(self.path).query)
            code = str((qs.get("code") or [""])[0])
            self._with_session(
                lambda s: self._json(200, oem_svc.referral_info(s, code))
            )
            return
        if path == "/nexus/oem/auth/config":
            # 只返回公开 site key 与能力开关；SMTP、Turnstile secret 和预期域名都
            # 留在服务端，避免门户配置接口成为部署信息泄漏面。
            self._json(
                200,
                {
                    "email_verification": oem_email.enabled(),
                    "turnstile": turnstile.public_config(),
                },
            )
            return
        if path == "/nexus/admin/me":
            if self._check_admin():
                self._json(
                    200,
                    {
                        "admin": {
                            "id": int(getattr(self, "_admin_actor_id", 0)),
                            "display_name": self._admin_actor(),
                            "role": getattr(self, "_admin_role", "superadmin"),
                            "role_label": admin_auth.ADMIN_ROLES.get(
                                getattr(self, "_admin_role", "superadmin"),
                                getattr(self, "_admin_role", "superadmin"),
                            ),
                            "permissions": admin_auth.role_permissions(
                                getattr(self, "_admin_role", "superadmin")
                            ),
                            "auth_kind": getattr(
                                self, "_admin_auth_kind", "named_session"
                            ),
                        }
                    },
                )
            return
        if path == "/nexus/admin/passkeys":
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(
                        200,
                        {
                            "enabled": passkeys.enabled(),
                            "passkeys": (
                                passkeys.list_passkeys(
                                    s, int(getattr(self, "_admin_actor_id", 0))
                                )
                                if int(getattr(self, "_admin_actor_id", 0)) > 0
                                else []
                            ),
                        },
                    )
                )
            return
        if path == "/nexus/admin/admins":
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(200, {"admins": admin_auth.list_admins(s)})
                )
            return
        if path == "/nexus/admin/audit":
            if self._check_admin():
                qs = parse_qs(urlsplit(self.path).query)
                try:
                    limit = int((qs.get("limit") or ["200"])[0])
                except ValueError:
                    limit = 200
                object_type = str((qs.get("object_type") or [""])[0])
                actor = str((qs.get("actor") or [""])[0])
                self._with_session(
                    lambda s: self._json(
                        200,
                        {
                            "events": audit.recent(
                                s,
                                limit=limit,
                                object_type=object_type,
                                actor=actor,
                            )
                        },
                    )
                )
            return
        if path == "/nexus/admin/keys":
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(200, {"keys": fleet.list_keys(s)})
                )
            return
        if path == "/nexus/admin/regions":
            # 地域字典（console 下拉 + 大屏图例用）。静态数据，不查库。
            if self._check_admin():
                self._json(200, {"regions": geo.options()})
            return
        if path == "/nexus/admin/instances":
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(200, {"instances": fleet.list_instances(s)})
                )
            return
        if path == "/nexus/admin/releases":
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(200, {"releases": releases.list_releases(s)})
                )
            return
        if path == "/nexus/admin/release_draft":
            # 自动生成只做“读当前版本 + 读 DEVLOG + 回填”，不直接创建发布记录。
            # 超级管理员仍要在界面审阅后保存，避免提交代码时顺带误触全量发布流程。
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(200, releases.build_release_draft(s))
                )
            return
        if path == "/nexus/admin/oems":
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(200, {"oems": oem_svc.list_oems(s)})
                )
            return
        if path == "/nexus/admin/hierarchy":
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(200, oem_svc.hierarchy_snapshot(s))
                )
            return
        if path == "/nexus/admin/dashboard-token":
            # 管理员控制台只在用户进入大屏时兑换“只读”凭据。前端从此不会把具有
            # KEY/钱包写权限的管理员令牌传给大屏，避免一个展示层 XSS 升级成接管后台。
            if self._check_admin():
                token = _dash_token()
                if token:
                    # 管理页面位于独立子域名后，大屏必须跳回公开 Nexus 域名；否则
                    # Cloudflare Access 会把挂墙大屏也误保护，且相对链接会落错站点。
                    dashboard_url = os.environ.get(
                        "NEXUS_DASHBOARD_PUBLIC_URL", ""
                    ).strip()
                    payload = {"token": token}
                    if dashboard_url:
                        payload["url"] = dashboard_url
                    self._json(200, payload)
                else:
                    self._err(
                        503,
                        "NEXUS_DASH_DISABLED",
                        "NEXUS_DASH_TOKEN 未配置",
                    )
            return
        if path == "/nexus/dash/summary":
            if self._check_dash():
                def _dashboard_summary(s):
                    """合并舰队运行数据与真实资金口径供只读大屏使用。"""
                    payload = fleet.dash_summary(s)
                    # 复用超管舰队总览的已确认资金聚合，不能由前端自行拼演示金额。
                    payload["finance"] = pay.finance_summary(s)
                    return self._json(200, payload)

                self._with_session(_dashboard_summary)
            return
        # —— OEM 门户：登录后看自己的账号 + 实例 + KEY ——
        if path == "/nexus/oem/me":

            def _me(s):
                oem = self._oem(s)
                if oem is None:
                    return
                instances = oem_svc.my_instances(s, oem.id)
                feature_flags = features.get_flags(s)
                self._json(
                    200,
                    {
                        "oem": oem_svc.public_oem(oem),
                        "instances": instances,
                        "keys": oem_svc.my_keys(s, oem.id),
                        "requests": oem_svc.my_requests(s, oem.id),
                        "orders": pay.my_orders(s, oem.id),
                        "lifetime_requests": entitlements.my_lifetime_requests(
                            s, oem.id
                        ),
                        "token_purchase_requests": (
                            entitlements.my_token_purchase_requests(s, oem.id)
                        ),
                        # 只返回该 OEM 名下节点已经成功安装的版本；它与上方 instances
                        # 使用同一归属边，但在业务层再次强制过滤，避免依赖前端隐藏。
                        "announcements": releases.list_oem_announcements(s, oem.id),
                        # 分享码、注册链接和二维码始终保留；开关关闭时只裁掉层级、
                        # 人数与下属统计，不能把隐藏数据继续留在浏览器网络响应里。
                        "features": feature_flags,
                        "referral": (
                            oem_svc.share_summary(s, oem.id, self._public_origin())
                            if feature_flags["oem_network_visible"]
                            else oem_svc.share_links(s, oem.id, self._public_origin())
                        ),
                    },
                )

            self._with_session(_me)
            return
        if path == "/nexus/oem/network":

            def _network(s):
                """仅返回当前登录 OEM 自己的下属网络明细。"""
                account = self._oem(s)
                if account is None:
                    return
                features.require_oem_network_visible(s)
                self._json(200, oem_svc.network_directory(s, account.id))

            self._with_session(_network)
            return
        if path == "/nexus/oem/instance":

            def _oem_instance(s):
                """校验 OEM 会话与实例归属后，返回节点的真实运行快照。"""
                account = self._oem(s)
                if account is None:
                    return
                qs = parse_qs(urlsplit(self.path).query)
                try:
                    instance_id = int((qs.get("instance_id") or ["0"])[0])
                except ValueError:
                    instance_id = 0
                self._json(
                    200,
                    {
                        "instance": oem_svc.my_instance_detail(
                            s, account.id, instance_id
                        )
                    },
                )

            self._with_session(_oem_instance)
            return
        if path == "/nexus/oem/share_qr":

            def _share_qr(s):
                account = self._oem(s)
                if account is None:
                    return
                qs = parse_qs(urlsplit(self.path).query)
                kind = str((qs.get("kind") or [""])[0])
                try:
                    instance_id = int((qs.get("instance_id") or ["0"])[0])
                except ValueError:
                    instance_id = 0
                target = oem_svc.qr_target(
                    s, account.id, self._public_origin(), kind, instance_id
                )
                # SVG 不依赖 Pillow，适合 Nexus 轻量服务；二维码只编码服务端重算的合法链接。
                import qrcode
                import qrcode.image.svg

                image = qrcode.make(
                    target,
                    image_factory=qrcode.image.svg.SvgPathImage,
                    box_size=7,
                    border=3,
                )
                buffer = io.BytesIO()
                image.save(buffer)
                data = buffer.getvalue()
                self.send_response(200)
                self.send_header("Content-Type", "image/svg+xml")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "private, max-age=300")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(data)

            self._with_session(_share_qr)
            return
        # —— 商品与渠道（登录后查询：定价 + 各渠道可用性）——
        if path == "/nexus/oem/products":

            def _products(s):
                oem = self._oem(s)
                if oem is None:
                    return
                self._json(
                    200,
                    {"pricing": pay.public_pricing(s), "channels": pay.channels(s)},
                )

            self._with_session(_products)
            return
        if path == "/nexus/oem/finance":

            def _oem_finance(s):
                account = self._oem(s)
                if account is None:
                    return
                self._json(200, oem_finance.finance_snapshot(s, account.id))

            self._with_session(_oem_finance)
            return
        if path == "/nexus/admin/orders":
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(200, {"orders": pay.list_orders(s)})
                )
            return
        if path == "/nexus/admin/withdrawals":
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(
                        200,
                        {"withdrawals": oem_finance.list_admin_withdrawals(s)},
                    )
                )
            return
        if path == "/nexus/admin/finance_summary":
            # 资金汇总与订单列表分开：列表只取最近 200 单，汇总必须覆盖全部历史订单。
            # 国内与海外渠道都只返回布尔状态，不暴露任何支付凭据内容。
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(
                        200,
                        {
                            "finance": pay.finance_summary(s),
                            "channels": pay.channels(s),
                            "manual_transfer_ai": manual_transfer.ai_status(),
                        },
                    )
                )
            return
        if path == "/nexus/admin/finance_ledger":
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(
                        200, {"entries": pay.finance_ledger(s)}
                    )
                )
            return
        if path == "/nexus/admin/payment_configs":
            # 配置接口只返回字段是否已填写和验证摘要；密钥原文、密文、掩码均不出服务端。
            # callback URL 使用经 Host 白名单检查后的公网 origin，管理员可直接复制到平台。
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(
                        200,
                        {
                            "payment_configs": payment_config.list_public(
                                s, self._public_origin()
                            )
                        },
                    )
                )
            return
        if path == "/nexus/admin/pricing":
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(200, {"pricing": pay.get_pricing(s)})
                )
            return
        if path == "/nexus/admin/oem_commercial_terms":
            # 专属条款只展示给平台主管；OEM 只能在自己的收益页看到最终有效价格。
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(
                        200,
                        {"terms": oem_finance.list_commercial_terms(s)},
                    )
                )
            return
        if path == "/nexus/admin/features":
            # 只返回非敏感布尔开关；超管令牌仍由统一鉴权拦截。
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(200, {"features": features.get_flags(s)})
                )
            return

        if path == "/nexus/admin/release_policy":
            # 只返回节点编号和布尔策略，不包含 KEY、SSH 或镜像仓凭据。
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(
                        200, {"release_policy": release_policy.get_policy(s)}
                    )
                )
            return

        if path == "/nexus/admin/requests":
            if self._check_admin():
                qs = parse_qs(urlsplit(self.path).query)
                status = str((qs.get("status") or [""])[0])
                query = str((qs.get("q") or [""])[0])
                self._with_session(
                    lambda s: self._json(
                        200,
                        {
                            "requests": oem_svc.list_requests(
                                s, status=status, query=query
                            ),
                            "counts": oem_svc.request_counts(s),
                        },
                    )
                )
            return
        if path == "/nexus/admin/lifetime_requests":
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(
                        200,
                        {
                            "requests": entitlements.list_lifetime_requests(s)
                        },
                    )
                )
            return
        if path == "/nexus/admin/token_purchase_requests":
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(
                        200,
                        {
                            "requests": entitlements.list_token_purchase_requests(s)
                        },
                    )
                )
            return
        if path == "/nexus/admin/request_detail":
            if self._check_admin():
                qs = parse_qs(urlsplit(self.path).query)
                try:
                    request_id = int((qs.get("request_id") or ["0"])[0])
                except ValueError:
                    request_id = 0
                self._with_session(
                    lambda s: self._json(
                        200, {"request": oem_svc.request_detail(s, request_id)}
                    )
                )
            return
        # 客户档案详情：/nexus/admin/oem_detail?oem_id=N
        if path == "/nexus/admin/oem_detail":
            if self._check_admin():
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                oem_id = 0
                for kv in qs.split("&"):
                    if kv.startswith("oem_id="):
                        try:
                            oem_id = int(kv.split("=", 1)[1])
                        except ValueError:
                            pass
                self._with_session(
                    lambda s: self._json(200, oem_svc.oem_detail(s, oem_id))
                )
            return
        # 附件下载：/nexus/admin/oem_file/<file_id>
        if path.startswith("/nexus/admin/oem_file/"):
            if self._check_admin():
                try:
                    fid = int(path.rsplit("/", 1)[-1])
                except ValueError:
                    self._err(404, "NEXUS_FILE_NOT_FOUND", "附件不存在")
                    return

                def _dl(s):
                    row = oem_svc.get_oem_file(s, fid)
                    data = bytes(row.data)
                    self.send_response(200)
                    self.send_header("Content-Type", row.content_type)
                    self.send_header("Content-Length", str(len(data)))
                    # RFC 5987 filename*：中文文件名安全下载
                    self.send_header(
                        "Content-Disposition",
                        "attachment; filename*=UTF-8''" + quote(row.filename),
                    )
                    self.end_headers()
                    self.wfile.write(data)

                self._with_session(_dl)
            return
        # 企业转账凭证包含银行信息，只允许超管按记录 id 查看；响应禁止缓存。
        if path.startswith("/nexus/admin/manual_transfer_voucher/"):
            if self._check_admin():
                try:
                    transfer_id = int(path.rsplit("/", 1)[-1])
                except ValueError:
                    self._err(404, "NEXUS_TRANSFER_NOT_FOUND", "企业转账单不存在")
                    return

                def _transfer_voucher(s):
                    filename, content_type, data = manual_transfer.voucher(
                        s, transfer_id
                    )
                    self.send_response(200)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.send_header(
                        "Content-Disposition",
                        "inline; filename*=UTF-8''" + quote(filename),
                    )
                    self.end_headers()
                    self.wfile.write(data)

                self._with_session(_transfer_voucher)
            return
        # —— 其余 GET：当静态请求，托管数据大屏（console/dashboard）——
        if self._serve_dashboard(path):
            return
        self._err(404, "NEXUS_UNKNOWN", "未知端点")

    # ---- 大屏静态托管 ----
    # Nexus VM 上一个进程同时供 API 和大屏页面：同源、免 CORS、免多配一个
    # 静态服务器。生产入口 https://<nexus域名>/#token=<NEXUS_DASH_TOKEN>。

    _DASH_DIR = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "console",
        "dashboard",
    )
    # 控制台（portal）静态目录：/portal/* → console/portal/*（登录页+超管+OEM 门户）
    _PORTAL_DIR = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "console",
        "portal",
    )
    _MIME = {
        ".html": "text/html; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".mjs": "application/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".txt": "text/plain; charset=utf-8",
        ".sh": "text/x-shellscript; charset=utf-8",
        ".ico": "image/x-icon",
    }

    def _serve_dashboard(self, path: str) -> bool:
        """把 GET 路径映射到静态目录。返回是否已处理。

        路由：``/portal`` 前缀 → console/portal（控制台）；其余 → console/dashboard（大屏）。
        安全：normpath 后必须仍在对应目录内（掐死 ../ 穿越）；扩展名白名单。
        """
        admin_url = self._admin_public_url()
        admin_entry = path in ("/portal/admin", "/portal/admin/")
        if admin_entry and admin_url and not self._is_admin_host():
            self._redirect(admin_url + "/portal/admin/")
            return True
        if self._is_admin_host() and admin_url and path in ("/", "/portal", "/portal/"):
            self._redirect("/portal/admin/")
            return True
        # —— 控制台：/portal 或 /portal/xxx → console/portal/ ——
        if path == "/portal" or path.startswith("/portal/"):
            base_dir = self._PORTAL_DIR
            # 超管使用独立、可收藏的入口；页面代码仍复用同一套控制台资产，避免复制
            # 数千行后台 DOM。独立 URL 只是入口隔离，真正权限始终由管理 API 校验。
            if path in ("/portal/admin", "/portal/admin/"):
                rel = "index.html"
            else:
                rel = path[len("/portal") :].lstrip("/") or "index.html"
        else:
            base_dir = self._DASH_DIR
            rel = path.lstrip("/") or "index.html"
        if not os.path.isdir(base_dir):
            return False
        full = os.path.normpath(os.path.join(base_dir, rel))
        if not full.startswith(base_dir + os.sep) and full != os.path.join(
            base_dir, "index.html"
        ):
            return False
        ext = os.path.splitext(full)[1].lower()
        ctype = self._MIME.get(ext)
        if ctype is None or not os.path.isfile(full):
            return False
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        # 大屏迭代频繁,禁缓存省一类"改了没生效"的支持工单;地图 JSON 大文件除外
        self.send_header(
            "Cache-Control",
            "public, max-age=86400" if ext == ".json" else "no-cache",
        )
        # 静态控制台与大屏都承载敏感运营数据，先给所有页面补齐基础浏览器边界。
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=(), "
            "publickey-credentials-create=(self), "
            "publickey-credentials-get=(self)",
        )
        if path in ("/portal/admin", "/portal/admin/"):
            # 避免搜索引擎把超管入口作为普通产品页面收录；它不是鉴权边界，但没有必要
            # 主动扩大入口曝光。浏览器和反向代理仍会按正常 HTTPS 页面访问。
            self.send_header("X-Robots-Tag", "noindex, nofollow, noarchive")
        if base_dir in (self._DASH_DIR, self._PORTAL_DIR):
            # 两个前端都不再使用内联脚本，因此脚本来源可严格锁死同源。样式仍保留
            # unsafe-inline：大屏坐标/柱高和 Portal 少量表单布局依赖 style 属性；它不会
            # 放宽 JavaScript 执行权限。Portal 的凭证预览使用本地 blob URL。
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; "
                "script-src 'self' https://challenges.cloudflare.com; "
                "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
                "font-src 'self' data:; "
                "connect-src 'self' https://challenges.cloudflare.com; "
                "frame-src https://challenges.cloudflare.com; object-src 'none'; "
                "base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
            )
        self.end_headers()
        self.wfile.write(data)
        return True

    def do_POST(self) -> None:  # noqa: N802
        self._reset_request_context()
        path = self.path.split("?", 1)[0]
        if not self._require_admin_host(path):
            return

        # —— LLM 网关：/gw/<厂商>/<原厂路径后缀>（体大且可能流式，独立处理）——
        if path.startswith("/gw/"):
            from nexus import gateway  # 延迟导入：fleet-only 部署可不装 requests

            parts = path[len("/gw/") :].split("/", 1)
            provider = parts[0] if parts else ""
            suffix = parts[1] if len(parts) > 1 else ""
            gateway.handle_post(self, provider, suffix)
            return

        # —— 附件上传（原始字节直传，必须在 JSON body 读取之前处理）——
        # POST /nexus/admin/oem_upload?oem_id=N&filename=合同.pdf  body=文件字节
        if path == "/nexus/admin/oem_upload":
            if self._check_admin():
                from urllib.parse import unquote

                qs = parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
                oem_id = int((qs.get("oem_id") or ["0"])[0] or 0)
                filename = unquote((qs.get("filename") or [""])[0])
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    n = 0
                if n <= 0 or n > oem_svc.FILE_MAX_BYTES:
                    self._err(413, "NEXUS_FILE_TOO_BIG", "文件为空或超过 20MB")
                    return
                data = self.rfile.read(n)
                ctype = self.headers.get("Content-Type") or "application/octet-stream"
                self._with_session(
                    lambda s: self._json(
                        200,
                        {
                            "file": oem_svc.add_oem_file(
                                s, oem_id, filename, ctype, data
                            )
                        },
                    )
                )
            return

        # 企业转账图片以 Base64 放在 JSON 中，字段与文件在一个受鉴权请求里原子提交；
        # 这避免把银行账号塞进 URL/query，也避免“先存孤儿文件、后建记录”产生垃圾数据。
        if path in (
            "/nexus/admin/manual_transfer/recognize",
            "/nexus/admin/manual_transfers",
        ):
            if not self._check_admin():
                return
            transfer_body = self._read_large_json(12 * 1024 * 1024)
            if transfer_body is None:
                return
            try:
                image_data, content_type = manual_transfer.decode_image(
                    str(transfer_body.get("image_base64", "")),
                    str(transfer_body.get("content_type", "")),
                )
            except FleetError as error:
                self._err(error.http_status, error.code, error.message)
                return
            if path.endswith("/recognize"):

                def _recognize_transfer(_s):
                    self._json(
                        200,
                        {
                            "recognition": manual_transfer.recognize_voucher(
                                image_data, content_type
                            )
                        },
                    )

                self._with_session(_recognize_transfer)
                return

            if transfer_body.get("confirmed") is not True:
                self._err(
                    400,
                    "NEXUS_TRANSFER_NOT_CONFIRMED",
                    "请先确认银行实际到账，再登记企业转账",
                )
                return
            details = transfer_body.get("details")
            recognition = transfer_body.get("recognition")

            def _create_transfer(s):
                record = manual_transfer.create_transfer(
                    s,
                    # 类型转换与可读业务错误统一交给领域层处理，避免畸形输入冒泡成 500。
                    amount_cents=transfer_body.get("amount_cents"),
                    image_data=image_data,
                    content_type=content_type,
                    filename=str(transfer_body.get("filename", "")),
                    oem_id=transfer_body.get("oem_id"),
                    purpose=str(transfer_body.get("purpose", "")),
                    details=details if isinstance(details, dict) else {},
                    recognition=(
                        recognition if isinstance(recognition, dict) else None
                    ),
                )
                self._json(201, {"transfer": record})

            self._with_session(_create_transfer)
            return

        # OEM 购买授权会在企业转账时携带最多 8MB 凭证，必须在通用
        # JSON 体积限制前单独读取。登录态和 OEM 归属仍由服务端会话强制。
        if path == "/nexus/oem/license_checkout":
            checkout_body = self._read_large_json(12 * 1024 * 1024)
            if checkout_body is None:
                return
            method = str(checkout_body.get("payment_method", "")).strip()
            image_data = b""
            content_type = ""
            if method == "corporate_transfer":
                try:
                    image_data, content_type = manual_transfer.decode_image(
                        str(checkout_body.get("image_base64", "")),
                        str(checkout_body.get("content_type", "")),
                    )
                except FleetError as error:
                    self._err(error.http_status, error.code, error.message)
                    return

            def _license_checkout(s):
                account = self._oem(s)
                if account is None:
                    return
                details = checkout_body.get("transfer_details")
                result = pay.create_license_checkout(
                    s,
                    account.id,
                    method,
                    channel=str(checkout_body.get("channel", "")),
                    note=str(checkout_body.get("note", "")),
                    deployment_domain=str(checkout_body.get("deployment_domain", "")),
                    purpose=str(checkout_body.get("purpose", "")),
                    expected_date=str(checkout_body.get("expected_date", "")),
                    # 付款领域层还会再根据平台开关强制归零；
                    # 这里保留原始值，便于开启功能时处理人工授权。
                    requested_tokens=int(checkout_body.get("requested_tokens") or 0),
                    expected_public_ip=str(checkout_body.get("expected_public_ip", "")),
                    strict_ip=bool(checkout_body.get("strict_ip", False)),
                    image_data=image_data,
                    content_type=content_type,
                    filename=str(checkout_body.get("filename", "")),
                    transfer_details=details if isinstance(details, dict) else {},
                    source_ip=self._client_ip(),
                )
                self._json(201, result)

            self._with_session(_license_checkout)
            return

        # Token 企业转账和授权购买一样携带图片；金额、套餐、实例归属均由服务端
        # 重算，浏览器不能自行提交金额或 Token 数。
        if path == "/nexus/oem/topup_checkout":
            checkout_body = self._read_large_json(12 * 1024 * 1024)
            if checkout_body is None:
                return
            method = str(checkout_body.get("payment_method", "online")).strip()
            image_data = b""
            content_type = ""
            if method == "corporate_transfer":
                try:
                    image_data, content_type = manual_transfer.decode_image(
                        str(checkout_body.get("image_base64", "")),
                        str(checkout_body.get("content_type", "")),
                    )
                except FleetError as error:
                    self._err(error.http_status, error.code, error.message)
                    return

            def _topup_checkout(s):
                account = self._oem(s)
                if account is None:
                    return
                instance_id = int(checkout_body.get("instance_id") or 0)
                if not oem_svc.owns_instance(s, account.id, instance_id):
                    raise FleetError("NEXUS_FORBIDDEN", "该实例不属于你的账号", 403)
                if method == "corporate_transfer":
                    details = checkout_body.get("transfer_details")
                    result = pay.create_topup_transfer(
                        s,
                        account.id,
                        instance_id,
                        int(checkout_body.get("pack_index", -1)),
                        image_data=image_data,
                        content_type=content_type,
                        filename=str(checkout_body.get("filename", "")),
                        transfer_details=(details if isinstance(details, dict) else {}),
                    )
                elif method == "online":
                    result = pay.create_order(
                        s,
                        account.id,
                        "topup",
                        str(checkout_body.get("channel", "")),
                        instance_id=instance_id,
                        pack_index=int(checkout_body.get("pack_index", -1)),
                    )
                else:
                    raise FleetError("NEXUS_BAD_PAYMENT_METHOD", "请选择有效的付款方式")
                self._json(201, result)

            self._with_session(_topup_checkout)
            return

        body = self._read_body()

        # 终身会员激活由节点服务端代理：用户不接触 OEM 部署 KEY，
        # Nexus 同时校验“节点授权 + 激活码归属 + 一人一码”。
        if path == "/nexus/lifetime/activate":
            self._with_session(
                lambda s: self._json(
                    200,
                    entitlements.activate_lifetime_code(
                        s,
                        raw_node_key=str(body.get("key", "")),
                        activation_code=str(body.get("activation_code", "")),
                        user_id=str(body.get("user_id", "")),
                        device_kind=str(body.get("device_kind", "node")),
                        device_id=str(body.get("device_id", "")),
                    ),
                )
            )
            return

        # —— GitHub Actions 镜像构建回调：不走浏览器管理员会话，只认独立 HMAC ——
        # 签名覆盖时间戳与规范化 JSON；五分钟窗口可阻断截获后的长期重放。清单本身只含
        # 公开镜像摘要和 commit，不含 GHCR 凭据，登记后同版本不可覆盖。
        if path == "/nexus/release/manifest":
            def _register_image_manifest(s):
                release_artifacts.verify_webhook(
                    body,
                    str(self.headers.get("X-Nexus-Timestamp", "")),
                    str(self.headers.get("X-Nexus-Signature", "")),
                )
                manifest = release_artifacts.register_manifest(s, body)
                release = releases.ensure_ci_release_draft(
                    s,
                    version=str(manifest["version"]),
                    title=str(body.get("release_title", "")),
                    notes=str(body.get("release_notes", "")),
                )
                # CI 只在收到 201 后结束，所以回应前必须确认镜像
                # 清单和未发布草稿均已持久化，避免后续查询的竞态。
                s.commit()
                self._json(201, {"manifest": manifest, "release": release})

            self._with_session(_register_image_manifest)
            return

        # —— 具名平台主管登录与账号管理 ——
        if path == "/nexus/admin/auth/login":
            if not _auth_rate_ok(self._client_ip()):
                self._err(429, "NEXUS_RATE_LIMIT", "尝试过于频繁，请稍后再试")
                return

            def _admin_login(s):
                result = admin_auth.login(
                    s,
                    str(body.get("username", "")),
                    str(body.get("password", "")),
                    self._client_ip(),
                )
                # 明文会话令牌只进入 HttpOnly Cookie，不再返回给 JavaScript。
                token = str(result.pop("token"))
                result["admin"]["auth_kind"] = "named_cookie"
                self._set_admin_cookie(token)
                # 会话必须先落库再把 Cookie 发给浏览器。否则快速网络下
                # 下一个请求可能早于外层事务提交，被误判为会话无效。
                s.commit()
                self._json(200, result)

            self._with_session(_admin_login)
            return

        if path == "/nexus/admin/auth/passkey/options":
            if not _auth_rate_ok(self._client_ip()):
                self._err(429, "NEXUS_RATE_LIMIT", "尝试过于频繁，请稍后再试")
                return
            self._with_session(
                lambda s: self._json(
                    200,
                    passkeys.authentication_options(s, str(body.get("username", ""))),
                )
            )
            return

        if path == "/nexus/admin/auth/passkey/verify":
            if not _auth_rate_ok(self._client_ip()):
                self._err(429, "NEXUS_RATE_LIMIT", "尝试过于频繁，请稍后再试")
                return

            def _passkey_login(s):
                credential = body.get("credential")
                if not isinstance(credential, dict):
                    raise FleetError(
                        "NEXUS_PASSKEY_RESPONSE_INVALID",
                        "浏览器未返回有效 Passkey 响应",
                    )
                result = passkeys.verify_authentication(
                    s,
                    str(body.get("ceremony_id", "")),
                    credential,
                    source_ip=self._client_ip(),
                )
                token = str(result.pop("token"))
                result["admin"]["auth_kind"] = "passkey_cookie"
                self._set_admin_cookie(token)
                # WebAuthn 会话与密码会话保持相同的“先持久化、后回应”语义。
                s.commit()
                self._json(200, result)

            self._with_session(_passkey_login)
            return

        if path == "/nexus/admin/auth/recovery":
            if not _auth_rate_ok(self._client_ip()):
                self._err(429, "NEXUS_RATE_LIMIT", "尝试过于频繁，请稍后再试")
                return

            def _recovery_login(s):
                result = admin_auth.consume_recovery_code(
                    s, str(body.get("recovery_code", ""))
                )
                token = str(result.pop("token"))
                self._set_admin_cookie(token)
                self._admin_actor_id = 0
                self._admin_actor_label = "服务器应急恢复"
                self._admin_auth_kind = "recovery_cookie"
                audit.record(
                    s,
                    object_type="admin",
                    object_id=0,
                    action="recovery_login",
                    actor_type="admin",
                    actor_label="服务器应急恢复",
                    source_ip=self._client_ip(),
                    to_state="active",
                )
                # 单次码的已使用标记和恢复会话必须在回传 Cookie 前
                # 原子提交，同时避免首次建号紧接着请求时出现 503。
                s.commit()
                self._json(
                    200,
                    {
                        "admin": {
                            "id": 0,
                            "display_name": "服务器应急恢复",
                            "auth_kind": "recovery_cookie",
                        },
                        "expires_ts": result["expires_ts"],
                    },
                )

            self._with_session(_recovery_login)
            return

        if path == "/nexus/admin/auth/emergency":
            # 旧路由明确作废，不做静默兼容；这可以让旧页面和脚本
            # 尽快暴露长期令牌依赖，而不是继续留下难以发现的后门。
            self._err(
                410,
                "NEXUS_EMERGENCY_TOKEN_REMOVED",
                "长期应急令牌已停用，请从服务器 SSH 生成单次恢复码",
            )
            return

        if path == "/nexus/admin/auth/logout":
            if self._check_admin():
                token = str(getattr(self, "_admin_session_token", ""))

                def _admin_logout(s):
                    admin_auth.logout(s, token)
                    self._clear_admin_cookie()
                    self._json(200, {"ok": True})

                self._with_session(_admin_logout)
            return

        if path == "/nexus/admin/passkey/register/options":
            if self._check_admin():
                actor_id = int(getattr(self, "_admin_actor_id", 0))
                if actor_id <= 0:
                    self._err(
                        403,
                        "NEXUS_NAMED_ADMIN_REQUIRED",
                        "请先使用具名管理员账号登录再登记 Passkey",
                    )
                    return
                self._with_session(
                    lambda s: self._json(
                        200, passkeys.registration_options(s, actor_id)
                    )
                )
            return

        if path == "/nexus/admin/passkey/register/verify":
            if self._check_admin():
                actor_id = int(getattr(self, "_admin_actor_id", 0))
                if actor_id <= 0:
                    self._err(
                        403,
                        "NEXUS_NAMED_ADMIN_REQUIRED",
                        "应急身份不能登记 Passkey",
                    )
                    return
                credential = body.get("credential")
                if not isinstance(credential, dict):
                    self._err(
                        400,
                        "NEXUS_PASSKEY_RESPONSE_INVALID",
                        "浏览器未返回有效 Passkey 响应",
                    )
                    return
                self._with_session(
                    lambda s: self._json(
                        201,
                        {
                            "passkey": passkeys.verify_registration(
                                s,
                                actor_id,
                                str(body.get("ceremony_id", "")),
                                credential,
                                str(body.get("name", "")),
                                actor_label=self._admin_actor(),
                                source_ip=self._client_ip(),
                            )
                        },
                    )
                )
            return

        if path == "/nexus/admin/passkey/delete":
            if self._check_admin():
                actor_id = int(getattr(self, "_admin_actor_id", 0))
                if actor_id <= 0:
                    self._err(
                        403,
                        "NEXUS_NAMED_ADMIN_REQUIRED",
                        "应急身份不能管理 Passkey",
                    )
                    return

                def _delete_passkey(s):
                    passkeys.delete_passkey(
                        s,
                        actor_id,
                        int(body.get("passkey_id") or 0),
                        actor_label=self._admin_actor(),
                        source_ip=self._client_ip(),
                    )
                    self._json(200, {"ok": True})

                self._with_session(_delete_passkey)
            return

        if path == "/nexus/admin/admins":
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(
                        201,
                        {
                            "admin": admin_auth.create_admin(
                                s,
                                str(body.get("username", "")),
                                str(body.get("password", "")),
                                str(body.get("display_name", "")),
                                role=str(body.get("role", "superadmin")),
                                actor_label=self._admin_actor(),
                                source_ip=self._client_ip(),
                            )
                        },
                    )
                )
            return

        if path == "/nexus/admin/admin_status":
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(
                        200,
                        {
                            "admin": admin_auth.set_status(
                                s,
                                int(body.get("admin_id") or 0),
                                str(body.get("status", "")),
                                actor_id=int(getattr(self, "_admin_actor_id", 0)),
                                actor_label=self._admin_actor(),
                                source_ip=self._client_ip(),
                            )
                        },
                    )
                )
            return

        if path == "/nexus/admin/admin_role":
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(
                        200,
                        {
                            "admin": admin_auth.set_role(
                                s,
                                int(body.get("admin_id") or 0),
                                str(body.get("role", "")),
                                actor_id=int(getattr(self, "_admin_actor_id", 0)),
                                actor_label=self._admin_actor(),
                                source_ip=self._client_ip(),
                            )
                        },
                    )
                )
            return

        if path == "/nexus/admin/admin_password":
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(
                        200,
                        {
                            "admin": admin_auth.reset_password(
                                s,
                                int(body.get("admin_id") or 0),
                                str(body.get("new_password", "")),
                                actor_label=self._admin_actor(),
                                source_ip=self._client_ip(),
                            )
                        },
                    )
                )
            return

        if path == "/nexus/redeem":
            if not _rate_ok(self._client_ip()):
                self._err(429, "NEXUS_RATE_LIMIT", "尝试过于频繁，请一小时后再试")
                return

            def _redeem(s):
                raw_key = str(body.get("key", ""))
                region_code = fleet.deployment_region(
                    s, raw_key, str(body.get("region", ""))
                )
                out = fleet.redeem(
                    s,
                    raw_key,
                    str(body.get("domain", "")),
                    str(body.get("admin_email", "")),
                    region_code,
                    # 来源由 Nexus 自己读取，安装脚本不能通过自报地址绕过 IP 风控。
                    client_ip=self._client_ip(),
                )
                # 装机成功后销毁申请单里存的交付明文（阅后即焚的"焚"时刻）
                oem_svc.clear_plain_by_key(s, raw_key)
                self._json(200, out)

            self._with_session(_redeem)
            return

        if path == "/nexus/install/artifact":
            # 首次安装尚未拥有实例会话，只能用已审批 KEY 获取公开镜像摘要；接口不返回
            # 仓库凭据，且复用兑换限频，防止被批量探测 KEY 或版本信息。
            if not _rate_ok(self._client_ip()):
                self._err(429, "NEXUS_RATE_LIMIT", "尝试过于频繁，请一小时后再试")
                return
            self._with_session(
                lambda s: self._json(
                    200,
                    releases.install_artifact(
                        s,
                        str(body.get("key", "")),
                        str(body.get("domain", "")),
                    ),
                )
            )
            return

        if path == "/nexus/heartbeat":
            stats = body.get("stats")
            self._with_session(
                lambda s: self._json(
                    200,
                    fleet.heartbeat(
                        s,
                        str(body.get("key", "")),
                        str(body.get("version", "")),
                        stats if isinstance(stats, dict) else {},
                        # 来源 IP 由母舰这边读（实例自报不可信、也拿不到自己的公网 IP）
                        client_ip=self._client_ip(),
                    ),
                )
            )
            return

        if path == "/nexus/user/attribution":
            self._with_session(
                lambda s: self._json(
                    200,
                    oem_svc.record_user_attribution(
                        s,
                        str(body.get("key", "")),
                        str(body.get("referral_code", "")),
                        str(body.get("user_id", "")),
                    ),
                )
            )
            return

        # —— 节点版本代理：授权 KEY 只可读取/更新自己的投放记录 ——
        if path == "/nexus/update/check":
            self._with_session(
                lambda s: self._json(
                    200,
                    {
                        "update": releases.check_update(
                            s,
                            str(body.get("key", "")),
                            str(body.get("current_version", "")),
                        )
                    },
                )
            )
            return

        if path == "/nexus/update/report":
            self._with_session(
                lambda s: self._json(
                    200,
                    releases.report_update(
                        s,
                        raw_key=str(body.get("key", "")),
                        release_id=int(body.get("release_id") or 0),
                        status=str(body.get("status", "")),
                        current_version=str(body.get("current_version", "")),
                        detail=str(body.get("detail", "")),
                    ),
                )
            )
            return

        # —— OEM 账号：邮箱验证 / 注册 / 登录 / 找回密码（免鉴权、统一按 IP 限频）——
        if path in (
            "/nexus/oem/email/request-code",
            "/nexus/oem/register",
            "/nexus/oem/login",
            "/nexus/oem/login/code",
            "/nexus/oem/password/reset",
        ):
            if not _auth_rate_ok(self._client_ip()):
                self._err(429, "NEXUS_RATE_LIMIT", "尝试过于频繁，请稍后再试")
                return
            if path == "/nexus/oem/email/request-code":
                self._with_session(
                    lambda s: self._json(
                        200,
                        oem_email.request_code(
                            s,
                            str(body.get("email", "")),
                            str(body.get("purpose", "")),
                            turnstile_token=str(body.get("turnstile_token", "")),
                            source_ip=self._client_ip(),
                        ),
                    )
                )
            elif path == "/nexus/oem/register":
                self._with_session(
                    lambda s: self._json(
                        200,
                        {
                            "oem": oem_email.register_with_code(
                                s,
                                email=str(body.get("email", "")),
                                code=str(body.get("code", "")),
                                password=str(body.get("password", "")),
                                name=str(body.get("name", "")),
                                inviter=str(body.get("inviter", "")),
                                company=str(body.get("company", "")),
                                contact_name=str(body.get("contact_name", "")),
                                phone=str(body.get("phone", "")),
                            )
                        },
                    )
                )
            elif path == "/nexus/oem/login":
                def _oem_password_login(s):
                    """用密码签发 OEM 会话，并确保令牌返回前已落库。"""
                    result = oem_svc.login(
                        s,
                        str(body.get("email", "")),
                        str(body.get("password", "")),
                    )
                    s.commit()
                    self._json(200, result)

                self._with_session(_oem_password_login)
            elif path == "/nexus/oem/login/code":
                def _oem_code_login(s):
                    """用邮箱验证码签发 OEM 会话，先持久化再回应。"""
                    result = oem_email.login_with_code(
                        s,
                        str(body.get("email", "")),
                        str(body.get("code", "")),
                    )
                    s.commit()
                    self._json(200, result)

                self._with_session(_oem_code_login)
            else:
                self._with_session(
                    lambda s: self._json(
                        200,
                        oem_email.reset_password(
                            s,
                            str(body.get("email", "")),
                            str(body.get("code", "")),
                            str(body.get("password", "")),
                            self._client_ip(),
                        ),
                    )
                )
            return

        if path == "/nexus/oem/logout":
            token = self._bearer()
            self._with_session(
                lambda s: (oem_svc.logout(s, token), self._json(200, {"ok": True}))[-1]
            )
            return

        if path == "/nexus/oem/claim":

            def _claim(s):
                oem = self._oem(s)
                if oem is None:
                    return
                self._json(200, oem_svc.claim_key(s, oem.id, str(body.get("key", ""))))

            self._with_session(_claim)
            return

        if path == "/nexus/oem/request_key":

            def _req(s):
                oem = self._oem(s)
                if oem is None:
                    return
                self._json(
                    200,
                    {
                        "request": oem_svc.request_key(
                            s,
                            oem.id,
                            str(body.get("note", "")),
                            deployment_domain=str(body.get("deployment_domain", "")),
                            purpose=str(body.get("purpose", "")),
                            expected_date=str(body.get("expected_date", "")),
                            requested_tokens=(
                                int(body.get("requested_tokens") or 0)
                                if features.get_flags(s)[
                                    "oem_token_grant_request_visible"
                                ]
                                else 0
                            ),
                            expected_public_ip=str(body.get("expected_public_ip", "")),
                            strict_ip=bool(body.get("strict_ip", False)),
                            source_ip=self._client_ip(),
                        )
                    },
                )

            self._with_session(_req)
            return

        if path == "/nexus/oem/request_action":

            def _request_action(s):
                account = self._oem(s)
                if account is None:
                    return
                action = str(body.get("action", ""))
                request_id = int(body.get("request_id") or 0)
                if action == "cancel":
                    result = oem_svc.cancel_request(
                        s, account.id, request_id, self._client_ip()
                    )
                elif action == "update":
                    result = oem_svc.update_request(
                        s,
                        account.id,
                        request_id,
                        note=str(body.get("note", "")),
                        deployment_domain=str(body.get("deployment_domain", "")),
                        purpose=str(body.get("purpose", "")),
                        expected_date=str(body.get("expected_date", "")),
                        requested_tokens=(
                            int(body.get("requested_tokens") or 0)
                            if features.get_flags(s)[
                                "oem_token_grant_request_visible"
                            ]
                            else 0
                        ),
                        expected_public_ip=str(body.get("expected_public_ip", "")),
                        strict_ip=bool(body.get("strict_ip", False)),
                        source_ip=self._client_ip(),
                    )
                elif action == "reveal":
                    result = oem_svc.reveal_request_key(
                        s, account.id, request_id, self._client_ip()
                    )
                else:
                    raise FleetError("NEXUS_BAD_ACTION", "不支持的申请操作")
                self._json(200, {"request": result})

            self._with_session(_request_action)
            return

        if path == "/nexus/oem/lifetime_request":

            def _lifetime_request(s):
                account = self._oem(s)
                if account is None:
                    return
                self._json(
                    201,
                    {
                        "request": entitlements.request_lifetime_code(
                            s,
                            account.id,
                            int(body.get("instance_id") or 0),
                            str(body.get("note", "")),
                        )
                    },
                )

            self._with_session(_lifetime_request)
            return

        if path == "/nexus/oem/lifetime_action":

            def _lifetime_action(s):
                account = self._oem(s)
                if account is None:
                    return
                action = str(body.get("action", ""))
                request_id = int(body.get("request_id") or 0)
                if action == "cancel":
                    result = entitlements.cancel_lifetime_request(
                        s, account.id, request_id
                    )
                    self._json(200, {"request": result})
                elif action == "reveal":
                    self._json(
                        200,
                        entitlements.reveal_lifetime_code(
                            s, account.id, request_id
                        ),
                    )
                else:
                    raise FleetError("NEXUS_BAD_ACTION", "不支持的激活码操作")

            self._with_session(_lifetime_action)
            return

        if path == "/nexus/oem/token_purchase_request":

            def _token_purchase_request(s):
                account = self._oem(s)
                if account is None:
                    return
                self._json(
                    201,
                    {
                        "request": entitlements.request_token_purchase(
                            s,
                            account.id,
                            int(body.get("instance_id") or 0),
                            int(body.get("requested_tokens") or 0),
                            str(body.get("note", "")),
                        )
                    },
                )

            self._with_session(_token_purchase_request)
            return

        if path == "/nexus/oem/token_purchase_action":

            def _token_purchase_action(s):
                account = self._oem(s)
                if account is None:
                    return
                if str(body.get("action", "")) != "cancel":
                    raise FleetError("NEXUS_BAD_ACTION", "不支持的 Token 申请操作")
                self._json(
                    200,
                    {
                        "request": entitlements.cancel_token_purchase_request(
                            s,
                            account.id,
                            int(body.get("request_id") or 0),
                        )
                    },
                )

            self._with_session(_token_purchase_action)
            return

        # —— Token 充值订单（KEY 必须走上方 license_checkout）——
        if path == "/nexus/oem/withdrawals":

            def _withdraw(s):
                account = self._oem(s)
                if account is None:
                    return
                payout = body.get("payout")
                self._json(
                    201,
                    {
                        "withdrawal": oem_finance.request_withdrawal(
                            s,
                            account.id,
                            int(body.get("amount_cents") or 0),
                            payout if isinstance(payout, dict) else {},
                            str(body.get("note", "")),
                        )
                    },
                )

            self._with_session(_withdraw)
            return

        if path == "/nexus/oem/order":

            def _order(s):
                oem = self._oem(s)
                if oem is None:
                    return
                kind = str(body.get("kind", ""))
                if kind != "topup":
                    # 旧端点曾允许直接买 KEY，会绕过部署资料、付款关联和安全领取。
                    # 新请求必须统一进入授权购买流程；旧的待支付订单仍可正常回调履约。
                    self._err(
                        409,
                        "NEXUS_LICENSE_CHECKOUT_REQUIRED",
                        "购买节点授权请使用统一授权购买流程",
                    )
                    return
                inst = body.get("instance_id")
                if kind == "topup" and not oem_svc.owns_instance(
                    s, oem.id, int(inst or 0)
                ):
                    self._err(403, "NEXUS_FORBIDDEN", "该实例不属于你的账号")
                    return
                self._json(
                    200,
                    pay.create_order(
                        s,
                        oem.id,
                        kind,
                        str(body.get("channel", "")),
                        instance_id=int(inst) if inst else None,
                        pack_index=int(body.get("pack_index", -1)),
                    ),
                )

            self._with_session(_order)
            return

        # mock 渠道确认（仅 NEXUS_PAY_MOCK=1 环境；买家本人对自己的单确认）
        if path == "/nexus/pay/mock/confirm":

            def _mock(s):
                if os.environ.get("NEXUS_PAY_MOCK", "").strip() != "1":
                    self._err(404, "NEXUS_UNKNOWN", "未知端点")
                    return
                oem = self._oem(s)
                if oem is None:
                    return
                order = pay.get_order_for(s, oem.id, str(body.get("order_no", "")))
                self._json(200, {"order": pay.mark_paid(s, order.order_no, "MOCK")})

            self._with_session(_mock)
            return

        # 支付渠道异步回调（骨架：验签在 provider 内，API 接入前一律 503）
        if path in ("/nexus/pay/notify/alipay", "/nexus/pay/notify/wechat"):
            channel = path.rsplit("/", 1)[-1]

            def _notify(s):
                provider = pay._PROVIDERS[channel]
                info = provider.verify_notify(dict(self.headers), b"")
                pay.mark_paid(
                    s,
                    info["order_no"],
                    info.get("provider_txn", ""),
                    paid_amount_cents=(
                        int(info["amount_cents"])
                        if info.get("amount_cents") is not None
                        else None
                    ),
                    paid_currency=info.get("currency", "CNY"),
                )
                # 支付宝要求回 success 文本；这里统一 JSON,接真 API 时按渠道要求调整
                self._json(200, {"ok": True})

            self._with_session(_notify)
            return

        if path == "/nexus/admin/pricing":
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(200, {"pricing": pay.set_pricing(s, body)})
                )
            return

        if path == "/nexus/admin/oem_commercial_terms":
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(
                        200,
                        {
                            "terms": oem_finance.set_commercial_terms(
                                s,
                                int(body.get("oem_id") or 0),
                                body,
                            )
                        },
                    )
                )
            return

        if path == "/nexus/admin/topup_transfer_decide":
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(
                        200,
                        pay.decide_topup_transfer(
                            s,
                            str(body.get("order_no", "")),
                            bool(body.get("approve")),
                            str(body.get("note", "")),
                        ),
                    )
                )
            return

        if path == "/nexus/admin/withdrawal_decide":
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(
                        200,
                        {
                            "withdrawal": oem_finance.decide_withdrawal(
                                s,
                                int(body.get("withdrawal_id") or 0),
                                str(body.get("action", "")),
                                str(body.get("note", "")),
                            )
                        },
                    )
                )
            return

        if path == "/nexus/admin/features":
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(200, {"features": features.set_flags(s, body)})
                )
            return

        if path == "/nexus/admin/release_policy":
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(
                        200,
                        {
                            "release_policy": release_policy.set_policy(s, body)
                        },
                    )
                )
            return

        if path == "/nexus/admin/payment_config":
            if self._check_admin():

                def _payment_config(s):
                    provider = str(body.get("provider", "")).strip().lower()
                    action = str(body.get("action", "save")).strip().lower()
                    if action == "verify":
                        result = payment_config.verify_existing(s, provider)
                    elif action == "save":
                        submitted = body.get("config")
                        if not isinstance(submitted, dict):
                            raise FleetError(
                                "NEXUS_PAY_CONFIG_INVALID", "支付配置格式不正确"
                            )
                        result = payment_config.save_and_verify(s, provider, submitted)
                    else:
                        raise FleetError(
                            "NEXUS_PAY_CONFIG_ACTION", "支付配置操作不合法"
                        )
                    self._json(200, {"payment_config": result})

                self._with_session(_payment_config)
            return

        if path == "/nexus/admin/releases":
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(
                        201,
                        {
                            "release": releases.create_release(
                                s,
                                version=str(body.get("version", "")),
                                title=str(body.get("title", "")),
                                notes=str(body.get("notes", "")),
                                git_ref=str(body.get("git_ref", "")),
                                # 旧版控制台没有 target 字段，继续按节点版本处理，避免
                                # 发布中心升级瞬间把历史操作语义改成平台公告。
                                target=str(body.get("target") or "node"),
                                # 新节点版本默认要求 CI 镜像；严格 Git 只允许运维明确
                                # 指定 legacy_git，用于首次引导或更新器救援。
                                delivery_mode=str(
                                    body.get("delivery_mode")
                                    or (
                                        "container"
                                        if str(body.get("target") or "node") == "node"
                                        else "legacy_git"
                                    )
                                ),
                            )
                        },
                    )
                )
            return

        if path == "/nexus/admin/release_action":
            if self._check_admin():

                def _release_action(s):
                    action = str(body.get("action", ""))
                    release_id = int(body.get("release_id") or 0)
                    if action == "canary":
                        result = releases.start_canary(
                            s,
                            release_id,
                            int(body.get("instance_id") or 0),
                        )
                    elif action == "publish":
                        result = releases.publish(s, release_id)
                    elif action == "pause":
                        result = releases.pause(s, release_id)
                    elif action == "rollback":
                        result = releases.rollback(s, release_id)
                    elif action == "retry":
                        result = releases.retry_failed(s, release_id)
                    elif action == "baseline":
                        result = releases.set_install_baseline(s, release_id)
                    else:
                        raise FleetError("NEXUS_BAD_RELEASE_ACTION", "版本操作不合法")
                    self._json(200, {"release": result})

                self._with_session(_release_action)
            return

        if path == "/nexus/admin/instance_region":
            # 改实例地域（OEM 兑码时填错/没填时，超管在 console 里纠正）
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(
                        200,
                        fleet.set_geo(
                            s,
                            int(body.get("instance_id") or 0),
                            str(body.get("region", "")),
                        ),
                    )
                )
            return

        if path == "/nexus/admin/instance_member_policy":
            # 永久权益是否必须经母舰审批属于商业安全策略，只允许超管调整。
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(
                        200,
                        {
                            "member_policy": member_policy.set_policy(
                                s,
                                int(body.get("instance_id") or 0),
                                body.get("lifetime_approval_required"),
                            )
                        },
                    )
                )
            return

        if path == "/nexus/admin/request_decide":
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(
                        200,
                        {
                            "request": oem_svc.decide_request(
                                s,
                                int(body.get("request_id") or 0),
                                bool(body.get("approve")),
                                # 超管端也不能绕过平台开关：关闭时即使
                                # 手工构造 HTTP 请求，新签发 KEY 的额度仍为 0。
                                token_grant=(
                                    int(body.get("token_grant") or 0)
                                    if features.get_flags(s)[
                                        "oem_token_grant_request_visible"
                                    ]
                                    else 0
                                ),
                                decide_note=str(body.get("decide_note", "")),
                                action=str(body.get("action", "")),
                                actor_label=self._admin_actor(),
                                source_ip=self._client_ip(),
                            )
                        },
                    )
                )
            return

        if path == "/nexus/admin/lifetime_request_decide":
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(
                        200,
                        {
                            "request": entitlements.decide_lifetime_request(
                                s,
                                int(body.get("request_id") or 0),
                                bool(body.get("approve")),
                                str(body.get("decide_note", "")),
                            )
                        },
                    )
                )
            return

        if path == "/nexus/admin/token_purchase_decide":
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(
                        200,
                        {
                            "request": entitlements.decide_token_purchase_request(
                                s,
                                int(body.get("request_id") or 0),
                                approve=bool(body.get("approve")),
                                amount_cents=int(body.get("amount_cents") or 0),
                                decide_note=str(body.get("decide_note", "")),
                            )
                        },
                    )
                )
            return

        if path == "/nexus/admin/license_transfer_decide":
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(
                        200,
                        pay.decide_license_transfer(
                            s,
                            int(body.get("request_id") or 0),
                            bool(body.get("approve")),
                            str(body.get("note", "")),
                            actor_label=self._admin_actor(),
                            source_ip=self._client_ip(),
                        ),
                    )
                )
            return

        if path == "/nexus/admin/keys":
            if self._check_admin():
                # KEY 必须来自授权申请审批或经支付验签的履约事务，禁止再由
                # 超管绕过申请归属、域名绑定和“一份申请一把 KEY”的规则直接生成。
                self._err(
                    410,
                    "NEXUS_MANUAL_KEY_ISSUE_DISABLED",
                    "手动签发已停用，请通过授权申请审批或支付履约签发 KEY",
                )
            return

        if path == "/nexus/admin/revoke":
            if self._check_admin():

                def _do(s):
                    key_id = int(body.get("key_id") or 0)
                    reason = str(body.get("reason", "")).strip()
                    if not reason:
                        raise FleetError(
                            "NEXUS_REASON_REQUIRED", "永久吊销必须填写原因"
                        )
                    key_row = s.get(db.NexusKey, key_id)
                    old_status = key_row.status if key_row else ""
                    fleet.revoke_key(s, key_id)
                    audit.record(
                        s,
                        object_type="key",
                        object_id=key_id,
                        action="revoke",
                        actor_type="admin",
                        actor_label=self._admin_actor(),
                        source_ip=self._client_ip(),
                        from_state=old_status,
                        to_state="revoked",
                        note=reason,
                    )
                    self._json(200, {"ok": True})

                self._with_session(_do)
            return

        if path == "/nexus/admin/key_status":
            if self._check_admin():

                def _key_status(s):
                    key_id = int(body.get("key_id") or 0)
                    target = str(body.get("status", ""))
                    reason = str(body.get("reason", "")).strip()
                    if not reason:
                        raise FleetError(
                            "NEXUS_REASON_REQUIRED", "暂停或恢复必须填写原因"
                        )
                    changed = fleet.set_key_status(s, key_id, target)
                    audit.record(
                        s,
                        object_type="key",
                        object_id=key_id,
                        action="resume" if target == "active" else "suspend",
                        actor_type="admin",
                        actor_label=self._admin_actor(),
                        source_ip=self._client_ip(),
                        from_state=str(changed.get("from_status", "")),
                        to_state=target,
                        note=reason,
                    )
                    self._json(200, {"key": changed})

                self._with_session(_key_status)
            return

        if path == "/nexus/admin/oem_note":
            if self._check_admin():

                def _note(s):
                    oem_svc.set_admin_note(
                        s, int(body.get("oem_id") or 0), str(body.get("note", ""))
                    )
                    self._json(200, {"ok": True})

                self._with_session(_note)
            return

        if path == "/nexus/admin/oem_file_delete":
            if self._check_admin():

                def _fdel(s):
                    oem_svc.delete_oem_file(s, int(body.get("file_id") or 0))
                    self._json(200, {"ok": True})

                self._with_session(_fdel)
            return

        if path == "/nexus/admin/oem_status":
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(
                        200,
                        {
                            "oem": oem_svc.set_oem_status(
                                s,
                                int(body.get("oem_id") or 0),
                                str(body.get("status", "")),
                            )
                        },
                    )
                )
            return

        if path == "/nexus/admin/topup":
            if self._check_admin():
                clean_note = str(body.get("note", "")).strip().replace("｜", "|")[:300]
                actor = self._admin_actor().replace("｜", "|")[:120]
                audit_note = "人工充值｜操作人：" + actor
                if clean_note:
                    audit_note += "｜备注：" + clean_note
                self._with_session(
                    lambda s: self._json(
                        200,
                        {
                            "balance_tokens": fleet.topup(
                                s,
                                int(body.get("instance_id") or 0),
                                int(body.get("tokens") or 0),
                                audit_note,
                            )
                        },
                    )
                )
            return

        self._err(404, "NEXUS_UNKNOWN", "未知端点")

    # ---- Session 包装：业务错误→JSON，未知错误→500 且不泄内部细节 ----

    def _with_session(self, fn) -> None:
        s = db.session()
        self._defer_json_response = True
        self._pending_json_response = None
        try:
            fn(s)
            # 每个成功的管理写请求都追加一条平台级审计。授权、KEY 等领域函数仍保留
            # 自己的细粒度时间线；这里补齐定价、功能开关、支付配置等过去没有对象日志
            # 的运营动作，形成可统一检索的完整后台操作轨迹。
            path = self.path.split("?", 1)[0]
            if (
                self.command == "POST"
                and path.startswith("/nexus/admin/")
                and getattr(self, "_admin_actor_label", "")
                and 200 <= int(getattr(self, "_last_response_status", 0)) < 400
            ):
                audit.record(
                    s,
                    object_type="admin_operation",
                    object_id=int(getattr(self, "_admin_actor_id", 0)),
                    action=path.rsplit("/", 1)[-1][:32],
                    actor_type="admin",
                    actor_label=self._admin_actor(),
                    source_ip=self._client_ip(),
                    metadata={"path": path},
                )
            s.commit()
            pending = self._pending_json_response
            self._defer_json_response = False
            self._pending_json_response = None
            if pending is not None:
                self._send_json(pending[0], pending[1])
        except FleetError as e:
            s.rollback()
            self._defer_json_response = False
            self._pending_json_response = None
            self._err(e.http_status, e.code, e.message)
        except Exception:
            s.rollback()
            self._defer_json_response = False
            self._pending_json_response = None
            logger.exception("nexus 内部错误 %s", self.path)
            self._err(500, "NEXUS_INTERNAL", "内部错误")
        finally:
            s.close()


def run(host: str = "", port: int = 0) -> None:
    """启动 Nexus 服务（阻塞）。默认 127.0.0.1:9100，可用 env 覆盖。"""
    host = host or os.environ.get("NEXUS_LISTEN_HOST", "127.0.0.1")
    port = port or int(os.environ.get("NEXUS_LISTEN_PORT", "9100"))
    db.init_engine()
    s = db.session()
    try:
        if admin_auth.active_count(s) == 0:
            logger.warning(
                "平台主管账号尚未创建——请从 SSH 运行 "
                "python -m nexus.recovery_codes 完成首次引导"
            )
    finally:
        s.close()
    srv = ThreadingHTTPServer((host, port), NexusHandler)
    logger.info("GuDuu Nexus fleet 服务监听 %s:%s", host, port)
    srv.serve_forever()
