"""GuDuu Nexus HTTP 服务（fleet 端点）。

技术选型与 cosmac bot 保持一致：标准库 ThreadingHTTPServer + 同步逻辑，
不引入 Web 框架——单人维护，栈越少越好。

端点总览：
    公开（实例回连，凭 KEY 鉴权）：
        GET  /nexus/health                       探活
        POST /nexus/redeem     {key,domain,admin_email}   兑换开通（install.sh 调）
        POST /nexus/heartbeat  {key,version,stats}        心跳上报（实例定时调）
    管理（console 用，须 Authorization: Bearer <NEXUS_ADMIN_TOKEN>）：
        POST /nexus/admin/keys       {count,note,token_grant}  签发 KEY（明文仅此一次）
        POST /nexus/admin/revoke     {key_id}                  吊销 KEY
        GET  /nexus/admin/keys                                 KEY 列表
        GET  /nexus/admin/instances                            实例列表（含余额）
        POST /nexus/admin/topup      {instance_id,tokens,note} 手动充值

安全：
    - NEXUS_ADMIN_TOKEN 无默认值，未配置则管理端点一律 503（宁停不裸奔）；
    - 兑换端点按 IP 限频（内存桶），防 KEY 爆破；
    - 生产部署躲在 Caddy 后面收 TLS，本服务只听内网。
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict

from nexus import db, fleet, oem as oem_svc, pay
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
        """大屏端点鉴权：只读令牌 NEXUS_DASH_TOKEN（大屏挂墙上，权限与管理
        令牌分开——泄露只读令牌看得到数据、动不了 KEY 和钱包）；admin 令牌也放行。"""
        got = self.headers.get("Authorization") or ""
        token = got[7:] if got.startswith("Bearer ") else ""
        dash = os.environ.get("NEXUS_DASH_TOKEN", "").strip()
        admin = _admin_token()
        if dash and token and hmac.compare_digest(token, dash):
            return True
        if admin and token and hmac.compare_digest(token, admin):
            return True
        if not dash and not admin:
            self._err(503, "NEXUS_ADMIN_DISABLED", "NEXUS_DASH_TOKEN 未配置")
        else:
            self._err(401, "NEXUS_FORBIDDEN", "大屏令牌无效")
        return False

    # 屏蔽默认的逐请求 stderr 日志，统一走 logging
    def log_message(self, fmt: str, *args: Any) -> None:
        logger.info("%s %s", self._client_ip(), fmt % args)

    # ---- 路由 ----

    def do_GET(self) -> None:  # noqa: N802  # http.server 命名约定
        path = self.path.split("?", 1)[0]
        if path == "/nexus/health":
            self._json(200, {"ok": True, "ts": int(time.time() * 1000)})
            return
        if path == "/nexus/admin/keys":
            if self._check_admin():
                self._with_session(lambda s: self._json(200, {"keys": fleet.list_keys(s)}))
            return
        if path == "/nexus/admin/instances":
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(200, {"instances": fleet.list_instances(s)})
                )
            return
        if path == "/nexus/admin/oems":
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(200, {"oems": oem_svc.list_oems(s)})
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
                self._json(
                    200,
                    {
                        "oem": oem_svc.public_oem(oem),
                        "instances": oem_svc.my_instances(s, oem.id),
                        "keys": oem_svc.my_keys(s, oem.id),
                        "requests": oem_svc.my_requests(s, oem.id),
                        "orders": pay.my_orders(s, oem.id),
                    },
                )
            self._with_session(_me)
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
        if path == "/nexus/admin/pricing":
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(200, {"pricing": pay.get_pricing(s)})
                )
            return
        if path == "/nexus/admin/requests":
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(
                        200, {"requests": oem_svc.list_requests(s, status="pending")}
                    )
                )
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
                    {"request": oem_svc.request_key(s, oem.id, str(body.get("note", "")))},
                )
            self._with_session(_req)
            return

        # —— 在线购买/充值（订单创建；topup 校验实例归属）——
        if path == "/nexus/oem/order":
            def _order(s):
                oem = self._oem(s)
                if oem is None:
                    return
                kind = str(body.get("kind", ""))
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
                pay.mark_paid(s, info["order_no"], info.get("provider_txn", ""))
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
                            )
                        },
                    )
                )
            return

        if path == "/nexus/admin/keys":
            if self._check_admin():
                self._with_session(
                    lambda s: self._json(
                        200,
                        {
                            "keys": fleet.issue_keys(
                                s,
                                count=int(body.get("count") or 1),
                                note=str(body.get("note", "")),
                                token_grant=int(body.get("token_grant") or 0),
                            )
                        },
                    )
                )
            return

        if path == "/nexus/admin/revoke":
            if self._check_admin():
                def _do(s):
                    fleet.revoke_key(s, int(body.get("key_id") or 0))
                    self._json(200, {"ok": True})
                self._with_session(_do)
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
