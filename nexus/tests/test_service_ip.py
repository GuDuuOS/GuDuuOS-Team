"""Nexus 真实来源 IP 的信任边界回归测试。"""

from __future__ import annotations

import unittest

from nexus.service import NexusHandler


class ClientIpTests(unittest.TestCase):
    """只有本机 Caddy 可把已净化的 X-Real-IP 交给 Nexus。"""

    @staticmethod
    def _handler(peer: str, headers: dict):
        """构造不启动 HTTP 服务的最小 handler，专测纯 IP 解析逻辑。"""
        handler = object.__new__(NexusHandler)
        handler.client_address = (peer, 12345)
        handler.headers = headers
        return handler

    def test_loopback_caddy_can_supply_single_real_ip(self) -> None:
        """宿主 Caddy 的覆盖头可用于严格 IP 绑定。"""
        handler = self._handler("127.0.0.1", {"X-Real-IP": "203.0.113.8"})
        self.assertEqual(handler._client_ip(), "203.0.113.8")

    def test_loopback_prefers_nexus_specific_real_ip(self) -> None:
        """Caddy 2.6 用项目专属头传递 Cloudflare 还原后的地址。"""
        handler = self._handler(
            "127.0.0.1",
            {
                "X-Nexus-Client-IP": "203.0.113.9",
                "X-Real-IP": "172.69.1.2",
            },
        )
        self.assertEqual(handler._client_ip(), "203.0.113.9")

    def test_public_peer_cannot_spoof_forwarded_headers(self) -> None:
        """绕过 Caddy 的请求不能借 XFF/X-Real-IP 伪造来源。"""
        handler = self._handler(
            "198.51.100.7",
            {"X-Forwarded-For": "203.0.113.8", "X-Real-IP": "203.0.113.8"},
        )
        self.assertEqual(handler._client_ip(), "198.51.100.7")

    def test_loopback_rejects_malformed_real_ip(self) -> None:
        """异常反代头不能污染审计，安全回退为本机对端。"""
        handler = self._handler("::1", {"X-Real-IP": "203.0.113.8, 10.0.0.1"})
        self.assertEqual(handler._client_ip(), "::1")
