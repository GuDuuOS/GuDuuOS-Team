"""自建邮箱验证码注册的核心逻辑单测。

不发真邮件、不调真 Synapse：把 `_send_email` 和 `_synapse_register` 打桩，
聚焦验证「发码→验码→建号」的状态机、限频、错码/过期/尝试上限等分支。
"""

from __future__ import annotations

import unittest

from cosmac import registration as reg


class RegistrationTest(unittest.TestCase):
    def setUp(self) -> None:
        # 每个用例独立的内存态 + 打桩
        reg._store.clear()
        self._sent: list[tuple[str, str]] = []
        reg._send_email = lambda to, code: self._sent.append((to, code))  # type: ignore
        # 让 registration_enabled() 为真（绕过 env 检查）
        reg.registration_enabled = lambda: True  # type: ignore
        # 建号成功桩：回 200 + 假 user_id
        reg._synapse_register = lambda hs, u, p: (  # type: ignore
            200, {"user_id": f"@{u}:test", "access_token": "tok"})
        # 隔离 DB：一邮一号「占位」默认成功（邮箱空闲=True），回滚为空操作——不碰真实 SQLite，
        # 保证单测幂等可重复跑（否则第一次注册占位写库后，第二次跑套件会被占位拦成 409）。
        reg._lookup_username = lambda email: None  # type: ignore
        reg._claim_email = lambda email, username: "claimed"  # type: ignore
        reg._release_email = lambda email, username: None  # type: ignore

    def _last_code(self) -> str:
        return self._sent[-1][1]

    def test_happy_path(self) -> None:
        code, body = reg.request_code("a@b.com")
        self.assertEqual(code, 200)
        self.assertEqual(len(self._sent), 1)
        # 用收到的码验证 + 建号
        st, payload = reg.verify_and_register(
            "a@b.com", self._last_code(), "alice", "Test1234!", hs_url="http://hs")
        self.assertEqual(st, 200)
        self.assertEqual(payload["user_id"], "@alice:test")

    def test_wrong_code_rejected(self) -> None:
        reg.request_code("a@b.com")
        st, payload = reg.verify_and_register(
            "a@b.com", "000000", "alice", "Test1234!", hs_url="http://hs")
        self.assertEqual(st, 400)
        self.assertIn("验证码", payload["error"])

    def test_code_is_single_use(self) -> None:
        reg.request_code("a@b.com")
        c = self._last_code()
        reg.verify_and_register("a@b.com", c, "alice", "Test1234!", hs_url="http://hs")
        # 同一个码再用一次应失败（已作废）
        st, _ = reg.verify_and_register("a@b.com", c, "bob", "Test1234!", hs_url="http://hs")
        self.assertEqual(st, 400)

    def test_resend_cooldown(self) -> None:
        reg.request_code("a@b.com")
        st, payload = reg.request_code("a@b.com")  # 立刻再发 → 命中冷却
        self.assertEqual(st, 429)
        self.assertIn("cooldown", payload)

    def test_bad_email_rejected(self) -> None:
        st, _ = reg.request_code("not-an-email")
        self.assertEqual(st, 400)

    def test_weak_password_rejected(self) -> None:
        reg.request_code("a@b.com")
        st, payload = reg.verify_and_register(
            "a@b.com", self._last_code(), "alice", "123", hs_url="http://hs")
        self.assertEqual(st, 400)
        self.assertIn("密码", payload["error"])

    def test_bad_username_rejected(self) -> None:
        reg.request_code("a@b.com")
        st, payload = reg.verify_and_register(
            "a@b.com", self._last_code(), "Alice Space", "Test1234!", hs_url="http://hs")
        self.assertEqual(st, 400)
        self.assertIn("用户名", payload["error"])

    def test_duplicate_email_rejected(self) -> None:
        # 邮箱已被占（占位返回 False）→ 409，且**不应去建号**（claim-first 的核心）。
        reg._claim_email = lambda email, username: "taken"  # type: ignore
        called = []
        reg._synapse_register = lambda hs, u, p: called.append(1) or (200, {})  # type: ignore
        reg.request_code("a@b.com")
        st, payload = reg.verify_and_register(
            "a@b.com", self._last_code(), "alice", "Test1234!", hs_url="http://hs")
        self.assertEqual(st, 409)
        self.assertIn("已注册", payload["error"])
        self.assertEqual(called, [])  # 占位失败就不该建号

    def test_db_error_fails_closed(self) -> None:
        # 占位时 cosmac DB 异常（None）→ 503，且不建号（fail-closed，绝不冒险破坏一邮一号）。
        reg._claim_email = lambda email, username: None  # type: ignore
        called = []
        reg._synapse_register = lambda hs, u, p: called.append(1) or (200, {})  # type: ignore
        reg.request_code("a@b.com")
        st, _ = reg.verify_and_register(
            "a@b.com", self._last_code(), "alice", "Test1234!", hs_url="http://hs")
        self.assertEqual(st, 503)
        self.assertEqual(called, [])

    def test_rollback_on_register_failure(self) -> None:
        # 新占位 + 建号**确定性失败(4xx)** → 回滚占位；返回建号的错误码。
        reg._claim_email = lambda email, username: "claimed"  # type: ignore
        released = []
        reg._release_email = (  # type: ignore
            lambda email, username: released.append((email, username)))
        reg._synapse_register = lambda hs, u, p: (409, {"error": "已占用"})  # type: ignore
        reg.request_code("a@b.com")
        st, _ = reg.verify_and_register(
            "a@b.com", self._last_code(), "alice", "Test1234!", hs_url="http://hs")
        self.assertEqual(st, 409)
        self.assertEqual(released, [("a@b.com", "alice")])

    def test_no_rollback_on_unknown_outcome(self) -> None:
        # 5xx/网络超时=**结果未知**（账号可能已建成）→ **不**回滚占位，保住邮箱映射
        # （否则孤儿账号永远无法邮箱登录/找回，见审查 bug#6）。
        reg._claim_email = lambda email, username: "claimed"  # type: ignore
        released = []
        reg._release_email = (  # type: ignore
            lambda email, username: released.append((email, username)))
        reg._synapse_register = lambda hs, u, p: (502, {"error": "timeout"})  # type: ignore
        reg.request_code("a@b.com")
        st, _ = reg.verify_and_register(
            "a@b.com", self._last_code(), "alice", "Test1234!", hs_url="http://hs")
        self.assertEqual(st, 502)
        self.assertEqual(released, [])  # 映射保留 → 本人重试可自愈/可找回密码

    def test_existing_claim_never_released(self) -> None:
        # 邮箱本就绑定本账号（"existing"，上次结果未知后的重试）→ 即使建号 4xx 失败
        # 也**不**回滚——那条映射不是本次建的，删了就毁掉老账号的邮箱登录/找回。
        reg._claim_email = lambda email, username: "existing"  # type: ignore
        released = []
        reg._release_email = (  # type: ignore
            lambda email, username: released.append((email, username)))
        reg._synapse_register = lambda hs, u, p: (409, {"error": "已占用"})  # type: ignore
        reg.request_code("a@b.com")
        st, _ = reg.verify_and_register(
            "a@b.com", self._last_code(), "alice", "Test1234!", hs_url="http://hs")
        self.assertEqual(st, 409)
        self.assertEqual(released, [])


class PasswordResetTest(unittest.TestCase):
    def setUp(self) -> None:
        reg._store.clear()
        self._sent: list[tuple[str, str]] = []
        self._reset_calls: list[tuple[str, str]] = []  # (user_id, new_password)
        reg.reset_enabled = lambda: True  # type: ignore
        reg._send_reset_email = lambda to, code: self._sent.append((to, code))  # type: ignore
        # 只有 a@b.com 注册过 → 映射到 alice
        reg._lookup_username = lambda email: "alice" if email == "a@b.com" else None  # type: ignore
        reg._admin_reset_password = lambda hs, uid, pw: (  # type: ignore
            self._reset_calls.append((uid, pw)) or (200, {"ok": True}))

    def _last_code(self) -> str:
        return self._sent[-1][1]

    def test_registered_email_sends_code(self) -> None:
        st, _ = reg.reset_request_code("a@b.com")
        self.assertEqual(st, 200)
        self.assertEqual(len(self._sent), 1)

    def test_unknown_email_no_send_but_ok(self) -> None:
        # 防枚举：未注册邮箱也回 200，但不真发信
        st, _ = reg.reset_request_code("nope@x.com")
        self.assertEqual(st, 200)
        self.assertEqual(len(self._sent), 0)

    def test_reset_happy_path(self) -> None:
        reg.reset_request_code("a@b.com")
        st, payload = reg.reset_verify(
            "a@b.com", self._last_code(), "NewPass123!", hs_url="http://hs", server_name="cosmac.cc")
        self.assertEqual(st, 200)
        # 确认拿正确的 user_id + 新密码去调了重置
        self.assertEqual(self._reset_calls, [("@alice:cosmac.cc", "NewPass123!")])

    def test_reset_wrong_code(self) -> None:
        reg.reset_request_code("a@b.com")
        st, _ = reg.reset_verify(
            "a@b.com", "000000", "NewPass123!", hs_url="http://hs", server_name="cosmac.cc")
        self.assertEqual(st, 400)
        self.assertEqual(self._reset_calls, [])  # 没验过码就不该调重置

    def test_reset_weak_password(self) -> None:
        reg.reset_request_code("a@b.com")
        st, payload = reg.reset_verify(
            "a@b.com", self._last_code(), "123", hs_url="http://hs", server_name="cosmac.cc")
        self.assertEqual(st, 400)
        self.assertIn("密码", payload["error"])

    def test_register_code_cannot_reset(self) -> None:
        # 注册码和找回码分桶：注册码不能拿去重置
        reg.registration_enabled = lambda: True  # type: ignore
        reg._send_email = lambda to, code: self._sent.append((to, code))  # type: ignore
        reg.request_code("a@b.com")          # 注册码
        reg_code = self._last_code()
        st, _ = reg.reset_verify(
            "a@b.com", reg_code, "NewPass123!", hs_url="http://hs", server_name="cosmac.cc")
        self.assertEqual(st, 400)  # reset 桶里没这个码


class LoginAccountTest(unittest.TestCase):
    """账号登录收口(login_account)：限频 + 代理 Synapse + 记审计。全程打桩,不连真库/真 HS。"""

    def setUp(self) -> None:
        reg._ip_store.clear()
        self._audits: list = []
        reg._audit = (  # type: ignore
            lambda kind, **kw: self._audits.append((kind, kw.get("ok"), kw.get("detail"))))
        # 保存原实现,tearDown 还原——防打桩的停用查询/HTTP 泄漏到别的用例。
        self._orig_qud = reg.query_user_deactivated
        self._orig_post = reg.requests.post

    def tearDown(self) -> None:
        reg.query_user_deactivated = self._orig_qud  # type: ignore
        reg.requests.post = self._orig_post  # type: ignore

    def test_deactivated_account_gets_specific_message(self) -> None:
        # 停用账号:Synapse 密码登录 403(密码已抹),后端查出已停用 → 回专门文案,不再"密码错误"。
        import cosmac.registration as _r

        class _Resp:
            status_code = 403
            @staticmethod
            def json():
                return {}
        _r.requests.post = lambda *a, **k: _Resp()  # type: ignore
        _r.query_user_deactivated = lambda hs, uid: True  # type: ignore
        st, payload = reg.login_account(
            "duxz02", "whatever", hs_url="http://hs", client_ip="1.2.3.4", server_name="h"
        )
        self.assertEqual(st, 403)
        self.assertEqual(payload.get("errcode"), "M_USER_DEACTIVATED")
        self.assertIn("停用", payload.get("error", ""))
        self.assertIn(("login", False, "deactivated"), self._audits)

    def test_active_account_wrong_pw_stays_generic(self) -> None:
        # 正常账号密码错(未停用)→ 仍回通用"用户名或密码错误",不泄露账号是否存在。
        import cosmac.registration as _r

        class _Resp:
            status_code = 403
            @staticmethod
            def json():
                return {}
        _r.requests.post = lambda *a, **k: _Resp()  # type: ignore
        _r.query_user_deactivated = lambda hs, uid: False  # type: ignore
        st, payload = reg.login_account(
            "alice", "wrong", hs_url="http://hs", client_ip="1.2.3.4", server_name="h"
        )
        self.assertEqual(st, 403)
        self.assertNotIn("errcode", payload)
        self.assertIn("用户名或密码", payload.get("error", ""))
        self.assertIn(("login", False, "bad_credentials"), self._audits)

    def test_list_deactivated_user_ids_pages_and_filters(self) -> None:
        # 分页拉全量用户,只收 deactivated=真 的 user_id;两页后 next_token=None 收尾。
        import cosmac.registration as _r

        orig_env, orig_get = _r._env, _r.requests.get
        pages = [
            {"users": [{"name": "@a:h", "deactivated": True},
                       {"name": "@b:h", "deactivated": False}], "next_token": "1"},
            {"users": [{"name": "@c:h", "deactivated": 1}], "next_token": None},
        ]
        calls = {"n": 0}
        try:
            _r._env = lambda name, default="": (  # type: ignore
                "admintok" if name == "ADMIN_TOKEN" else default)

            def _get(*a, **k):
                i = calls["n"]
                calls["n"] += 1

                class _R:
                    status_code = 200
                    @staticmethod
                    def json():
                        return pages[i]
                return _R()
            _r.requests.get = _get  # type: ignore
            ids = reg.list_deactivated_user_ids("http://hs")
            self.assertEqual(ids, {"@a:h", "@c:h"})
        finally:
            _r._env, _r.requests.get = orig_env, orig_get  # type: ignore

    def test_list_deactivated_fail_open_on_error(self) -> None:
        # 无令牌 → None(调用方据此不过滤)。
        import cosmac.registration as _r
        orig_env = _r._env
        try:
            _r._env = lambda name, default="": default  # type: ignore（无 ADMIN_TOKEN）
            self.assertIsNone(reg.list_deactivated_user_ids("http://hs"))
        finally:
            _r._env = orig_env  # type: ignore

    def test_query_user_deactivated_parses_admin_api(self) -> None:
        # query_user_deactivated：读 Synapse 管理 API 的 deactivated 字段。
        import cosmac.registration as _r

        orig_env, orig_get = _r._env, _r.requests.get
        try:
            _r._env = lambda name, default="": (  # type: ignore
                "admintok" if name == "ADMIN_TOKEN" else default)

            class _R:
                status_code = 200
                @staticmethod
                def json():
                    return {"deactivated": True}
            _r.requests.get = lambda *a, **k: _R()  # type: ignore
            self.assertTrue(reg.query_user_deactivated("http://hs", "@x:h"))
        finally:
            _r._env, _r.requests.get = orig_env, orig_get  # type: ignore

    def test_success_returns_synapse_resp_and_audits_ok(self) -> None:
        import cosmac.registration as _r

        class _Resp:
            status_code = 200
            @staticmethod
            def json():
                return {"access_token": "tok", "user_id": "@a:h", "device_id": "d"}
        _r.requests.post = lambda *a, **k: _Resp()  # type: ignore
        st, payload = reg.login_account("alice", "pw", hs_url="http://hs", client_ip="1.2.3.4")
        self.assertEqual(st, 200)
        self.assertEqual(payload["access_token"], "tok")
        self.assertIn(("login", True, "ok"), self._audits)

    def test_bad_credentials_audits_fail(self) -> None:
        import cosmac.registration as _r

        class _Resp:
            status_code = 403
            @staticmethod
            def json():
                return {}
        _r.requests.post = lambda *a, **k: _Resp()  # type: ignore
        st, _ = reg.login_account("alice", "wrong", hs_url="http://hs", client_ip="1.2.3.4")
        self.assertEqual(st, 403)
        self.assertIn(("login", False, "bad_credentials"), self._audits)

    def test_empty_input_rejected(self) -> None:
        st, _ = reg.login_account("", "", hs_url="http://hs")
        self.assertEqual(st, 403)

    def test_synapse_429_not_mapped_to_bad_credentials(self) -> None:
        # 高①:Synapse 限频(429)不能被当成"用户名或密码错误",要透传 429
        import cosmac.registration as _r

        class _Resp:
            status_code = 429
            @staticmethod
            def json():
                return {}
        _r.requests.post = lambda *a, **k: _Resp()  # type: ignore
        st, _ = reg.login_account("alice", "pw", hs_url="http://hs", client_ip="1.2.3.4")
        self.assertEqual(st, 429)
        self.assertIn(("login", False, "hs_rate_limited"), self._audits)

    def test_synapse_5xx_maps_to_502(self) -> None:
        import cosmac.registration as _r

        class _Resp:
            status_code = 503
            @staticmethod
            def json():
                return {}
        _r.requests.post = lambda *a, **k: _Resp()  # type: ignore
        st, _ = reg.login_account("alice", "pw", hs_url="http://hs", client_ip="1.2.3.4")
        self.assertEqual(st, 502)

    def test_forwards_real_ip_to_synapse(self) -> None:
        # 高①:代理登录必须带 X-Forwarded-For(真实IP),否则 Synapse 按 bot IP 全局限频
        import cosmac.registration as _r
        seen = {}

        class _Resp:
            status_code = 200
            @staticmethod
            def json():
                return {"access_token": "t", "user_id": "@a:h", "device_id": "d"}

        def _post(url, **k):
            seen["xff"] = (k.get("headers") or {}).get("X-Forwarded-For")
            return _Resp()
        _r.requests.post = _post  # type: ignore
        reg.login_account("alice", "pw", hs_url="http://hs", client_ip="9.9.9.9")
        self.assertEqual(seen["xff"], "9.9.9.9")


class PasswordStrengthTest(unittest.TestCase):
    """password_problem 规则 + 注册/重置弱密码拦截(阶段1)。纯计算,无桩。"""

    def test_rules(self) -> None:
        pp = reg.password_problem
        self.assertIsNotNone(pp("short1"))              # 太短
        self.assertIsNotNone(pp("abcdefgh"))            # 单一类别(纯字母)
        self.assertIsNotNone(pp("12345678"))            # 单一类别+常见弱密码
        self.assertIsNotNone(pp("Password1".lower()))   # 常见弱密码表
        self.assertIsNotNone(pp("alice2024", "alice"))  # 含用户名
        self.assertIsNone(pp("zk8#mQ2pL"))              # 合格
        self.assertIsNone(pp("hong2024mao"))            # 字母+数字两类,合格
        self.assertIsNone(pp("ali99xxxx", "ali"))       # 用户名<4位不启用包含规则

    def test_register_rejects_weak(self) -> None:
        reg.registration_enabled = lambda: True  # type: ignore
        sent: list = []
        reg._send_email = lambda to, code: sent.append((to, code))  # type: ignore
        reg._store.clear()
        reg._ip_store.clear()
        reg.request_code("w@b.com")
        st, payload = reg.verify_and_register(
            "w@b.com", sent[-1][1], "bobby", "bobby1234567", hs_url="http://hs")
        self.assertEqual(st, 400)
        self.assertIn("用户名", payload["error"])  # 密码包含用户名被拦


class TurnstileTest(unittest.TestCase):
    """Turnstile 人机验证:没配 secret 放行;配了则 token 空/校验不过被拦(阶段1下)。"""

    def setUp(self) -> None:
        import os
        os.environ.pop("COSMAC_TURNSTILE_SECRET", None)

    def tearDown(self) -> None:
        import os
        os.environ.pop("COSMAC_TURNSTILE_SECRET", None)

    def test_disabled_passes(self) -> None:
        # 没配 secret → _verify_turnstile 一律放行(功能可插拔)
        self.assertTrue(reg._verify_turnstile(""))
        self.assertFalse(reg.turnstile_enabled())

    def test_enabled_empty_token_blocked(self) -> None:
        import os
        os.environ["COSMAC_TURNSTILE_SECRET"] = "s3cr3t"
        self.assertTrue(reg.turnstile_enabled())
        self.assertFalse(reg._verify_turnstile(""))   # 空 token 直接 False,不打网络

    def test_request_code_blocked_when_turnstile_fails(self) -> None:
        import os
        os.environ["COSMAC_TURNSTILE_SECRET"] = "s3cr3t"
        reg.registration_enabled = lambda: True  # type: ignore
        st, payload = reg.request_code("a@b.com", turnstile="")
        self.assertEqual(st, 400)
        self.assertIn("人机验证", payload["error"])


class StepUpTest(unittest.TestCase):
    """阶段2 异地登录二次验证:risky 判定 + 挑战→验码→放行 全流程(全打桩)。"""

    # 类定义时捕获真函数:用例里会打 _login_risky 桩,tearDown 还原,防止污染后续用例
    _ORIG_RISKY = staticmethod(reg._login_risky)

    def setUp(self) -> None:
        import os
        os.environ["COSMAC_LOGIN_STEPUP"] = "1"
        reg._store.clear()
        reg._ip_store.clear()
        self._audits: list = []
        reg._audit = (  # type: ignore
            lambda kind, **kw: self._audits.append(kw.get("detail")))
        self._sent: list = []
        reg._send_login_email = lambda to, code: self._sent.append((to, code))  # type: ignore
        self._revoked: list = []
        reg._revoke_token = lambda hs, tok: self._revoked.append(tok)  # type: ignore
        reg._email_for_login = lambda u: "a@b.com" if u == "alice" else None  # type: ignore
        # Synapse 登录桩:密码一律正确
        import cosmac.registration as _r

        class _Resp:
            status_code = 200
            @staticmethod
            def json():
                return {"access_token": "tok1", "user_id": "@alice:h", "device_id": "d"}
        _r.requests.post = lambda *a, **k: _Resp()  # type: ignore

    def tearDown(self) -> None:
        import os
        os.environ.pop("COSMAC_LOGIN_STEPUP", None)
        reg._login_risky = self._ORIG_RISKY  # type: ignore  # 还原桩

    def test_ip_bucket(self) -> None:
        self.assertEqual(reg._ip_bucket("1.2.3.4"), "1.2")
        self.assertEqual(reg._ip_bucket("2001:db8:1:2:3:4:5:6"), "2001:db8:1:2")

    def test_first_login_not_risky(self) -> None:
        reg_recent = lambda s, u: []  # noqa: E731
        import cosmac.db.auth_event_repo as repo
        old = repo.recent_success_ips
        repo.recent_success_ips = reg_recent  # type: ignore
        try:
            self.assertFalse(reg._login_risky("alice", "9.9.9.9"))
        finally:
            repo.recent_success_ips = old  # type: ignore

    def test_challenge_then_verify(self) -> None:
        # 判定可疑 → 第一步:不发 token、撤销 token、发码、回 step_up
        reg._login_risky = lambda u, ip: True  # type: ignore
        st, payload = reg.login_account("alice", "pw", hs_url="http://hs", client_ip="9.9.9.9")
        self.assertEqual(st, 200)
        self.assertTrue(payload.get("step_up"))
        self.assertNotIn("access_token", payload)          # token 绝不能漏给前端
        self.assertEqual(self._revoked, ["tok1"])          # 暂扣 token 已撤销
        self.assertEqual(len(self._sent), 1)               # 码已发
        self.assertIn("stepup_challenge", self._audits)
        # 第二步:带正确码 → 验码通过 → 正常发 token
        code = self._sent[-1][1]
        st2, payload2 = reg.login_account(
            "alice", "pw", hs_url="http://hs", client_ip="9.9.9.9", code=code)
        self.assertEqual(st2, 200)
        self.assertEqual(payload2.get("access_token"), "tok1")
        self.assertIn("ok_stepup", self._audits)

    def test_wrong_code_rejected(self) -> None:
        reg._login_risky = lambda u, ip: True  # type: ignore
        reg.login_account("alice", "pw", hs_url="http://hs", client_ip="9.9.9.9")
        st, _ = reg.login_account(
            "alice", "pw", hs_url="http://hs", client_ip="9.9.9.9", code="000000")
        self.assertEqual(st, 403)
        self.assertIn("stepup_bad_code", self._audits)

    def test_no_email_passes_through(self) -> None:
        # 没绑邮箱的账号:可疑也放行(别锁死),审计留痕
        reg._login_risky = lambda u, ip: True  # type: ignore
        st, payload = reg.login_account("bob", "pw", hs_url="http://hs", client_ip="9.9.9.9")
        self.assertEqual(st, 200)
        self.assertEqual(payload.get("access_token"), "tok1")
        self.assertIn("stepup_skipped_no_email", self._audits)

    def test_disabled_by_default(self) -> None:
        import os
        os.environ.pop("COSMAC_LOGIN_STEPUP", None)
        reg._login_risky = lambda u, ip: True  # type: ignore
        st, payload = reg.login_account("alice", "pw", hs_url="http://hs", client_ip="9.9.9.9")
        self.assertEqual(st, 200)
        self.assertEqual(payload.get("access_token"), "tok1")  # 开关关:直接放行


if __name__ == "__main__":
    unittest.main()
