"""Nexus 平台功能开关测试。

使用内存 SQLite 验证缺省关闭、持久化、白名单和服务端访问守卫，不触碰生产库。
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from typing import Any, Dict, Optional
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from nexus import admin_auth, db, features, oem
from nexus.fleet import FleetError
from nexus.service import NexusHandler


class FeatureFlagTests(unittest.TestCase):
    """平台功能开关必须默认保守关闭，并且只能由合法布尔值改变。"""

    def setUp(self) -> None:
        """为每条测试建立独立内存数据库。"""
        db.init_engine("sqlite:///:memory:")
        self.s = db.session()

    def tearDown(self) -> None:
        """关闭会话，避免连接资源泄漏。"""
        self.s.close()

    def test_network_visibility_defaults_off_and_persists(self) -> None:
        """缺少设置行时必须关闭；超管开启后立即从数据库读回。"""
        self.assertEqual(
            features.get_flags(self.s),
            {
                "oem_network_visible": False,
                "oem_token_grant_request_visible": False,
            },
        )
        result = features.set_flags(self.s, {"oem_network_visible": True})
        self.s.commit()
        self.assertTrue(result["oem_network_visible"])
        self.assertTrue(features.get_flags(self.s)["oem_network_visible"])

    def test_network_guard_rejects_when_off_and_allows_when_on(self) -> None:
        """OEM 不能绕过隐藏菜单直接调用受控数据接口。"""
        with self.assertRaises(FleetError) as raised:
            features.require_oem_network_visible(self.s)
        self.assertEqual(raised.exception.http_status, 403)
        self.assertEqual(raised.exception.code, "NEXUS_FEATURE_DISABLED")
        features.set_flags(self.s, {"oem_network_visible": True})
        features.require_oem_network_visible(self.s)

    def test_rejects_unknown_or_non_boolean_values(self) -> None:
        """拼错字段或用字符串冒充布尔值都不能写入平台配置。"""
        with self.assertRaises(FleetError):
            features.set_flags(self.s, {"unknown": True})
        with self.assertRaises(FleetError):
            features.set_flags(self.s, {"oem_network_visible": "true"})


class FeatureFlagHttpTests(unittest.TestCase):
    """用真实 HTTP 处理器验证 OEM 响应裁剪和超管开关端点。"""

    def setUp(self) -> None:
        """建立临时数据库、OEM 会话和随机本机端口服务。"""
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        db.init_engine("sqlite:///" + self._tmp.name)
        # 批准授权会创建加密交付记录；测试使用独立临时密钥，
        # 不读取、也不污染开发机或生产的 NEXUS_SECRET_KEY。
        self._old_secret = os.environ.get("NEXUS_SECRET_KEY")
        os.environ["NEXUS_SECRET_KEY"] = (
            "feature-flag-http-test-secret-at-least-32-bytes"
        )
        s = db.session()
        oem.register(
            s,
            "feature@example.com",
            "abc12345",
            inviter="GUDUU",
            company="功能开关测试企业",
            contact_name="测试人",
            phone="13800000000",
        )
        self.oem_token = oem.login(s, "feature@example.com", "abc12345")["token"]
        admin_auth.create_admin(
            s,
            "feature-owner",
            "Feature1234!",
            "功能开关管理员",
            actor_label="测试引导",
        )
        self.admin_token = admin_auth.login(
            s, "feature-owner", "Feature1234!"
        )["token"]
        s.commit()
        s.close()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), NexusHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        """关闭测试服务、恢复环境变量并删除临时数据库。"""
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        if self._old_secret is None:
            os.environ.pop("NEXUS_SECRET_KEY", None)
        else:
            os.environ["NEXUS_SECRET_KEY"] = self._old_secret
        os.unlink(self._tmp.name)

    def _json_request(
        self,
        path: str,
        token: str,
        body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """发送带 Bearer 的 JSON 请求并解析响应。"""
        raw = json.dumps(body).encode("utf-8") if body is not None else None
        request = Request(
            self.base_url + path,
            data=raw,
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
            },
        )
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_oem_network_hidden_until_admin_enables_it(self) -> None:
        """关闭时隐藏统计和目录但保留分享二维码；开启后目录恢复。"""
        me = self._json_request("/nexus/oem/me", self.oem_token)
        self.assertEqual(
            me["features"],
            {
                "oem_network_visible": False,
                "oem_token_grant_request_visible": False,
            },
        )
        self.assertTrue(me["referral"]["code"])
        self.assertIn("invite=", me["referral"]["partner_link"])
        for hidden_key in (
            "level",
            "ancestors",
            "direct_oems",
            "total_downline_oems",
            "direct_users",
            "network_users",
        ):
            self.assertNotIn(hidden_key, me["referral"])

        with self.assertRaises(HTTPError) as raised:
            self._json_request("/nexus/oem/network", self.oem_token)
        self.assertEqual(raised.exception.code, 403)
        payload = json.loads(raised.exception.read().decode("utf-8"))
        self.assertEqual(payload["errcode"], "NEXUS_FEATURE_DISABLED")

        # 二维码是邀请能力，不属于层级/用户数据开关；关闭时也必须生成成功。
        request = Request(
            self.base_url + "/nexus/oem/share_qr?kind=partner",
            headers={"Authorization": "Bearer " + self.oem_token},
        )
        with urlopen(request, timeout=10) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get_content_type(), "image/svg+xml")
            self.assertIn(b"<svg", response.read())

        admin = self._json_request(
            "/nexus/admin/features",
            self.admin_token,
            {"oem_network_visible": True},
        )
        self.assertTrue(admin["features"]["oem_network_visible"])
        directory = self._json_request("/nexus/oem/network", self.oem_token)
        self.assertEqual(directory["oem_total"], 0)
        self.assertEqual(directory["user_total"], 0)

    def test_oem_token_grant_defaults_to_zero_and_requires_admin_switch(self) -> None:
        """隐藏字段不能被手工 API 绕过；开启后才允许保存申请额度。"""
        hidden = self._json_request(
            "/nexus/oem/request_key",
            self.oem_token,
            {
                "deployment_domain": "token-off.example.com",
                "purpose": "验证默认关闭",
                "requested_tokens": 100_000_000,
            },
        )
        self.assertEqual(hidden["request"]["requested_tokens"], 0)

        # 超管即使手工构造非零批准请求，关闭状态下签发的 KEY 仍必须是零额度。
        self._json_request(
            "/nexus/admin/request_decide",
            self.admin_token,
            {
                "request_id": hidden["request"]["id"],
                "action": "approve",
                "approve": True,
                "token_grant": 100_000_000,
            },
        )
        me = self._json_request("/nexus/oem/me", self.oem_token)
        self.assertEqual(me["keys"][0]["token_grant"], 0)

        enabled = self._json_request(
            "/nexus/admin/features",
            self.admin_token,
            {"oem_token_grant_request_visible": True},
        )
        self.assertTrue(
            enabled["features"]["oem_token_grant_request_visible"]
        )
        visible = self._json_request(
            "/nexus/oem/request_key",
            self.oem_token,
            {
                "deployment_domain": "token-on.example.com",
                "purpose": "验证超管开启",
                "requested_tokens": 12_345,
            },
        )
        self.assertEqual(visible["request"]["requested_tokens"], 12_345)


if __name__ == "__main__":
    unittest.main()
