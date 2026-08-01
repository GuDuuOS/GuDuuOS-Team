"""平台主管 Passkey 的注册、登录和重放防护测试。"""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy.pool import StaticPool

from nexus import admin_auth, db, passkeys
from nexus.fleet import FleetError


class PasskeyTests(unittest.TestCase):
    """用内存数据库和密码学验证结果替身测试 Nexus 自己的安全状态机。"""

    def setUp(self) -> None:
        self.old_env = {
            key: os.environ.get(key)
            for key in (
                "NEXUS_WEBAUTHN_RP_ID",
                "NEXUS_WEBAUTHN_ORIGIN",
                "NEXUS_WEBAUTHN_RP_NAME",
            )
        }
        os.environ["NEXUS_WEBAUTHN_RP_ID"] = "admin-nexus.guduu.co"
        os.environ["NEXUS_WEBAUTHN_ORIGIN"] = "https://admin-nexus.guduu.co"
        engine = db.init_engine("sqlite:///:memory:")
        # 同一进程的 Session 都必须命中同一个内存库，保持与其他 Nexus 单测口径一致。
        engine.dispose()
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        db._engine = create_engine(
            "sqlite:///:memory:",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        db.Base.metadata.create_all(db._engine)
        db._Session = sessionmaker(bind=db._engine, future=True)
        self.s = db.session()
        self.admin = admin_auth.create_admin(
            self.s,
            "owner",
            "OwnerPass123",
            "平台主管",
            actor_label="测试引导",
        )
        self.s.commit()

    def tearDown(self) -> None:
        self.s.close()
        for key, value in self.old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _register(self):
        """登记一个模拟凭据并返回创建后的安全摘要。"""
        options = passkeys.registration_options(self.s, self.admin["id"])
        verified = SimpleNamespace(
            credential_id=b"credential-one",
            credential_public_key=b"cose-public-key",
            sign_count=0,
        )
        with patch("nexus.passkeys.verify_registration_response", return_value=verified):
            result = passkeys.verify_registration(
                self.s,
                self.admin["id"],
                options["ceremony_id"],
                {"id": "ignored", "response": {"transports": ["internal"]}},
                "MacBook Touch ID",
                actor_label="平台主管",
            )
        self.s.commit()
        return result

    def test_register_list_and_delete_passkey(self) -> None:
        """浏览器私钥不入库，列表只返回名称与时间，管理员可移除自己的凭据。"""
        created = self._register()
        self.assertEqual(created["name"], "MacBook Touch ID")
        listed = passkeys.list_passkeys(self.s, self.admin["id"])
        self.assertEqual(listed, [created])
        self.assertNotIn("public_key", listed[0])
        self.assertNotIn("credential_id", listed[0])
        passkeys.delete_passkey(
            self.s,
            self.admin["id"],
            created["id"],
            actor_label="平台主管",
        )
        self.s.commit()
        self.assertEqual(passkeys.list_passkeys(self.s, self.admin["id"]), [])

    def test_passkey_login_issues_distinct_session_and_challenge_is_single_use(self) -> None:
        """Passkey 登录签发 nxp 会话，同一断言不能重放。"""
        self._register()
        options = passkeys.authentication_options(self.s, "owner")
        verified = SimpleNamespace(new_sign_count=3)
        credential = {"id": "Y3JlZGVudGlhbC1vbmU", "response": {}}
        with patch("nexus.passkeys.verify_authentication_response", return_value=verified):
            result = passkeys.verify_authentication(
                self.s,
                options["ceremony_id"],
                credential,
                source_ip="127.0.0.1",
            )
        self.s.commit()
        self.assertTrue(result["token"].startswith("nxp_"))
        self.assertIsNotNone(admin_auth.resolve_session(self.s, result["token"]))
        with self.assertRaises(FleetError) as raised:
            passkeys.verify_authentication(
                self.s, options["ceremony_id"], credential
            )
        self.assertEqual(raised.exception.code, "NEXUS_PASSKEY_CHALLENGE_INVALID")

    def test_origin_must_exactly_match_fixed_rp_id(self) -> None:
        """错误 Origin 不能因请求 Host 看似合法而被接受。"""
        os.environ["NEXUS_WEBAUTHN_ORIGIN"] = "https://evil.example"
        with self.assertRaises(FleetError) as raised:
            passkeys.registration_options(self.s, self.admin["id"])
        self.assertEqual(raised.exception.code, "NEXUS_PASSKEY_CONFIG_INVALID")


if __name__ == "__main__":
    unittest.main()
