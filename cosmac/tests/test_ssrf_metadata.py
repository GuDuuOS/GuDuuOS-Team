"""SSRF 防护：云元数据地址必须永远拒绝 —— 安全回归测试。

2026-07-27 排查 WebFetch 风险时发现的真实漏洞：
阿里云的元数据地址 100.100.100.200 属 RFC 6598 运营商级 NAT (100.64.0.0/10)，
而 Python 的 ipaddress **不**把这一段判为 is_private，于是被当普通公网放行。
本项目生产就跑在阿里云上——等于给 SSRF 留了一条直通元数据、可取 RAM 临时凭据的路。

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
        阿里云元数据还能吐 RAM 临时凭据。
        """
        for bad in (
            "http://127.0.0.1/x",
            "http://10.0.0.5/x",
            "http://169.254.169.254/latest/meta-data/",
            "http://100.100.100.200/latest/meta-data/",   # 阿里云
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

        class _R:
            content, status_code, encoding, headers = html, 200, "utf-8", {}

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


if __name__ == "__main__":
    unittest.main()
