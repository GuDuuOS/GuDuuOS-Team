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
        self.assertIsNotNone(oem.password_problem("short1"))  # 太短
        self.assertIsNotNone(oem.password_problem("12345678"))  # 纯数字
        self.assertIsNotNone(oem.password_problem("abcdefgh"))  # 纯字母
        self.assertIsNone(oem.password_problem("abc12345"))  # 合格


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
        pub = oem.register(
            self.s,
            "A@Example.com ",
            "abc12345",
            "张三",
            inviter="GUDUU",
            company="测试公司",
            contact_name="张三",
            phone="13800000000",
        )
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
        oem.register(
            self.s,
            "dup@example.com",
            "abc12345",
            inviter="GUDUU",
            company="测试公司",
            contact_name="张三",
            phone="13800000000",
        )
        with self.assertRaises(FleetError):
            oem.register(
                self.s,
                "dup@example.com",
                "abc12345",
                inviter="GUDUU",
                company="测试公司",
                contact_name="张三",
                phone="13800000000",
            )  # 邮箱重复
        with self.assertRaises(FleetError):
            oem.register(
                self.s,
                "not-an-email",
                "abc12345",
                inviter="GUDUU",
                company="测试公司",
                contact_name="张三",
                phone="13800000000",
            )  # 邮箱非法
        with self.assertRaises(FleetError):
            oem.register(
                self.s,
                "b@example.com",
                "123",
                inviter="GUDUU",
                company="测试公司",
                contact_name="张三",
                phone="13800000000",
            )  # 弱密码

    def test_login_wrong_password(self):
        oem.register(
            self.s,
            "c@example.com",
            "abc12345",
            inviter="GUDUU",
            company="测试公司",
            contact_name="张三",
            phone="13800000000",
        )
        with self.assertRaises(FleetError):
            oem.login(self.s, "c@example.com", "nope1234")
        # 不存在的邮箱与密码错误返回同一错误（不泄露账号是否存在）
        with self.assertRaises(FleetError):
            oem.login(self.s, "ghost@example.com", "abc12345")

    def test_logout_invalidates_session(self):
        oem.register(
            self.s,
            "d@example.com",
            "abc12345",
            inviter="GUDUU",
            company="测试公司",
            contact_name="张三",
            phone="13800000000",
        )
        token = oem.login(self.s, "d@example.com", "abc12345")["token"]
        self.assertIsNotNone(oem.resolve_session(self.s, token))
        oem.logout(self.s, token)
        self.assertIsNone(oem.resolve_session(self.s, token))

    def test_set_oem_status(self):
        pub = oem.register(
            self.s,
            "f@example.com",
            "abc12345",
            inviter="GUDUU",
            company="测试公司",
            contact_name="张三",
            phone="13800000000",
        )
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
        pub = oem.register(
            self.s,
            "e@example.com",
            "abc12345",
            inviter="GUDUU",
            company="测试公司",
            contact_name="张三",
            phone="13800000000",
        )
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
        self.a = oem.register(
            self.s,
            "a@x.com",
            "abc12345",
            inviter="GUDUU",
            company="测试公司",
            contact_name="张三",
            phone="13800000000",
        )["id"]
        self.b = oem.register(
            self.s,
            "b@x.com",
            "abc12345",
            inviter="GUDUU",
            company="测试公司",
            contact_name="张三",
            phone="13800000000",
        )["id"]

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
            oem.claim_key(self.s, self.a, "CMK-XXXX")  # 格式错
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

        # 超管节点列表必须沿 KEY 认领关系带出真实 OEM 企业，
        # 不能把实例管理员邮箱误当企业名。
        admin_inst = fleet.list_instances(self.s)[0]
        self.assertEqual(admin_inst["oem_id"], self.a)
        self.assertEqual(admin_inst["company_name"], "测试公司")
        self.assertEqual(admin_inst["oem_email"], "a@x.com")

        # 归属守卫
        self.assertTrue(oem.owns_instance(self.s, self.a, a_inst[0]["id"]))
        self.assertFalse(oem.owns_instance(self.s, self.b, a_inst[0]["id"]))

        # OEM 点开自己的节点时，返回与超管详情同口径的真实心跳/账本数据。
        fleet.heartbeat(
            self.s,
            k1,
            "1.2.3",
            {
                "users_total": 3,
                "users_business": 1,
                "users_admin": 1,
                "users_ai": 1,
                "channels_total": 2,
                "knowledge_bases_total": 1,
                "agents_custom_enabled": 4,
            },
            client_ip="34.44.38.162",
        )
        fleet.debit(self.s, a_inst[0]["id"], 125, "openai/test")
        detail = oem.my_instance_detail(self.s, self.a, a_inst[0]["id"])
        self.assertEqual(detail["domain"], "a-oem.com")
        self.assertEqual(detail["version"], "1.2.3")
        self.assertEqual(detail["balance_tokens"], 875)
        self.assertEqual(detail["tokens_total"], 125)
        self.assertEqual(detail["requests_total"], 1)
        self.assertEqual(detail["stats"]["channels_total"], 2)
        self.assertEqual(detail["stats"]["agents_custom_enabled"], 4)
        self.assertEqual(detail["last_ip"], "34.44.38.0/24")

        # 另一家 OEM 即使猜到实例编号也只得到 403；不存在的编号同样 403，
        # 不给跨企业探测节点是否存在的信息差。
        with self.assertRaises(FleetError) as other_error:
            oem.my_instance_detail(self.s, self.b, a_inst[0]["id"])
        self.assertEqual(other_error.exception.http_status, 403)
        with self.assertRaises(FleetError) as missing_error:
            oem.my_instance_detail(self.s, self.a, 99999)
        self.assertEqual(missing_error.exception.http_status, 403)

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


class InviteTest(unittest.TestCase):
    """邀请人层级：必填、填错拒注册、GUDUU=平台直属、层级边落库。"""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        db.init_engine("sqlite:///" + self._tmp.name)
        self.s = db.session()

    def tearDown(self):
        self.s.close()
        os.unlink(self._tmp.name)

    def test_inviter_required_and_validated(self):
        # 不填 → 拒
        with self.assertRaises(FleetError):
            oem.register(
                self.s,
                "a@x.com",
                "abc12345",
                company="测试公司",
                contact_name="张三",
                phone="13800000000",
            )
        # 填了不存在的 → 拒(填错不能注册)
        with self.assertRaises(FleetError):
            oem.register(
                self.s,
                "a@x.com",
                "abc12345",
                inviter="ghost@x.com",
                company="测试公司",
                contact_name="张三",
                phone="13800000000",
            )
        # 官方码不分大小写 → 平台直属
        pub = oem.register(
            self.s,
            "a@x.com",
            "abc12345",
            inviter="guduu",
            company="测试公司",
            contact_name="张三",
            phone="13800000000",
        )
        edge = self.s.get(db.NexusOemInvite, pub["id"])
        self.assertIsNotNone(edge)
        self.assertIsNone(edge.inviter_id)

    def test_downline_chain_recorded(self):
        top = oem.register(
            self.s,
            "top@x.com",
            "abc12345",
            inviter="GUDUU",
            company="测试公司",
            contact_name="张三",
            phone="13800000000",
        )
        # 下线填上线邮箱(大小写/空白容错)
        sub = oem.register(
            self.s,
            "sub@x.com",
            "abc12345",
            inviter=" Top@X.com ",
            company="测试公司",
            contact_name="张三",
            phone="13800000000",
        )
        edge = self.s.get(db.NexusOemInvite, sub["id"])
        self.assertEqual(edge.inviter_id, top["id"])
        # 超管列表能看到层级展示名
        rows = {o["email"]: o for o in oem.list_oems(self.s)}
        self.assertEqual(rows["sub@x.com"]["inviter"], "top@x.com")
        self.assertEqual(rows["top@x.com"]["inviter"], "GuDuu")

    def test_disabled_inviter_cannot_recruit(self):
        top = oem.register(
            self.s,
            "t2@x.com",
            "abc12345",
            inviter="GUDUU",
            company="测试公司",
            contact_name="张三",
            phone="13800000000",
        )
        oem.set_oem_status(self.s, top["id"], "disabled")
        with self.assertRaises(FleetError):
            oem.register(
                self.s,
                "s2@x.com",
                "abc12345",
                inviter="t2@x.com",
                company="测试公司",
                contact_name="张三",
                phone="13800000000",
            )

    def test_share_code_builds_unlimited_oem_chain(self):
        """分享码可邀请下级 OEM，层级/全部下级按任意深度动态计算。"""
        top = oem.register(
            self.s,
            "top3@x.com",
            "abc12345",
            inviter="GUDUU",
            company="顶层公司",
            contact_name="张三",
            phone="13800000000",
        )
        top_share = oem.share_summary(self.s, top["id"], "https://nexus.test")
        self.assertIn("?invite=", top_share["partner_link"])
        sub = oem.register(
            self.s,
            "sub3@x.com",
            "abc12345",
            inviter=top_share["code"],
            company="二层公司",
            contact_name="李四",
            phone="13900000000",
        )
        sub_share = oem.share_summary(self.s, sub["id"], "https://nexus.test")
        leaf = oem.register(
            self.s,
            "leaf3@x.com",
            "abc12345",
            inviter=sub_share["code"],
            company="三层公司",
            contact_name="王五",
            phone="13700000000",
        )
        rows = {row["id"]: row for row in oem.list_oems(self.s)}
        self.assertEqual(rows[top["id"]]["level"], 1)
        self.assertEqual(rows[sub["id"]]["level"], 2)
        self.assertEqual(rows[leaf["id"]]["level"], 3)
        self.assertEqual(rows[top["id"]]["direct_oems"], 1)
        self.assertEqual(rows[top["id"]]["total_downline_oems"], 2)

    def test_user_attribution_requires_matching_oem_instance(self):
        """普通用户归属必须同时匹配分享码、KEY 归属、实例和 Matrix 域名。"""
        owner = oem.register(
            self.s,
            "owner@x.com",
            "abc12345",
            inviter="GUDUU",
            company="归属公司",
            contact_name="张三",
            phone="13800000000",
        )
        issued = fleet.issue_keys(self.s, token_grant=10)[0]["key"]
        oem.claim_key(self.s, owner["id"], issued)
        fleet.redeem(self.s, issued, "owner.example.com")
        share = oem.share_summary(self.s, owner["id"], "https://nexus.test")
        self.assertEqual(len(share["user_links"]), 1)

        first = oem.record_user_attribution(
            self.s, issued, share["code"], "@alice:owner.example.com"
        )
        self.assertFalse(first["already"])
        again = oem.record_user_attribution(
            self.s, issued, share["code"], "@alice:owner.example.com"
        )
        self.assertTrue(again["already"])
        with self.assertRaises(FleetError):
            oem.record_user_attribution(
                self.s, issued, share["code"], "@mallory:other.example.com"
            )

        summary = oem.share_summary(self.s, owner["id"], "https://nexus.test")
        self.assertEqual(summary["direct_users"], 1)
        self.assertEqual(summary["network_users"], 1)
        snapshot = oem.hierarchy_snapshot(self.s)
        self.assertEqual(
            snapshot["user_edges"][0]["user_id"], "@alice:owner.example.com"
        )

    def test_network_directory_only_returns_own_downline(self):
        """OEM 目录可见自己整棵下级树，不得泄露旁支企业与联系资料。"""
        top = oem.register(
            self.s,
            "directory-top@x.com",
            "abc12345",
            inviter="GUDUU",
            company="甲集团",
            contact_name="甲联系人",
            phone="13800000001",
        )
        top_share = oem.share_summary(self.s, top["id"], "https://nexus.test")
        sub = oem.register(
            self.s,
            "directory-sub@x.com",
            "abc12345",
            inviter=top_share["code"],
            company="乙公司",
            contact_name="乙联系人",
            phone="13800000002",
        )
        sub_share = oem.share_summary(self.s, sub["id"], "https://nexus.test")
        leaf = oem.register(
            self.s,
            "directory-leaf@x.com",
            "abc12345",
            inviter=sub_share["code"],
            company="丙公司",
            contact_name="丙联系人",
            phone="13800000003",
        )
        unrelated = oem.register(
            self.s,
            "directory-other@x.com",
            "abc12345",
            inviter="GUDUU",
            company="旁支公司",
            contact_name="旁支联系人",
            phone="13800000004",
        )

        # 给顶层与叶子各开一个真实实例，再从各自分享码上报用户归属。
        # 这样同时验证“我的直属用户”与“下级网络用户”两种关系。
        top_key = fleet.issue_keys(self.s, token_grant=10)[0]["key"]
        oem.claim_key(self.s, top["id"], top_key)
        fleet.redeem(self.s, top_key, "top-directory.example.com")
        oem.record_user_attribution(
            self.s,
            top_key,
            top_share["code"],
            "@alice:top-directory.example.com",
        )

        leaf_key = fleet.issue_keys(self.s, token_grant=10)[0]["key"]
        oem.claim_key(self.s, leaf["id"], leaf_key)
        fleet.redeem(self.s, leaf_key, "leaf-directory.example.com")
        leaf_share = oem.share_summary(self.s, leaf["id"], "https://nexus.test")
        oem.record_user_attribution(
            self.s,
            leaf_key,
            leaf_share["code"],
            "@bob:leaf-directory.example.com",
        )

        directory = oem.network_directory(self.s, top["id"])
        self.assertEqual(directory["oem_total"], 2)
        self.assertEqual(directory["user_total"], 2)
        by_company = {row["company"]: row for row in directory["oems"]}
        self.assertEqual(set(by_company), {"乙公司", "丙公司"})
        self.assertEqual(by_company["乙公司"]["relation"], "direct")
        self.assertEqual(by_company["乙公司"]["depth"], 1)
        self.assertEqual(by_company["丙公司"]["relation"], "indirect")
        self.assertEqual(by_company["丙公司"]["depth"], 2)
        self.assertEqual(by_company["丙公司"]["parent_company"], "乙公司")
        self.assertEqual(by_company["乙公司"]["network_users"], 1)
        # 开放给上级的目录明确不含下级账号和联系资料。
        for row in directory["oems"]:
            self.assertNotIn("email", row)
            self.assertNotIn("contact_name", row)
            self.assertNotIn("phone", row)

        users = {row["user_id"]: row for row in directory["users"]}
        self.assertEqual(
            users["@alice:top-directory.example.com"]["relation"], "direct"
        )
        self.assertEqual(
            users["@bob:leaf-directory.example.com"]["relation"], "indirect"
        )
        self.assertEqual(users["@bob:leaf-directory.example.com"]["depth"], 2)
        self.assertEqual(
            users["@bob:leaf-directory.example.com"]["instance_domain"],
            "leaf-directory.example.com",
        )

        # 二层 OEM 只能看到自己的叶子和其用户，既看不到上级，也看不到旁支。
        sub_directory = oem.network_directory(self.s, sub["id"])
        self.assertEqual([row["id"] for row in sub_directory["oems"]], [leaf["id"]])
        self.assertEqual(
            [row["user_id"] for row in sub_directory["users"]],
            ["@bob:leaf-directory.example.com"],
        )
        self.assertNotIn(unrelated["id"], [row["id"] for row in directory["oems"]])


class ProfileAndFilesTest(unittest.TestCase):
    """客户档案(注册强制三项)与合同附件(上传/下载/删除/白名单/上限)。"""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        db.init_engine("sqlite:///" + self._tmp.name)
        self.s = db.session()

    def tearDown(self):
        self.s.close()
        os.unlink(self._tmp.name)

    def test_profile_required_on_register(self):
        # 缺任意一项都拒
        with self.assertRaises(FleetError):
            oem.register(
                self.s,
                "p1@x.com",
                "abc12345",
                inviter="GUDUU",
                contact_name="张三",
                phone="13800000000",
            )  # 缺企业
        with self.assertRaises(FleetError):
            oem.register(
                self.s,
                "p1@x.com",
                "abc12345",
                inviter="GUDUU",
                company="星辰传媒",
                phone="13800000000",
            )  # 缺联系人
        with self.assertRaises(FleetError):
            oem.register(
                self.s,
                "p1@x.com",
                "abc12345",
                inviter="GUDUU",
                company="星辰传媒",
                contact_name="张三",
            )  # 缺联系方式
        pub = oem.register(
            self.s,
            "p1@x.com",
            "abc12345",
            inviter="GUDUU",
            company="星辰传媒",
            contact_name="张三",
            phone="13800000000",
        )
        # 档案落库 + 显示名默认取企业名
        detail = oem.oem_detail(self.s, pub["id"])
        self.assertEqual(detail["company"], "星辰传媒")
        self.assertEqual(detail["contact_name"], "张三")
        self.assertEqual(detail["phone"], "13800000000")
        self.assertFalse(detail["profile_missing"])
        self.assertEqual(pub["name"], "星辰传媒")

    def test_admin_note_and_detail_summary(self):
        pub = oem.register(
            self.s,
            "p2@x.com",
            "abc12345",
            inviter="GUDUU",
            company="测试公司",
            contact_name="李四",
            phone="13900000000",
        )
        oem.set_admin_note(self.s, pub["id"], "重点客户,谈到 8 折")
        d = oem.oem_detail(self.s, pub["id"])
        self.assertEqual(d["admin_note"], "重点客户,谈到 8 折")
        self.assertEqual(d["inviter"], "GuDuu")
        self.assertEqual(d["keys"], [])
        with self.assertRaises(FleetError):
            oem.oem_detail(self.s, 99999)

    def test_contract_files(self):
        pub = oem.register(
            self.s,
            "p3@x.com",
            "abc12345",
            inviter="GUDUU",
            company="测试公司",
            contact_name="王五",
            phone="13700000000",
        )
        # 白名单外扩展名拒;空内容拒;超限拒
        with self.assertRaises(FleetError):
            oem.add_oem_file(self.s, pub["id"], "evil.exe", "app/x", b"x")
        with self.assertRaises(FleetError):
            oem.add_oem_file(self.s, pub["id"], "c.pdf", "application/pdf", b"")
        with self.assertRaises(FleetError):
            oem.add_oem_file(
                self.s,
                pub["id"],
                "big.pdf",
                "application/pdf",
                b"x" * (oem.FILE_MAX_BYTES + 1),
            )
        # 正常上传(路径注入被掐成纯文件名)
        f = oem.add_oem_file(
            self.s, pub["id"], "../../合同2026.pdf", "application/pdf", b"%PDF-1.4 fake"
        )
        self.assertEqual(f["filename"], "合同2026.pdf")
        d = oem.oem_detail(self.s, pub["id"])
        self.assertEqual(len(d["files"]), 1)
        self.assertEqual(d["files"][0]["size"], len(b"%PDF-1.4 fake"))
        # 下载内容一致;删除后消失(幂等)
        row = oem.get_oem_file(self.s, f["id"])
        self.assertEqual(bytes(row.data), b"%PDF-1.4 fake")
        oem.delete_oem_file(self.s, f["id"])
        oem.delete_oem_file(self.s, f["id"])
        self.assertEqual(oem.oem_detail(self.s, pub["id"])["files"], [])


class KeyRequestTest(unittest.TestCase):
    """授权中心 V2：结构化申请、加密交付、补资料、撤回与审计。"""

    def setUp(self):
        self._old_secret = os.environ.get("NEXUS_SECRET_KEY")
        os.environ["NEXUS_SECRET_KEY"] = "unit-test-license-delivery-secret-32-bytes"
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        db.init_engine("sqlite:///" + self._tmp.name)
        self.s = db.session()
        self.a = oem.register(
            self.s,
            "a@x.com",
            "abc12345",
            inviter="GUDUU",
            company="测试公司",
            contact_name="张三",
            phone="13800000000",
        )["id"]

    def tearDown(self):
        self.s.close()
        os.unlink(self._tmp.name)
        if self._old_secret is None:
            os.environ.pop("NEXUS_SECRET_KEY", None)
        else:
            os.environ["NEXUS_SECRET_KEY"] = self._old_secret

    def test_request_and_approve_delivers_key(self):
        req = oem.request_key(
            self.s,
            self.a,
            "首个正式节点",
            deployment_domain="my-brand.com",
            purpose="企业内部协作",
            requested_tokens=5000,
            expected_public_ip="203.0.113.9",
            strict_ip=True,
        )
        self.assertEqual(req["status"], "pending")
        self.assertEqual(req["deployment_domain"], "my-brand.com")
        self.assertEqual(req["expected_public_ip_masked"], "203.0.113.0/24")
        self.assertTrue(req["strict_ip"])
        # 超管批准：签发 + 自动归属 + Fernet 加密交付，管理响应不含明文。
        out = oem.decide_request(self.s, req["id"], True, token_grant=5000)
        self.assertEqual(out["status"], "approved")
        self.assertNotIn("key", out)
        self.assertEqual(out["delivery_status"], "ready")
        binding = self.s.get(db.NexusKeyBinding, out["key_id"])
        self.assertEqual(binding.approved_domain, "my-brand.com")
        self.assertTrue(binding.strict_ip)
        self.assertNotIn("203.0.113.9", binding.expected_ip_hash)
        # 门户摘要也不带明文；必须显式领取，KEY 已自动归属。
        mine = oem.my_requests(self.s, self.a)
        self.assertNotIn("key", mine[0])
        self.assertEqual(oem.my_keys(self.s, self.a)[0]["id"], out["key_id"])
        revealed = oem.reveal_request_key(self.s, self.a, req["id"])
        self.assertTrue(revealed["key"].startswith("CMK-"))
        delivery = self.s.get(db.NexusKeyRequestDelivery, req["id"])
        self.assertNotIn(revealed["key"].encode("utf-8"), bytes(delivery.encrypted_key))
        self.assertNotIn("key", oem.list_requests(self.s, status="approved")[0])
        # 装机兑换成功 → 密文销毁，其余申请与审计保留。
        fleet.redeem(
            self.s,
            revealed["key"],
            "my-brand.com",
            client_ip="203.0.113.9",
        )
        oem.clear_plain_by_key(self.s, revealed["key"])
        after = oem.my_requests(self.s, self.a)[0]
        self.assertEqual(after["delivery_status"], "used")
        self.assertEqual(after["status"], "approved")
        actions = [
            event["action"]
            for event in oem.request_detail(self.s, req["id"])["timeline"]
        ]
        self.assertEqual(actions, ["submit", "approve", "reveal", "redeem"])

    def test_same_oem_and_domain_cannot_submit_twice(self):
        """同账号双击或重复提交同域名时只保留第一份申请。"""
        first = oem.request_key(
            self.s,
            self.a,
            "第一次",
            deployment_domain="Node.Example.COM.",
            purpose="企业内部协作",
        )
        with self.assertRaises(FleetError) as duplicate:
            oem.request_key(
                self.s,
                self.a,
                "双击重复",
                deployment_domain="node.example.com",
                purpose="企业内部协作",
            )
        self.assertEqual(duplicate.exception.code, "NEXUS_REQUEST_DOMAIN_EXISTS")
        self.assertIn(f"#{first['id']}", duplicate.exception.message)
        self.assertEqual(self.s.query(db.NexusKeyRequest).count(), 1)

    def test_same_oem_can_request_different_domains(self):
        """一个 OEM 可合法购买多个不同域名的节点授权。"""
        oem.request_key(
            self.s,
            self.a,
            deployment_domain="node-a.example.com",
            purpose="A 节点",
        )
        second = oem.request_key(
            self.s,
            self.a,
            deployment_domain="node-b.example.com",
            purpose="B 节点",
        )
        self.assertEqual(second["deployment_domain"], "node-b.example.com")
        self.assertEqual(self.s.query(db.NexusKeyRequest).count(), 2)

    def test_rejected_domain_can_be_requested_again(self):
        """被拒绝或撤回不会永久占用域名，OEM 修正资料后可重申。"""
        first = oem.request_key(
            self.s,
            self.a,
            deployment_domain="retry.example.com",
            purpose="首次申请",
        )
        oem.decide_request(self.s, first["id"], False, decide_note="请补充合同")
        retried = oem.request_key(
            self.s,
            self.a,
            deployment_domain="retry.example.com",
            purpose="补充后重申",
        )
        self.assertNotEqual(retried["id"], first["id"])

    def test_reject_and_pending_cap(self):
        req = oem.request_key(
            self.s, self.a, "拒绝测试", deployment_domain="reject.test"
        )
        out = oem.decide_request(self.s, req["id"], False, decide_note="请先联系商务")
        self.assertEqual(out["status"], "rejected")
        self.assertEqual(out["decide_note"], "请先联系商务")
        # 已处理的申请不能再裁决
        with self.assertRaises(FleetError):
            oem.decide_request(self.s, req["id"], True)
        # 挂起上限 3 张
        for index in range(3):
            oem.request_key(
                self.s,
                self.a,
                "容量测试",
                deployment_domain=f"capacity-{index}.test",
            )
        with self.assertRaises(FleetError):
            oem.request_key(
                self.s, self.a, "第4张", deployment_domain="capacity-4.test"
            )

    def test_needs_info_update_and_cancel(self):
        req = oem.request_key(
            self.s, self.a, "待确认", purpose="客户交付", deployment_domain="old.test"
        )
        asked = oem.decide_request(
            self.s,
            req["id"],
            False,
            action="needs_info",
            decide_note="请确认正式域名",
        )
        self.assertEqual(asked["status"], "needs_info")
        updated = oem.update_request(
            self.s,
            self.a,
            req["id"],
            purpose="客户交付",
            deployment_domain="new.test",
        )
        self.assertEqual(updated["status"], "pending")
        self.assertEqual(updated["deployment_domain"], "new.test")
        cancelled = oem.cancel_request(self.s, self.a, req["id"])
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(oem.request_counts(self.s)["cancelled"], 1)


if __name__ == "__main__":
    unittest.main()
