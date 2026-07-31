"""SSRF 防护：云元数据地址必须永远拒绝 —— 安全回归测试。

2026-07-27 排查 WebFetch 风险时发现的真实漏洞：
RFC 6598 网段中的元数据地址 100.100.100.200 属 RFC 6598 运营商级 NAT (100.64.0.0/10)，
而 Python 的 ipaddress **不**把这一段判为 is_private，于是被当普通公网放行。
若部署环境暴露该端点，就会留下可读取云临时凭据的 SSRF 通道。

运行：.venv/bin/python -m unittest cosmac.tests.test_ssrf_metadata
"""

from __future__ import annotations

import ipaddress
import unittest

from cosmac.wf import _is_metadata_addr, check_outbound_url


class MetadataAddrTest(unittest.TestCase):
    def test_aliyun_metadata_is_blocked(self) -> None:
        """本项目生产环境所在的云——这条要是漏了，代价是实例凭据。"""
        self.assertTrue(_is_metadata_addr(ipaddress.ip_address("100.100.100.200")))

    def test_whole_carrier_nat_range_is_blocked(self) -> None:
        """整段拦掉而不是只拦那一个 IP：同段内还有别的内部服务端点。"""
        for ip in ("100.64.0.0", "100.64.0.1", "100.100.100.200", "100.127.255.255"):
            self.assertTrue(_is_metadata_addr(ipaddress.ip_address(ip)), ip)

    def test_public_addresses_are_not_blocked(self) -> None:
        """别误伤正常公网——尤其 100.64/10 的边界外要放行。"""
        for ip in ("8.8.8.8", "185.199.108.133", "100.63.255.255", "100.128.0.0", "1.1.1.1"):
            self.assertFalse(_is_metadata_addr(ipaddress.ip_address(ip)), ip)

    def test_aws_ipv6_metadata_is_blocked(self) -> None:
        self.assertTrue(_is_metadata_addr(ipaddress.ip_address("fd00:ec2::254")))


class CheckOutboundUrlTest(unittest.TestCase):
    """端到端：check_outbound_url 对危险目标的最终判定。"""

    def _reject_reason(self, host: str) -> str:
        """host 直接是 IP 时不触发 DNS，判定路径与真实一致。"""
        return check_outbound_url(f"https://{host}/x")

    def test_metadata_rejected_even_with_allow_internal(self) -> None:
        """⚠️ 关键：开了「允许内网」也不能放行元数据。

        自建内网工作流是合理诉求，但那从不包含"打元数据拿凭据"。
        """
        import os

        old = os.environ.get("COSMAC_WF_ALLOW_INTERNAL")
        os.environ["COSMAC_WF_ALLOW_INTERNAL"] = "1"
        try:
            reason = check_outbound_url("https://100.100.100.200/latest/meta-data/")
            self.assertNotEqual(reason, "", "开了内网开关也绝不能放行元数据")
            self.assertIn("元数据", reason)
        finally:
            if old is None:
                os.environ.pop("COSMAC_WF_ALLOW_INTERNAL", None)
            else:
                os.environ["COSMAC_WF_ALLOW_INTERNAL"] = old

    def test_loopback_and_private_still_rejected_by_default(self) -> None:
        for host in ("127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254"):
            self.assertNotEqual(self._reject_reason(host), "", host)



class FetchUrlToolTest(unittest.TestCase):
    """自研 fetch_url：替代被拉黑的 SDK WebFetch，能力等价但走 SSRF 防护。"""

    def _box(self):
        from cosmac.ai.tools import Toolbox

        class _C:
            def resolve_alias(self, a):
                return "!ctrl:h"

            def get_state_event(self, *a, **k):
                return None

        return Toolbox(_C())

    def _run(self, url):
        from cosmac.ai.tools import ToolCall, ToolContext

        box = self._box()
        return box.execute(
            ToolCall(id="t", name="fetch_url", arguments={"url": url}),
            ToolContext(room_id="!r:h", sender="@u:h"),
        )

    def test_blocks_internal_and_metadata(self) -> None:
        """核心：容器内网与云元数据必须抓不到。

        这正是拉黑 SDK WebFetch 的理由——实测 bot 容器可直连 synapse:8008，
        RFC 6598 元数据端点还能吐 RAM 临时凭据。
        """
        for bad in (
            "http://127.0.0.1/x",
            "http://10.0.0.5/x",
            "http://169.254.169.254/latest/meta-data/",
            "http://100.100.100.200/latest/meta-data/",   # 已退役云环境
        ):
            out = self._run(bad)
            self.assertIn("不能抓取", out, f"{bad} 必须被拒")

    def test_rejects_bad_scheme(self) -> None:
        for bad in ("file:///etc/passwd", "ftp://x/y", "gopher://x"):
            self.assertIn("不能抓取", self._run(bad))

    def test_requires_url(self) -> None:
        self.assertIn("请给出", self._run("  "))

    def test_html_is_stripped_to_text(self) -> None:
        """返回纯文本：script/style 整段丢掉，标签去净——省 token 也更好读。"""
        import sys
        import types

        from cosmac.ai.tools import ToolCall, ToolContext

        html = (b"<html><head><style>.a{color:red}</style>"
                b"<script>alert('x')</script></head>"
                b"<body><h1>\xe6\xa0\x87\xe9\xa2\x98</h1><p>\xe6\xad\xa3\xe6\x96\x87</p></body></html>")

        class _Raw:
            """模拟 urllib3 HTTPResponse：fetch_url 现在走 stream 模式手动 raw.read。"""
            _connection = None  # 无底层连接 → verify_connected_peer 放行(拿不到不拦)

            def read(self, amt=None, decode_content=True):
                return html

        class _R:
            content, status_code, encoding, headers = html, 200, "utf-8", {}
            raw = _Raw()

            def close(self):
                pass

        fake = types.ModuleType("requests")
        fake.get = lambda url, **k: _R()
        old = sys.modules.get("requests")
        sys.modules["requests"] = fake
        try:
            box = self._box()
            # 绕开 DNS/SSRF（本用例只验文本处理）；防护本身另有用例覆盖
            import cosmac.wf as wf
            old_chk = wf.check_outbound_url
            wf.check_outbound_url = lambda u: ""
            try:
                out = box.execute(ToolCall(
                    id="t", name="fetch_url", arguments={"url": "https://example.com/a"},
                ), ToolContext(room_id="!r:h", sender="@u:h"))
            finally:
                wf.check_outbound_url = old_chk
        finally:
            if old is not None:
                sys.modules["requests"] = old
            else:
                sys.modules.pop("requests", None)
        self.assertIn("标题", out)
        self.assertIn("正文", out)
        self.assertNotIn("alert", out, "script 内容必须丢掉")
        self.assertNotIn("color:red", out, "style 内容必须丢掉")
        self.assertNotIn("<", out, "标签要去净")


class VerifyConnectedPeerTest(unittest.TestCase):
    """连接后对端校验（堵 DNS rebinding）：域名先解析到公网过 check_outbound_url、
    再 rebind 到内网/元数据的，必须在读 body 前被掐断。"""

    @staticmethod
    def _resp_with_peer(peer_ip):
        """造一个带底层 socket 的假 requests 响应（getpeername 返回指定 IP）。"""
        class _Sock:
            def getpeername(self):
                return (peer_ip, 443)

        class _Conn:
            sock = _Sock()

        class _Raw:
            _connection = _Conn()

        class _R:
            raw = _Raw()

        return _R()

    def test_rebind_to_metadata_rejected(self) -> None:
        """rebind 到RFC 6598 元数据端点——最值钱的目标，必须拒绝。"""
        from cosmac.wf import verify_connected_peer

        reason = verify_connected_peer(self._resp_with_peer("100.100.100.200"))
        self.assertNotEqual(reason, "")
        self.assertIn("元数据", reason)

    def test_rebind_to_internal_rejected(self) -> None:
        from cosmac.wf import verify_connected_peer

        for ip in ("127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254"):
            self.assertNotEqual(
                verify_connected_peer(self._resp_with_peer(ip)), "", ip
            )

    def test_public_peer_allowed(self) -> None:
        from cosmac.wf import verify_connected_peer

        self.assertEqual(verify_connected_peer(self._resp_with_peer("8.8.8.8")), "")

    def test_missing_socket_does_not_block(self) -> None:
        """底层 socket 拿不到(urllib3 版本差异)时放行——绝不能让正常抓取全挂。"""
        from cosmac.wf import verify_connected_peer

        class _R:
            raw = None

        self.assertEqual(verify_connected_peer(_R()), "")

    def test_proxy_peer_not_blocked(self) -> None:
        """走代理时对端是代理自己(常见本机 127.0.0.1)——必须豁免，否则代理环境全误杀。

        用显式 env 构造(不依赖开发机是否真配了代理)，NO_PROXY 语义也一并验证。
        """
        import os

        from cosmac.wf import verify_connected_peer

        resp = self._resp_with_peer("127.0.0.1")  # 对端=本机代理

        class _Req:
            url = "https://example.com/x"

        resp.request = _Req()
        saved = {k: os.environ.get(k) for k in
                 ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
                  "NO_PROXY", "no_proxy")}
        try:
            os.environ["HTTPS_PROXY"] = "http://127.0.0.1:1082"
            os.environ.pop("NO_PROXY", None)
            os.environ.pop("no_proxy", None)
            # 配了代理 → 对端是代理，豁免放行
            self.assertEqual(verify_connected_peer(resp), "")
            # 目标在 NO_PROXY 里 → 不走代理，对端就是目标本身，校验必须照常拦
            os.environ["NO_PROXY"] = "example.com"
            self.assertNotEqual(verify_connected_peer(resp), "")
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


if __name__ == "__main__":
    unittest.main()
