"""Nexus OEM 账号层回归测试（注册/登录/会话 + KEY 认领 + 自有资源分权）。

跑法（项目根）： .venv/bin/python -m unittest nexus.tests.test_oem -v
用独立临时 SQLite 文件，不碰 run/nexus.db，不依赖网络。
"""

from __future__ import annotations

import os
import tempfile
import unittest

from nexus import db, fleet, oem
from nexus.fleet import FleetError


class PasswordTest(unittest.TestCase):
    """密码哈希与强度校验（纯逻辑）。"""

    def test_hash_roundtrip(self):
        h = oem.hash_password("abc12345")
        self.assertTrue(h.startswith("pbkdf2$"))
        self.assertTrue(oem.verify_password("abc12345", h))
        self.assertFalse(oem.verify_password("wrong123", h))
        # 两次派生 salt 不同 → 存储串不同
        self.assertNotEqual(h, oem.hash_password("abc12345"))

    def test_verify_bad_stored(self):
        self.assertFalse(oem.verify_password("x", "garbage"))
        self.assertFalse(oem.verify_password("x", ""))

    def test_password_problem(self):
        self.assertIsNotNone(oem.password_problem("short1"))   # 太短
        self.assertIsNotNone(oem.password_problem("12345678"))  # 纯数字
        self.assertIsNotNone(oem.password_problem("abcdefgh"))  # 纯字母
        self.assertIsNone(oem.password_problem("abc12345"))     # 合格


class OemAccountTest(unittest.TestCase):
    """注册→登录→会话→登出 全链路（临时 SQLite）。"""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        db.init_engine("sqlite:///" + self._tmp.name)
        self.s = db.session()

    def tearDown(self):
        self.s.close()
        os.unlink(self._tmp.name)

    def test_register_and_login(self):
        pub = oem.register(self.s, "A@Example.com ", "abc12345", "张三")
        # 邮箱归一化为小写、去空白；返回不含密码
        self.assertEqual(pub["email"], "a@example.com")
        self.assertEqual(pub["name"], "张三")
        self.assertNotIn("password_hash", pub)

        res = oem.login(self.s, "a@example.com", "abc12345")
        self.assertIn("token", res)
        self.assertEqual(res["oem"]["email"], "a@example.com")
        # 会话可解析回同一账号
        who = oem.resolve_session(self.s, res["token"])
        self.assertIsNotNone(who)
        self.assertEqual(who.id, pub["id"])

    def test_register_rejects_dup_and_bad_input(self):
        oem.register(self.s, "dup@example.com", "abc12345")
        with self.assertRaises(FleetError):
            oem.register(self.s, "dup@example.com", "abc12345")  # 邮箱重复
        with self.assertRaises(FleetError):
            oem.register(self.s, "not-an-email", "abc12345")      # 邮箱非法
        with self.assertRaises(FleetError):
            oem.register(self.s, "b@example.com", "123")          # 弱密码

    def test_login_wrong_password(self):
        oem.register(self.s, "c@example.com", "abc12345")
        with self.assertRaises(FleetError):
            oem.login(self.s, "c@example.com", "nope1234")
        # 不存在的邮箱与密码错误返回同一错误（不泄露账号是否存在）
        with self.assertRaises(FleetError):
            oem.login(self.s, "ghost@example.com", "abc12345")

    def test_logout_invalidates_session(self):
        oem.register(self.s, "d@example.com", "abc12345")
        token = oem.login(self.s, "d@example.com", "abc12345")["token"]
        self.assertIsNotNone(oem.resolve_session(self.s, token))
        oem.logout(self.s, token)
        self.assertIsNone(oem.resolve_session(self.s, token))

    def test_set_oem_status(self):
        pub = oem.register(self.s, "f@example.com", "abc12345")
        token = oem.login(self.s, "f@example.com", "abc12345")["token"]
        # 超管停用：会话立即失效、不能再登录
        out = oem.set_oem_status(self.s, pub["id"], "disabled")
        self.assertEqual(out["status"], "disabled")
        self.assertIsNone(oem.resolve_session(self.s, token))
        with self.assertRaises(FleetError):
            oem.login(self.s, "f@example.com", "abc12345")
        # 启用恢复：可重新登录（数据无损）
        oem.set_oem_status(self.s, pub["id"], "active")
        self.assertIn("token", oem.login(self.s, "f@example.com", "abc12345"))
        # 非法状态/不存在的账号
        with self.assertRaises(FleetError):
            oem.set_oem_status(self.s, pub["id"], "banned")
        with self.assertRaises(FleetError):
            oem.set_oem_status(self.s, 99999, "disabled")

    def test_disabled_account_cannot_login(self):
        pub = oem.register(self.s, "e@example.com", "abc12345")
        token = oem.login(self.s, "e@example.com", "abc12345")["token"]
        # 平台停用账号后：已有会话失效 + 无法再登录
        row = self.s.get(db.NexusOem, pub["id"])
        row.status = "disabled"
        self.s.flush()
        self.assertIsNone(oem.resolve_session(self.s, token))
        with self.assertRaises(FleetError):
            oem.login(self.s, "e@example.com", "abc12345")


class OemScopingTest(unittest.TestCase):
    """KEY 认领 + 自有资源隔离（OEM 只见自己的 KEY/实例）。"""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        db.init_engine("sqlite:///" + self._tmp.name)
        self.s = db.session()
        # 两个 OEM
        self.a = oem.register(self.s, "a@x.com", "abc12345")["id"]
        self.b = oem.register(self.s, "b@x.com", "abc12345")["id"]

    def tearDown(self):
        self.s.close()
        os.unlink(self._tmp.name)

    def _issue(self, grant=1000):
        return fleet.issue_keys(self.s, note="t", token_grant=grant)[0]["key"]

    def test_claim_and_ownership(self):
        k1 = self._issue()
        r = oem.claim_key(self.s, self.a, k1)
        self.assertFalse(r["already"])
        # 幂等：同账号再认领同一 KEY
        self.assertTrue(oem.claim_key(self.s, self.a, k1)["already"])
        # 别的账号认领已被认领的 KEY → 拒绝
        with self.assertRaises(FleetError):
            oem.claim_key(self.s, self.b, k1)

    def test_claim_rejects_bad_and_revoked(self):
        with self.assertRaises(FleetError):
            oem.claim_key(self.s, self.a, "CMK-XXXX")           # 格式错
        with self.assertRaises(FleetError):
            oem.claim_key(self.s, self.a, "CMK-A2B3-C4D5-E6F7-G8H9")  # 不存在
        # 已吊销的 KEY 不能认领
        info = fleet.issue_keys(self.s, note="t")[0]
        fleet.revoke_key(self.s, info["id"])
        with self.assertRaises(FleetError):
            oem.claim_key(self.s, self.a, info["key"])

    def test_my_keys_and_instances_isolated(self):
        # A 认领 k1 并装机开通 inst1；B 认领 k2 不开通
        k1 = self._issue()
        k2 = self._issue()
        oem.claim_key(self.s, self.a, k1)
        oem.claim_key(self.s, self.b, k2)
        fleet.redeem(self.s, k1, "a-oem.com", "admin@a-oem.com")

        a_keys = oem.my_keys(self.s, self.a)
        b_keys = oem.my_keys(self.s, self.b)
        self.assertEqual(len(a_keys), 1)
        self.assertEqual(len(b_keys), 1)
        self.assertNotEqual(a_keys[0]["id"], b_keys[0]["id"])

        a_inst = oem.my_instances(self.s, self.a)
        b_inst = oem.my_instances(self.s, self.b)
        self.assertEqual(len(a_inst), 1)
        self.assertEqual(a_inst[0]["domain"], "a-oem.com")
        self.assertEqual(a_inst[0]["balance_tokens"], 1000)
        self.assertEqual(len(b_inst), 0)  # B 尚未装机，无实例

        # 归属守卫
        self.assertTrue(oem.owns_instance(self.s, self.a, a_inst[0]["id"]))
        self.assertFalse(oem.owns_instance(self.s, self.b, a_inst[0]["id"]))

    def test_list_oems_for_admin(self):
        # 超管客户列表：全量账号 + 每家认领数；绝不含密码哈希
        k1 = self._issue()
        k2 = self._issue()
        oem.claim_key(self.s, self.a, k1)
        oem.claim_key(self.s, self.a, k2)
        rows = oem.list_oems(self.s)
        self.assertEqual(len(rows), 2)
        by_id = {r["id"]: r for r in rows}
        self.assertEqual(by_id[self.a]["keys_claimed"], 2)
        self.assertEqual(by_id[self.b]["keys_claimed"], 0)
        self.assertNotIn("password_hash", rows[0])


if __name__ == "__main__":
    unittest.main()
