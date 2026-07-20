"""Nexus fleet 业务逻辑回归测试（KEY 签发/兑换/心跳/钱包）。

跑法（项目根）： .venv/bin/python -m unittest nexus.tests.test_fleet -v
用独立的临时 SQLite 文件建库，不碰 run/nexus.db，也不依赖任何网络。
"""

from __future__ import annotations

import os
import tempfile
import unittest

from nexus import db, fleet
from nexus.db import NexusLedger, NexusWallet
from nexus.fleet import FleetError
from nexus.keys import generate_key, hash_key, looks_like_key, normalize_key
from sqlalchemy import select


class KeyFormatTest(unittest.TestCase):
    """KEY 生成与清洗的纯逻辑。"""

    def test_generate_and_recognize(self):
        k = generate_key()
        self.assertTrue(k.startswith("CMK-"))
        self.assertTrue(looks_like_key(k))
        # 归一化：小写、带空白也能识别（模拟邮件复制）
        self.assertTrue(looks_like_key("  " + k.lower() + "\n"))
        self.assertEqual(hash_key(k), hash_key(" " + k.lower()))

    def test_reject_garbage(self):
        for bad in ("", "CMK-XXX", "hello", "CMK-AAAA-BBBB-CCCC"):
            self.assertFalse(looks_like_key(bad), bad)

    def test_normalize(self):
        self.assertEqual(normalize_key(" cmk-a2b3 "), "CMK-A2B3")


class FleetTest(unittest.TestCase):
    """签发→兑换→心跳→充值/扣费 的全链路（临时 SQLite）。"""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        db.init_engine("sqlite:///" + self._tmp.name)
        self.s = db.session()

    def tearDown(self):
        self.s.close()
        os.unlink(self._tmp.name)

    # ---- 签发 ----

    def test_issue_keys(self):
        keys = fleet.issue_keys(self.s, count=3, note="张三订单#1", token_grant=1000)
        self.assertEqual(len(keys), 3)
        for k in keys:
            self.assertTrue(looks_like_key(k["key"]))
            self.assertEqual(k["key"].rsplit("-", 1)[-1], k["tail"])
        listed = fleet.list_keys(self.s)
        self.assertEqual(len(listed), 3)
        # 列表里绝不能出现明文
        self.assertNotIn("key", listed[0])
        self.assertEqual(listed[0]["token_grant"], 1000)

    def test_issue_bounds(self):
        with self.assertRaises(FleetError):
            fleet.issue_keys(self.s, count=0)
        with self.assertRaises(FleetError):
            fleet.issue_keys(self.s, count=101)
        with self.assertRaises(FleetError):
            fleet.issue_keys(self.s, token_grant=-1)

    # ---- 兑换 ----

    def _one_key(self, grant: int = 500) -> str:
        return fleet.issue_keys(self.s, note="t", token_grant=grant)[0]["key"]

    def test_redeem_creates_instance_wallet_ledger(self):
        k = self._one_key(grant=500)
        out = fleet.redeem(self.s, k, "im.oem-a.com", "a@b.co")
        self.assertFalse(out["reinstall"])
        wallet = self.s.get(NexusWallet, out["instance_id"])
        self.assertEqual(wallet.balance_tokens, 500)
        rows = self.s.execute(select(NexusLedger)).scalars().all()
        self.assertEqual([r.kind for r in rows], ["grant"])

    def test_redeem_reinstall_idempotent(self):
        k = self._one_key()
        first = fleet.redeem(self.s, k, "im.oem-a.com")
        again = fleet.redeem(self.s, k, "IM.OEM-A.COM")  # 大小写也应归一
        self.assertTrue(again["reinstall"])
        self.assertEqual(first["instance_id"], again["instance_id"])
        # 幂等重装不重复注资：默认附赠 500，重装后仍是 500（只注一次）
        wallet = self.s.get(NexusWallet, first["instance_id"])
        self.assertEqual(wallet.balance_tokens, 500)

    def test_redeem_key_bound_other_domain(self):
        k = self._one_key()
        fleet.redeem(self.s, k, "im.oem-a.com")
        with self.assertRaises(FleetError) as ctx:
            fleet.redeem(self.s, k, "im.oem-b.com")
        self.assertEqual(ctx.exception.code, "NEXUS_KEY_BOUND")

    def test_redeem_domain_taken(self):
        fleet.redeem(self.s, self._one_key(), "im.oem-a.com")
        with self.assertRaises(FleetError) as ctx:
            fleet.redeem(self.s, self._one_key(), "im.oem-a.com")
        self.assertEqual(ctx.exception.code, "NEXUS_DOMAIN_TAKEN")

    def test_redeem_revoked_and_garbage(self):
        keys = fleet.issue_keys(self.s)
        fleet.revoke_key(self.s, keys[0]["id"])
        with self.assertRaises(FleetError) as ctx:
            fleet.redeem(self.s, keys[0]["key"], "im.x.com")
        self.assertEqual(ctx.exception.code, "NEXUS_KEY_REVOKED")
        with self.assertRaises(FleetError):
            fleet.redeem(self.s, "not-a-key", "im.x.com")
        with self.assertRaises(FleetError):
            fleet.redeem(self.s, generate_key(), "bad domain!")

    # ---- 心跳 ----

    def test_heartbeat_updates_and_returns_balance(self):
        k = self._one_key(grant=800)
        inst = fleet.redeem(self.s, k, "im.oem-a.com")["instance_id"]
        out = fleet.heartbeat(self.s, k, "1.2.0", {"users": 42, "dau": 7})
        self.assertEqual(out["instance_id"], inst)
        self.assertEqual(out["balance_tokens"], 800)
        insts = fleet.list_instances(self.s)
        self.assertEqual(insts[0]["version"], "1.2.0")
        self.assertEqual(insts[0]["stats"]["users"], 42)
        self.assertIsNotNone(insts[0]["last_seen_ts"])

    def test_heartbeat_unredeemed(self):
        with self.assertRaises(FleetError) as ctx:
            fleet.heartbeat(self.s, self._one_key(), "1.0")
        self.assertEqual(ctx.exception.code, "NEXUS_NOT_REDEEMED")

    # ---- 钱包 ----

    def test_topup_and_debit(self):
        k = self._one_key(grant=100)
        inst = fleet.redeem(self.s, k, "im.oem-a.com")["instance_id"]
        self.assertEqual(fleet.topup(self.s, inst, 900, "手动充值#1"), 1000)
        # 扣费允许透支（断供判定是"下一次请求"，见 fleet.debit docstring）
        self.assertEqual(fleet.debit(self.s, inst, 1300, "claude in+out"), -300)
        kinds = [
            r.kind for r in self.s.execute(select(NexusLedger)).scalars().all()
        ]
        self.assertEqual(kinds, ["grant", "topup", "usage"])
        with self.assertRaises(FleetError):
            fleet.topup(self.s, inst, 0)
        with self.assertRaises(FleetError):
            fleet.debit(self.s, inst, -5)
        with self.assertRaises(FleetError):
            fleet.topup(self.s, 9999, 10)

    # ---- 大屏聚合 ----

    def test_dash_summary(self):
        # 实例A：有心跳、有今日用量、两种模型
        ka = self._one_key(grant=1000)
        inst = fleet.redeem(self.s, ka, "im.dash-a.test")["instance_id"]
        fleet.heartbeat(self.s, ka, "1.0.0", {"users": 12})
        fleet.debit(self.s, inst, 150, "openai/gpt-4o in=100 out=50")
        fleet.debit(self.s, inst, 30, "anthropic/claude-x in=20 out=10")
        # 实例B：兑换后从未心跳 → 大屏应判 offline
        fleet.redeem(self.s, self._one_key(), "im.dash-b.test")

        out = fleet.dash_summary(self.s)
        self.assertEqual(out["totals"]["instances"], 2)
        self.assertEqual(out["totals"]["online"], 1)
        self.assertEqual(out["totals"]["tokens_today"], 180)
        self.assertEqual(out["totals"]["requests_today"], 2)

        by_domain = {o["domain"]: o for o in out["oems"]}
        a = by_domain["im.dash-a.test"]
        self.assertEqual(a["status"], "active")
        self.assertEqual(a["tokens_total"], 180)
        self.assertEqual(a["requests_today"], 2)
        self.assertEqual(a["models_today"], 2)  # gpt-4o + claude-x
        self.assertEqual(a["users"], 12)
        self.assertEqual(a["balance_tokens"], 820)
        self.assertEqual(by_domain["im.dash-b.test"]["status"], "offline")
        # 实时动态：A 的 grant + 2 笔 usage + B 的 grant = 4 条流水
        self.assertEqual(len(out["recent"]), 4)


if __name__ == "__main__":
    unittest.main()
