"""MatrixClient 的鉴权方式回归测试。

重点守住一条安全红线：高权限的 appservice as_token **绝不能出现在 URL 查询参数里**
（否则会进 nginx/代理/错误日志），必须走 Authorization: Bearer 请求头。
"""

from __future__ import annotations

import unittest
from unittest import mock

import requests

from cosmac.bots.matrix_client import MatrixClient


class _Resp:
    """最小化的假 requests 响应。"""

    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class TestJoinedMemberCount(unittest.TestCase):
    """私聊/群聊判定的可用性回归：瞬时故障不能让私聊被误判成群聊。"""

    def setUp(self) -> None:
        self.client = MatrixClient(
            homeserver_url="http://hs:8008", as_token="t", bot_user_id="@guduu:hs",
        )

    def test_caches_and_falls_back_on_failure(self) -> None:
        # 先成功查到 2 人（私聊），缓存下来
        with mock.patch.object(
            self.client._session, "get",
            return_value=_Resp(200, {"joined": {"@a:hs": {}, "@guduu:hs": {}}}),
        ):
            self.assertEqual(self.client.joined_member_count("!r:hs"), 2)
        # 随后服务端抖动（两次都抛异常）：必须回退上次缓存值 2，而不是 fail-open 的 99
        with mock.patch.object(
            self.client._session, "get",
            side_effect=requests.RequestException("boom"),
        ):
            self.assertEqual(self.client.joined_member_count("!r:hs"), 2)

    def test_retries_once_then_succeeds(self) -> None:
        # 第一次抛异常、第二次成功：一次重试应吸收瞬时抖动
        with mock.patch.object(
            self.client._session, "get",
            side_effect=[
                requests.RequestException("flaky"),
                _Resp(200, {"joined": {"@a:hs": {}, "@guduu:hs": {}}}),
            ],
        ):
            self.assertEqual(self.client.joined_member_count("!r:hs"), 2)

    def test_unknown_room_conservatively_group(self) -> None:
        # 从未成功查过、又查不到 → 保守按群聊(99)，避免在群里刷屏
        with mock.patch.object(
            self.client._session, "get",
            side_effect=requests.RequestException("boom"),
        ):
            self.assertEqual(self.client.joined_member_count("!never:hs"), 99)


class TestMatrixClientAuth(unittest.TestCase):
    def setUp(self) -> None:
        self.token = "SECRET_AS_TOKEN_should_never_leak"
        self.client = MatrixClient(
            homeserver_url="http://hs:8008",
            as_token=self.token,
            bot_user_id="@guduu:hs",
        )

    def test_token_not_in_url(self) -> None:
        # 任意路径拼出来的 URL 都不能含 token；user_id（身份标识，非密钥）仍保留
        for path in (
            "/_matrix/client/v3/rooms/!r/join",
            "/_matrix/client/v3/createRoom",
            "/_matrix/client/v3/directory/room/%23a%3Ahs",
        ):
            url = self.client._url(path)
            self.assertNotIn(self.token, url, f"token 泄进了 URL: {url}")
            self.assertIn("user_id=", url)

    def test_token_in_bearer_header(self) -> None:
        # token 走 Authorization: Bearer 头，且挂在复用的 Session 上
        self.assertEqual(
            self.client._session.headers.get("Authorization"),
            f"Bearer {self.token}",
        )


class TestSetDisplayname(unittest.TestCase):
    """设置自己 profile 时不带 user_id 伪装参数（新 Synapse 上带它会 500）。"""

    def setUp(self) -> None:
        self.client = MatrixClient(
            homeserver_url="http://hs:8008", as_token="t", bot_user_id="@guduu:hs",
        )

    def test_profile_put_omits_user_id_masquerade(self) -> None:
        captured = {}

        def fake_put(url, json=None, timeout=None):
            captured["url"] = url
            return _Resp(200, {})

        with mock.patch.object(self.client._session, "put", side_effect=fake_put):
            self.client.set_displayname("GuDuu OS")
        # 设自己 profile 走本体身份：URL 不能带 ?user_id=（伪装路径在 1.15x 上 500）
        self.assertIn("/profile/", captured["url"])
        self.assertNotIn("user_id=", captured["url"])


if __name__ == "__main__":
    unittest.main()
