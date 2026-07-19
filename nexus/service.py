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

from nexus import db, fleet
from nexus.fleet import FleetError

logger = logging.getLogger("nexus.service")

# ---------- 兑换限频（内存桶：单实例部署够用；多实例部署时换 Redis，P2 再说）----------
_BUCKET_LOCK = threading.Lock()
_BUCKET: Dict[str, list] = {}
_REDEEM_MAX_PER_HOUR = 10


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
        self._err(404, "NEXUS_UNKNOWN", "未知端点")

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
            self._with_session(
                lambda s: self._json(
                    200,
                    fleet.redeem(
                        s,
                        str(body.get("key", "")),
                        str(body.get("domain", "")),
                        str(body.get("admin_email", "")),
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
                    ),
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
