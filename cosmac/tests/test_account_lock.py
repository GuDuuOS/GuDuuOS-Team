# -*- coding: utf-8 -*-
"""账号「锁定停用」单测(负责人报的:停用恢复后成员关系全丢)。

根因:旧「停用」走 Synapse deactivate,会把用户退出**所有房间**(协议级不可逆);
改为 locked(锁定):禁登录但数据全保留。本文件测后端配合面:
① 登录代理识别 M_USER_LOCKED → 专门文案(不再误报"密码错误");
② 停用检测(query_user_deactivated)认 locked;
③ 名册过滤(list_deactivated_user_ids)把 locked 用户也算停用。

运行:.venv/bin/python -m unittest cosmac.tests.test_account_lock
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from cosmac import registration


class _Resp:
    def __init__(self, status_code: int, payload) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class TestLockedLogin(unittest.TestCase):
    def test_locked_login_gets_deactivated_style_error(self) -> None:
        """锁定用户登录:Synapse 回 401+M_USER_LOCKED → 专门的「已被停用」文案。"""
        with patch.object(registration.requests, "post", return_value=_Resp(
            401, {"errcode": "M_USER_LOCKED", "error": "This account has been locked"}
        )):
            st, body = registration._proxy_synapse_login(
                "http://hs", "alice", "pw", "1.2.3.4")
        self.assertEqual(st, 403)
        self.assertIn("已被停用", body["error"])
        self.assertEqual(body["errcode"], "M_USER_DEACTIVATED")

    def test_wrong_password_still_generic(self) -> None:
        """普通密码错(M_FORBIDDEN)仍回通用文案(不泄露账号状态)。"""
        with patch.object(registration.requests, "post", return_value=_Resp(
            403, {"errcode": "M_FORBIDDEN", "error": "Invalid password"}
        )):
            st, body = registration._proxy_synapse_login(
                "http://hs", "alice", "pw", "1.2.3.4")
        self.assertEqual(st, 403)
        self.assertEqual(body["error"], "用户名或密码错误")


class TestLockedDetection(unittest.TestCase):
    def _q(self, payload):
        with patch.object(registration, "_env", return_value="admtok"), \
             patch.object(registration.requests, "get",
                          return_value=_Resp(200, payload)):
            return registration.query_user_deactivated("http://hs", "@u:h")

    def test_locked_counts_as_deactivated(self) -> None:
        self.assertTrue(self._q({"deactivated": False, "locked": True}))

    def test_normal_user_false(self) -> None:
        self.assertFalse(self._q({"deactivated": False, "locked": False}))

    def test_legacy_deactivated_still_true(self) -> None:
        self.assertTrue(self._q({"deactivated": True}))


class TestRosterFilter(unittest.TestCase):
    def test_list_includes_locked_users(self) -> None:
        """名册过滤集合:locked 与 deactivated 都算(两者都登不进来,不该被派单)。"""
        page = {
            "users": [
                {"name": "@ok:h", "deactivated": False, "locked": False},
                {"name": "@locked:h", "deactivated": False, "locked": True},
                {"name": "@gone:h", "deactivated": True},
            ],
        }
        with patch.object(registration, "_env", return_value="admtok"), \
             patch.object(registration.requests, "get",
                          return_value=_Resp(200, page)):
            out = registration.list_deactivated_user_ids("http://hs")
        self.assertEqual(out, {"@locked:h", "@gone:h"})


if __name__ == "__main__":
    unittest.main()
