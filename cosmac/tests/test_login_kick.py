# -*- coding: utf-8 -*-
"""单端在线(后踢前)单测:登录成功踢其它设备 / 两步 UIA / 被踢记录查询 / 失败不影响登录。

负责人需求:同一账号跨浏览器登录时,后登录的把先登录的踢下线,旧端提示"账号已在别处登录"。
Synapse 交互全打桩(requests.get/post),聚焦 _kick_other_devices / was_kicked 逻辑。

运行:.venv/bin/python -m unittest cosmac.tests.test_login_kick
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, List
from unittest import mock

from cosmac import registration


class _Resp:
    """极简 requests 响应桩。"""

    def __init__(self, status_code: int, body: Dict[str, Any]) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> Dict[str, Any]:
        return self._body


PAYLOAD = {
    "access_token": "tok_new",
    "device_id": "DEVNEW",
    "user_id": "@u:h",
}


class TestKickOtherDevices(unittest.TestCase):
    def setUp(self) -> None:
        # 每个用例清空被踢记录,互不串扰
        registration._kicked_devices.clear()

    def test_kicks_others_with_two_step_uia(self) -> None:
        """标准路径:列设备→UIA 第一步 401 拿 session→第二步带密码删成功→记录被踢。"""
        posts: List[Dict[str, Any]] = []

        def fake_get(url, **kw):
            self.assertIn("/devices", url)
            return _Resp(200, {"devices": [
                {"device_id": "DEVOLD1"}, {"device_id": "DEVOLD2"},
                {"device_id": "DEVNEW"},  # 新设备自己要排除
            ]})

        def fake_post(url, json=None, **kw):
            posts.append(json or {})
            if "auth" not in (json or {}):
                return _Resp(401, {"session": "sess1", "flows": []})
            return _Resp(200, {})

        with mock.patch.object(registration.requests, "get", fake_get), \
             mock.patch.object(registration.requests, "post", fake_post):
            registration._kick_other_devices("http://hs", "u", "pw", dict(PAYLOAD))

        # 两步 UIA:第一步裸提交,第二步带密码+session
        self.assertEqual(len(posts), 2)
        self.assertEqual(sorted(posts[0]["devices"]), ["DEVOLD1", "DEVOLD2"])
        auth = posts[1]["auth"]
        self.assertEqual(auth["type"], "m.login.password")
        self.assertEqual(auth["password"], "pw")
        self.assertEqual(auth["session"], "sess1")
        # 被踢的两台都可查到;新设备自己不算被踢
        self.assertTrue(registration.was_kicked("@u:h", "DEVOLD1"))
        self.assertTrue(registration.was_kicked("@u:h", "DEVOLD2"))
        self.assertFalse(registration.was_kicked("@u:h", "DEVNEW"))

    def test_no_other_devices_noop(self) -> None:
        """只有本次登录这一台设备 → 不发删除请求。"""
        posts: List[Any] = []
        with mock.patch.object(registration.requests, "get",
                               lambda url, **kw: _Resp(200, {"devices": [{"device_id": "DEVNEW"}]})), \
             mock.patch.object(registration.requests, "post",
                               lambda *a, **kw: posts.append(1) or _Resp(200, {})):
            registration._kick_other_devices("http://hs", "u", "pw", dict(PAYLOAD))
        self.assertEqual(posts, [])

    def test_delete_failure_swallowed(self) -> None:
        """删设备失败(403 等)→ 不抛异常、不记录被踢——绝不影响登录主流程。"""
        with mock.patch.object(registration.requests, "get",
                               lambda url, **kw: _Resp(200, {"devices": [
                                   {"device_id": "DEVOLD"}, {"device_id": "DEVNEW"}]})), \
             mock.patch.object(registration.requests, "post",
                               lambda *a, **kw: _Resp(403, {})):
            registration._kick_other_devices("http://hs", "u", "pw", dict(PAYLOAD))
        self.assertFalse(registration.was_kicked("@u:h", "DEVOLD"))

    def test_network_error_swallowed(self) -> None:
        """网络异常 → 吞掉不抛(best-effort)。"""
        def boom(*a, **kw):
            raise registration.requests.RequestException("net down")
        with mock.patch.object(registration.requests, "get", boom):
            registration._kick_other_devices("http://hs", "u", "pw", dict(PAYLOAD))  # 不应抛

    def test_was_kicked_ttl_expiry(self) -> None:
        """被踢记录超过 TTL → 查询返回 False 且条目被清。"""
        registration._record_kicked("@u:h", ["DEVX"])
        key = ("@u:h", "DEVX")
        registration._kicked_devices[key] = 1.0  # 伪造成远古时刻
        self.assertFalse(registration.was_kicked("@u:h", "DEVX"))
        self.assertNotIn(key, registration._kicked_devices)

    def test_was_kicked_unknown(self) -> None:
        self.assertFalse(registration.was_kicked("@nobody:h", "DEV"))
        self.assertFalse(registration.was_kicked("", ""))


class TestSingleSessionSwitch(unittest.TestCase):
    """单端在线开关:默认关(多设备同时在线),置 COSMAC_SINGLE_SESSION=1 才启用互踢。"""

    def test_default_off_multi_device(self) -> None:
        import os
        for k in ("COSMAC_SINGLE_SESSION", "GUDUU_SINGLE_SESSION"):
            os.environ.pop(k, None)
        self.assertFalse(registration._single_session_enabled())  # 默认多设备

    def test_enabled_by_env(self) -> None:
        import os
        with mock.patch.dict(os.environ, {"COSMAC_SINGLE_SESSION": "1"}):
            self.assertTrue(registration._single_session_enabled())
        with mock.patch.dict(os.environ, {"COSMAC_SINGLE_SESSION": "true"}):
            self.assertTrue(registration._single_session_enabled())
        with mock.patch.dict(os.environ, {"COSMAC_SINGLE_SESSION": "0"}):
            self.assertFalse(registration._single_session_enabled())


if __name__ == "__main__":
    unittest.main()
