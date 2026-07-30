"""LLM 网关集成测试：假上游 + 真 Nexus 服务（双线程），全链路走真 HTTP。

覆盖：
  - openai 非流式：透传响应 + 换真 key + 按 usage 扣钱包 + 流水备注；
  - anthropic 流式(SSE)：chunked 回传 + 从事件流解析用量扣账；
  - 拒绝矩阵：无 KEY(401)/吊销(403)/零余额(402)/白名单外路径(403)/
    未知厂商(404)/原厂 key 未配置(503)。

跑法（项目根）： .venv/bin/python -m unittest nexus.tests.test_gateway -v
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests
from sqlalchemy import select

from nexus import db, fleet
from nexus.db import NexusLedger
from nexus.service import NexusHandler


class _FakeUpstream(BaseHTTPRequestHandler):
    """假原厂：记录收到的鉴权头，按路径/body 回 JSON 或 SSE。"""

    seen_headers: list = []  # 类变量：测试断言网关换了真 key
    hold_started = threading.Event()  # 并发测试：第一条请求已进入原厂
    hold_release = threading.Event()  # 并发测试：允许第一条请求返回

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        _FakeUpstream.seen_headers.append(
            {
                "path": self.path,
                "x-api-key": self.headers.get("x-api-key"),
                "authorization": self.headers.get("Authorization"),
            }
        )
        if self.path == "/v1/chat/completions":
            if body.get("model") == "hold":
                # 故意把第一条模型请求悬住，给第二条同实例请求制造稳定的并发窗口。
                _FakeUpstream.hold_started.set()
                _FakeUpstream.hold_release.wait(timeout=5)
            payload = json.dumps(
                {
                    "choices": [{"message": {"content": "hi"}}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 50},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path == "/v1/messages":
            if body.get("stream"):
                # anthropic 流式：message_start 带输入、message_delta 带输出
                events = (
                    'data: {"type":"message_start","message":{"usage":{"input_tokens":10}}}\n\n'
                    'data: {"type":"content_block_delta","delta":{"text":"你好"}}\n\n'
                    'data: {"type":"message_delta","usage":{"output_tokens":5}}\n\n'
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(events)))
                self.end_headers()
                self.wfile.write(events)
                return
            payload = json.dumps(
                {
                    "content": [{"type": "text", "text": "hello"}],
                    "usage": {"input_tokens": 200, "output_tokens": 80},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *a):  # 静音
        pass


class GatewayTest(unittest.TestCase):
    upstream_srv: ThreadingHTTPServer
    nexus_srv: ThreadingHTTPServer

    @classmethod
    def setUpClass(cls):
        # 独立临时库
        cls._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls._tmp.close()
        db.init_engine("sqlite:///" + cls._tmp.name)
        # 假上游 + 真 Nexus 服务，各占一个随机端口
        cls.upstream_srv = ThreadingHTTPServer(("127.0.0.1", 0), _FakeUpstream)
        cls.nexus_srv = ThreadingHTTPServer(("127.0.0.1", 0), NexusHandler)
        for srv in (cls.upstream_srv, cls.nexus_srv):
            threading.Thread(target=srv.serve_forever, daemon=True).start()
        up = f"http://127.0.0.1:{cls.upstream_srv.server_address[1]}"
        cls.base = f"http://127.0.0.1:{cls.nexus_srv.server_address[1]}"
        # 网关厂商配置：openai/anthropic 指向假上游；ark 故意不配 key（测 503）
        cls._env = {
            "NEXUS_GW_OPENAI_BASE": up,
            "NEXUS_GW_OPENAI_KEY": "vk-openai-real",
            "NEXUS_GW_ANTHROPIC_BASE": up,
            "NEXUS_GW_ANTHROPIC_KEY": "vk-anth-real",
        }
        os.environ.update(cls._env)
        os.environ.pop("NEXUS_GW_ARK_KEY", None)

    @classmethod
    def tearDownClass(cls):
        cls.upstream_srv.shutdown()
        cls.nexus_srv.shutdown()
        for k in cls._env:
            os.environ.pop(k, None)
        os.unlink(cls._tmp.name)

    def _new_instance(self, grant: int) -> str:
        """签发+兑换一个新实例，返回 OEM KEY 明文。"""
        s = db.session()
        try:
            key = fleet.issue_keys(s, token_grant=grant)[0]["key"]
            fleet.redeem(s, key, f"im.gw-{key[-4:].lower()}.test")
            s.commit()
            return key
        finally:
            s.close()

    def _balance(self, key: str) -> int:
        s = db.session()
        try:
            out = fleet.heartbeat(s, key)
            s.commit()
            return out["balance_tokens"]
        finally:
            s.close()

    # ---- 正向 ----

    def test_openai_nonstream_meter_and_debit(self):
        key = self._new_instance(grant=1000)
        r = requests.post(
            f"{self.base}/gw/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": "gpt-4o", "messages": []},
            timeout=10,
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["choices"][0]["message"]["content"], "hi")
        # 换成了真 key（绝不透传实例的 OEM KEY）
        self.assertEqual(
            _FakeUpstream.seen_headers[-1]["authorization"], "Bearer vk-openai-real"
        )
        # 扣账：100+50
        self.assertEqual(self._balance(key), 850)
        s = db.session()
        try:
            notes = [
                r0.note
                for r0 in s.execute(select(NexusLedger)).scalars().all()
                if r0.kind == "usage"
            ]
            self.assertTrue(any("openai/gpt-4o in=100 out=50" in n for n in notes))
        finally:
            s.close()

    def test_anthropic_stream_meter(self):
        key = self._new_instance(grant=1000)
        r = requests.post(
            f"{self.base}/gw/anthropic/v1/messages",
            headers={"x-api-key": key},
            json={"model": "claude-x", "stream": True},
            timeout=10,
            stream=True,
        )
        self.assertEqual(r.status_code, 200)
        text = r.raw.read().decode()
        self.assertIn("content_block_delta", text)  # 事件流原样到达
        self.assertEqual(
            _FakeUpstream.seen_headers[-1]["x-api-key"], "vk-anth-real"
        )
        self.assertEqual(self._balance(key), 985)  # 1000 - (10+5)

    def test_same_instance_concurrent_request_is_rejected(self):
        """同一实例已有在途模型调用时，第二条必须 429，且只产生一次原厂扣费。"""
        key = self._new_instance(grant=100)
        _FakeUpstream.hold_started.clear()
        _FakeUpstream.hold_release.clear()
        first_result = {}

        def first_request() -> None:
            """发起会被假原厂悬住的第一条请求。"""
            first_result["response"] = requests.post(
                f"{self.base}/gw/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": "hold", "messages": []},
                timeout=10,
            )

        worker = threading.Thread(target=first_request)
        worker.start()
        self.assertTrue(_FakeUpstream.hold_started.wait(timeout=3))
        try:
            second = requests.post(
                f"{self.base}/gw/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": "gpt-4o", "messages": []},
                timeout=3,
            )
            self.assertEqual(second.status_code, 429)
            self.assertEqual(second.json()["errcode"], "NEXUS_GW_CONCURRENT")
        finally:
            _FakeUpstream.hold_release.set()
            worker.join(timeout=5)

        self.assertFalse(worker.is_alive())
        self.assertEqual(first_result["response"].status_code, 200)
        # 第一单用量 150，可按既定后付语义把 100 扣到 -50；第二单没有打到原厂、没有扣费。
        self.assertEqual(self._balance(key), -50)

    # ---- 拒绝矩阵 ----

    def _post(self, path: str, key: str = "", **kw):
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        return requests.post(
            f"{self.base}{path}", headers=headers, json={"model": "m"}, timeout=10, **kw
        )

    def test_reject_matrix(self):
        # 无 KEY
        self.assertEqual(
            self._post("/gw/openai/v1/chat/completions").status_code, 401
        )
        # 零余额 → 402（唯一续费抓手的执行点）
        broke = self._new_instance(grant=0)
        r = self._post("/gw/openai/v1/chat/completions", broke)
        self.assertEqual(r.status_code, 402)
        self.assertEqual(r.json()["errcode"], "NEXUS_GW_NO_BALANCE")
        # 吊销 → 403
        rich = self._new_instance(grant=100)
        s = db.session()
        try:
            kid = [k for k in fleet.list_keys(s) if k["tail"] == rich[-4:]][0]["id"]
            fleet.revoke_key(s, kid)
            s.commit()
        finally:
            s.close()
        self.assertEqual(
            self._post("/gw/openai/v1/chat/completions", rich).status_code, 403
        )
        # 白名单外路径 → 403（保护原厂 key 不被挪用）
        ok = self._new_instance(grant=100)
        r = self._post("/gw/openai/v1/files", ok)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["errcode"], "NEXUS_GW_PATH_DENIED")
        # 未知厂商 → 404；原厂 key 未配置(ark) → 503
        self.assertEqual(self._post("/gw/nope/v1/x", ok).status_code, 404)
        self.assertEqual(
            self._post("/gw/ark/chat/completions", ok).status_code, 503
        )
        # 拒绝的调用一分钱不扣
        self.assertEqual(self._balance(ok), 100)


if __name__ == "__main__":
    unittest.main()
