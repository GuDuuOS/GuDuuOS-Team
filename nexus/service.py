"""GuDuu Nexus HTTP 服务（fleet 端点）。

技术选型与 cosmac bot 保持一致：标准库 ThreadingHTTPServer + 同步逻辑，
不引入 Web 框架——单人维护，栈越少越好。

端点总览：
    公开（实例回连，凭 KEY 鉴权）：
        GET  /nexus/health                       探活
        POST /nexus/redeem     {key,domain,admin_email,region}  兑换开通（install.sh 调）
        POST /nexus/heartbeat  {key,version,stats}        心跳上报（实例定时调）
        GET  /nexus/referral?code=...                    公开校验 OEM 分享码
        POST /nexus/user/attribution {key,referral_code,user_id} 用户归属上报
        POST /nexus/update/check   {key,current_version}  拉取已分配的版本更新
        POST /nexus/update/report  {key,release_id,status,...} 上报更新结果
    管理（console 用，须 Authorization: Bearer <NEXUS_ADMIN_TOKEN>）：
        POST /nexus/admin/keys       {count,note,token_grant}  签发 KEY（明文仅此一次）
        POST /nexus/admin/revoke     {key_id}                  吊销 KEY
        GET  /nexus/admin/keys                                 KEY 列表
        GET  /nexus/admin/instances                            实例列表（含余额）
        POST /nexus/admin/topup      {instance_id,tokens,note} 手动充值
        GET  /nexus/admin/finance_summary                      资金经营汇总
        GET  /nexus/admin/payment_configs                      支付配置字段与验证状态
        POST /nexus/admin/payment_config {provider,config|action} 加密保存/重新验证
        GET  /nexus/admin/hierarchy                            OEM/用户完整归属边
        GET/POST /nexus/admin/releases                         版本发布中心
        GET  /nexus/admin/release_draft                        从 DEVLOG 自动生成版本草稿
        POST /nexus/admin/release_action                       灰度/全量/回撤/暂停/重试
    OEM 门户（须 OEM 会话，且所有数据按当前企业服务端隔离）：
        GET  /nexus/oem/me                                  自有实例/KEY/订单等总览
        GET  /nexus/oem/network                             自己的下级 OEM 与归属用户清单

安全：
    - NEXUS_ADMIN_TOKEN 无默认值，未配置则管理端点一律 503（宁停不裸奔）；
    - 兑换端点按 IP 限频（内存桶），防 KEY 爆破；
    - 生产部署躲在 Caddy 后面收 TLS，本服务只听内网。
"""

from __future__ import annotations

import hmac
import io
import json
import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, quote, urlsplit

from nexus import (
    audit,
    db,
    fleet,
    geo,
    manual_transfer,
    oem as oem_svc,
    pay,
    payment_config,
    releases,
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


def _admin_token() -> str:
    return os.environ.get("NEXUS_ADMIN_TOKEN", "").strip()


def _dash_token() -> str:
    """读取只读大屏令牌。

    独立函数让大屏鉴权与管理员鉴权保持清晰边界，避免以后为了“方便”再次把
    ``NEXUS_ADMIN_TOKEN`` 当成大屏令牌使用。
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
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # API 响应可能包含会话令牌、余额等敏感数据，任何层级都不应缓存。
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
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
        # 生产在 Caddy 后面，以 X-Forwarded-For 第一跳为准；直连时用对端地址
        fwd = (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        return fwd or (self.client_address[0] if self.client_address else "?")

    def _check_admin(self) -> bool:
        """管理端点鉴权。token 未配置一律拒绝——宁可停摆不可裸奔。"""
        expect = _admin_token()
        if not expect:
            self._err(503, "NEXUS_ADMIN_DISABLED", "NEXUS_ADMIN_TOKEN 未配置")
            return False
        got = self.headers.get("Authorization") or ""
        if not (got.startswith("Bearer ") and hmac.compare_digest(got[7:], expect)):
            self._err(401, "NEXUS_FORBIDDEN", "管理令牌无效")
            return False
        return True

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
        host = (self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or "").strip()
        host = host.split(",", 1)[0].strip()
        if not host or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-:" for c in host):
            raise FleetError("NEXUS_BAD_HOST", "请求 Host 不合法")
        forwarded = (self.headers.get("X-Forwarded-Proto") or "").split(",", 1)[0].strip()
        scheme = forwarded if forwarded in ("http", "https") else (
            "http" if host.startswith(("127.0.0.1", "localhost")) else "https"
        )
        return f"{scheme}://{host}"

    # ---- 路由 ----

    def do_GET(self) -> None:  # noqa: N802  # http.server 命名约定
        path = self.path.split("?", 1)[0]
        if path == "/nexus/health":
            self._json(200, {"ok": True, "ts": int(time.time() * 1000)})
            return
        if path == "/nexus/referral":
            qs = parse_qs(urlsplit(self.path).query)
            code = str((qs.get("code") or [""])[0])
            self._with_session(lambda s: self._json(200, oem_svc.referral_info(s, code)))
            return
        if path == "/nexus/admin/keys":
            if self._check_admin():
                self._with_session(lambda s: self._json(200, {"keys": fleet.list_keys(s)}))
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
                    lambda s: self._json(
                        200, {"releases": releases.list_releases(s)}
                    )
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
                    self._json(200, {"token": token})
                else:
                    self._err(
                        503,
                        "NEXUS_DASH_DISABLED",
                        "NEXUS_DASH_TOKEN 未配置",
                    )
            return
        if path == "/nexus/dash/summary":
            if self._check_dash():
                self._with_session(lambda s: self._json(200, fleet.dash_summary(s)))
            return
        # —— OEM 门户：登录后看自己的账号 + 实例 + KEY ——
        if path == "/nexus/oem/me":
            def _me(s):
                oem = self._oem(s)
                if oem is None:
                    return
                instances = oem_svc.my_instances(s, oem.id)
                self._json(
                    200,
                    {
                        "oem": oem_svc.public_oem(oem),
                        "instances": instances,
                        "keys": oem_svc.my_keys(s, oem.id),
                        "requests": oem_svc.my_requests(s, oem.id),
                        "orders": pay.my_orders(s, oem.id),
                        # 只返回该 OEM 名下节点已经成功安装的版本；它与上方 instances
                        # 使用同一归属边，但在业务层再次强制过滤，避免依赖前端隐藏。
                        "announcements": releases.list_oem_announcements(s, oem.id),
                        # 分享码与层级统计只在 OEM 登录后返回；链接按当前 Nexus 公网域名生成。
                        "referral": oem_svc.share_summary(
                            s, oem.id, self._public_origin()
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
                self._json(200, oem_svc.network_directory(s, account.id))

            self._with_session(_network)
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
                    {"pricing": pay.get_pricing(s), "channels": pay.channels(s)},
                )
            self._with_session(_products)
            return
        if path == "/nexus/admin/orders":
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(200, {"orders": pay.list_orders(s)})
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
        ".ico": "image/x-icon",
    }

    def _serve_dashboard(self, path: str) -> bool:
        """把 GET 路径映射到静态目录。返回是否已处理。

        路由：``/portal`` 前缀 → console/portal（控制台）；其余 → console/dashboard（大屏）。
        安全：normpath 后必须仍在对应目录内（掐死 ../ 穿越）；扩展名白名单。
        """
        # —— 控制台：/portal 或 /portal/xxx → console/portal/ ——
        if path == "/portal" or path.startswith("/portal/"):
            base_dir = self._PORTAL_DIR
            rel = path[len("/portal"):].lstrip("/") or "index.html"
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
            "camera=(), microphone=(), geolocation=(), payment=()",
        )
        if base_dir == self._DASH_DIR:
            # 大屏没有内联脚本，脚本来源可严格锁死到同源。样式保留 unsafe-inline 是因为
            # 地图坐标、颜色、柱高都通过 style 属性动态设置；它不放宽 JavaScript 执行。
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; "
                "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                "font-src 'self' data:; connect-src 'self'; object-src 'none'; "
                "base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
            )
        self.end_headers()
        self.wfile.write(data)
        return True

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]

        # —— LLM 网关：/gw/<厂商>/<原厂路径后缀>（体大且可能流式，独立处理）——
        if path.startswith("/gw/"):
            from nexus import gateway  # 延迟导入：fleet-only 部署可不装 requests

            parts = path[len("/gw/"):].split("/", 1)
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
                        {"file": oem_svc.add_oem_file(s, oem_id, filename, ctype, data)},
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
                    deployment_domain=str(
                        checkout_body.get("deployment_domain", "")
                    ),
                    purpose=str(checkout_body.get("purpose", "")),
                    expected_date=str(checkout_body.get("expected_date", "")),
                    requested_tokens=int(
                        checkout_body.get("requested_tokens") or 0
                    ),
                    image_data=image_data,
                    content_type=content_type,
                    filename=str(checkout_body.get("filename", "")),
                    transfer_details=details if isinstance(details, dict) else {},
                    source_ip=self._client_ip(),
                )
                self._json(201, result)

            self._with_session(_license_checkout)
            return

        body = self._read_body()

        if path == "/nexus/redeem":
            if not _rate_ok(self._client_ip()):
                self._err(429, "NEXUS_RATE_LIMIT", "尝试过于频繁，请一小时后再试")
                return

            def _redeem(s):
                out = fleet.redeem(
                    s,
                    str(body.get("key", "")),
                    str(body.get("domain", "")),
                    str(body.get("admin_email", "")),
                    str(body.get("region", "")),   # OEM 兑码时选的机房地域（大屏地图用）
                )
                # 装机成功后销毁申请单里存的交付明文（阅后即焚的"焚"时刻）
                oem_svc.clear_plain_by_key(s, str(body.get("key", "")))
                self._json(200, out)
            self._with_session(_redeem)
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

        # —— OEM 账号：注册 / 登录（免鉴权，按 IP 限频）/ 登出 / 认领 KEY ——
        if path in ("/nexus/oem/register", "/nexus/oem/login"):
            if not _auth_rate_ok(self._client_ip()):
                self._err(429, "NEXUS_RATE_LIMIT", "尝试过于频繁，请稍后再试")
                return
            if path == "/nexus/oem/register":
                self._with_session(
                    lambda s: self._json(
                        200,
                        {
                            "oem": oem_svc.register(
                                s,
                                str(body.get("email", "")),
                                str(body.get("password", "")),
                                str(body.get("name", "")),
                                inviter=str(body.get("inviter", "")),
                                company=str(body.get("company", "")),
                                contact_name=str(body.get("contact_name", "")),
                                phone=str(body.get("phone", "")),
                            )
                        },
                    )
                )
            else:
                self._with_session(
                    lambda s: self._json(
                        200,
                        oem_svc.login(
                            s,
                            str(body.get("email", "")),
                            str(body.get("password", "")),
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
                            requested_tokens=int(body.get("requested_tokens") or 0),
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
                        requested_tokens=int(body.get("requested_tokens") or 0),
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

        # —— Token 充值订单（KEY 必须走上方 license_checkout）——
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
                if kind == "topup" and not oem_svc.owns_instance(s, oem.id, int(inst or 0)):
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
                    lambda s: self._json(
                        200, {"pricing": pay.set_pricing(s, body)}
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
                        result = payment_config.save_and_verify(
                            s, provider, submitted
                        )
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
                    else:
                        raise FleetError(
                            "NEXUS_BAD_RELEASE_ACTION", "版本操作不合法"
                        )
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
                                token_grant=int(body.get("token_grant") or 0),
                                decide_note=str(body.get("decide_note", "")),
                                action=str(body.get("action", "")),
                                actor_label="平台超级管理员",
                                source_ip=self._client_ip(),
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
                            actor_label="平台超级管理员",
                            source_ip=self._client_ip(),
                        ),
                    )
                )
            return

        if path == "/nexus/admin/keys":
            if self._check_admin():
                def _issue(s):
                    issued = fleet.issue_keys(
                        s,
                        count=int(body.get("count") or 1),
                        note=str(body.get("note", "")),
                        token_grant=int(body.get("token_grant") or 0),
                    )
                    for item in issued:
                        audit.record(
                            s,
                            object_type="key",
                            object_id=item["id"],
                            action="issue",
                            actor_type="admin",
                            actor_label="平台超级管理员",
                            source_ip=self._client_ip(),
                            to_state="active",
                            note=str(body.get("note", "")),
                            metadata={
                                "token_grant": int(body.get("token_grant") or 0)
                            },
                        )
                    self._json(200, {"keys": issued})

                self._with_session(_issue)
            return

        if path == "/nexus/admin/revoke":
            if self._check_admin():
                def _do(s):
                    key_id = int(body.get("key_id") or 0)
                    reason = str(body.get("reason", "")).strip()
                    if not reason:
                        raise FleetError("NEXUS_REASON_REQUIRED", "永久吊销必须填写原因")
                    key_row = s.get(db.NexusKey, key_id)
                    old_status = key_row.status if key_row else ""
                    fleet.revoke_key(s, key_id)
                    audit.record(
                        s,
                        object_type="key",
                        object_id=key_id,
                        action="revoke",
                        actor_type="admin",
                        actor_label="平台超级管理员",
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
                        raise FleetError("NEXUS_REASON_REQUIRED", "暂停或恢复必须填写原因")
                    changed = fleet.set_key_status(s, key_id, target)
                    audit.record(
                        s,
                        object_type="key",
                        object_id=key_id,
                        action="resume" if target == "active" else "suspend",
                        actor_type="admin",
                        actor_label="平台超级管理员",
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
                self._with_session(
                    lambda s: self._json(
                        200,
                        {
                            "balance_tokens": fleet.topup(
                                s,
                                int(body.get("instance_id") or 0),
                                int(body.get("tokens") or 0),
                                str(body.get("note", "")),
                            )
                        },
                    )
                )
            return

        self._err(404, "NEXUS_UNKNOWN", "未知端点")

    # ---- Session 包装：业务错误→JSON，未知错误→500 且不泄内部细节 ----

    def _with_session(self, fn) -> None:
        s = db.session()
        try:
            fn(s)
            s.commit()
        except FleetError as e:
            s.rollback()
            self._err(e.http_status, e.code, e.message)
        except Exception:
            s.rollback()
            logger.exception("nexus 内部错误 %s", self.path)
            self._err(500, "NEXUS_INTERNAL", "内部错误")
        finally:
            s.close()


def run(host: str = "", port: int = 0) -> None:
    """启动 Nexus 服务（阻塞）。默认 127.0.0.1:9100，可用 env 覆盖。"""
    host = host or os.environ.get("NEXUS_LISTEN_HOST", "127.0.0.1")
    port = port or int(os.environ.get("NEXUS_LISTEN_PORT", "9100"))
    db.init_engine()
    if not _admin_token():
        logger.warning("NEXUS_ADMIN_TOKEN 未配置——管理端点将全部返回 503")
    srv = ThreadingHTTPServer((host, port), NexusHandler)
    logger.info("GuDuu Nexus fleet 服务监听 %s:%s", host, port)
    srv.serve_forever()
