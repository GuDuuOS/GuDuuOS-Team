"""Nexus fleet 业务逻辑回归测试（KEY 签发/兑换/心跳/钱包）。

跑法（项目根）： .venv/bin/python -m unittest nexus.tests.test_fleet -v
用独立的临时 SQLite 文件建库，不碰 run/nexus.db，也不依赖任何网络。
"""

from __future__ import annotations

import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

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
        with self.assertRaises(FleetError):
            fleet.issue_keys(self.s, token_grant=1_000_000_000_001)

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
        # 历史/平台直接签发但尚未被 OEM 认领的节点不得猜测企业。
        listed = fleet.list_instances(self.s)[0]
        self.assertIsNone(listed["oem_id"])
        self.assertEqual(listed["company_name"], "")
        self.assertEqual(listed["oem_email"], "")

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

    def test_suspend_resume_and_irreversible_revoke(self):
        """暂停可恢复并同步实例；永久吊销后不能误恢复。"""
        issued = fleet.issue_keys(self.s)[0]
        instance_id = fleet.redeem(self.s, issued["key"], "im.lifecycle.test")[
            "instance_id"
        ]
        fleet.set_key_status(self.s, issued["id"], "suspended")
        self.assertEqual(self.s.get(db.NexusInstance, instance_id).status, "suspended")
        with self.assertRaises(FleetError) as suspended:
            fleet.heartbeat(self.s, issued["key"])
        self.assertEqual(suspended.exception.code, "NEXUS_KEY_SUSPENDED")
        fleet.set_key_status(self.s, issued["id"], "active")
        self.assertEqual(self.s.get(db.NexusInstance, instance_id).status, "active")
        fleet.revoke_key(self.s, issued["id"])
        with self.assertRaises(FleetError):
            fleet.set_key_status(self.s, issued["id"], "active")

    # ---- 心跳 ----

    def test_heartbeat_updates_and_returns_balance(self):
        k = self._one_key(grant=800)
        inst = fleet.redeem(self.s, k, "im.oem-a.com")["instance_id"]
        out = fleet.heartbeat(self.s, k, "1.2.0", {"users": 42, "dau": 7})
        self.assertEqual(out["instance_id"], inst)
        self.assertEqual(out["balance_tokens"], 800)
        fleet.debit(self.s, inst, 125, "openai/test")
        insts = fleet.list_instances(self.s)
        self.assertEqual(insts[0]["version"], "1.2.0")
        self.assertEqual(insts[0]["stats"]["users"], 42)
        self.assertIsNotNone(insts[0]["last_seen_ts"])
        self.assertEqual(insts[0]["tokens_total"], 125)
        self.assertEqual(insts[0]["tokens_today"], 125)
        self.assertEqual(insts[0]["requests_total"], 1)
        self.assertEqual(insts[0]["requests_today"], 1)

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

    def test_concurrent_debits_do_not_lose_updates(self):
        """两个独立事务同时扣费时，两笔减法与两条流水都必须完整保留。"""
        k = self._one_key(grant=100)
        inst = fleet.redeem(self.s, k, "im.concurrent.test")["instance_id"]
        self.s.commit()
        ready = threading.Barrier(2)

        def debit_once(index: int) -> int:
            """用独立 Session 模拟两个网关线程在同一时刻结算。"""
            worker_session = db.session()
            try:
                ready.wait(timeout=3)
                balance = fleet.debit(
                    worker_session, inst, 10, note=f"concurrent-{index}"
                )
                worker_session.commit()
                return balance
            finally:
                worker_session.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(debit_once, range(2)))

        self.s.expire_all()
        self.assertEqual(self.s.get(NexusWallet, inst).balance_tokens, 80)
        usage_rows = self.s.execute(
            select(NexusLedger).where(
                NexusLedger.instance_id == inst,
                NexusLedger.kind == "usage",
            )
        ).scalars().all()
        self.assertEqual(len(usage_rows), 2)
        self.assertEqual(sum(int(row.delta_tokens) for row in usage_rows), -20)

    # ---- 大屏聚合 ----

    def test_dash_summary(self):
        # 实例A：有心跳、有今日用量、两种模型
        ka = self._one_key(grant=1000)
        inst = fleet.redeem(self.s, ka, "im.dash-a.test")["instance_id"]
        fleet.heartbeat(
            self.s,
            ka,
            "1.0.0",
            {
                "users_total": 12,
                "users_business": 9,
                "users_admin": 1,
                "users_ai": 2,
            },
        )
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
        self.assertEqual(a["users"], 9)
        self.assertEqual(a["accounts_total"], 12)
        self.assertEqual(a["admin_users"], 1)
        self.assertEqual(a["ai_users"], 2)
        self.assertEqual(out["totals"]["users"], 9)
        self.assertEqual(out["totals"]["accounts_total"], 12)
        self.assertEqual(out["totals"]["admin_users"], 1)
        self.assertEqual(out["totals"]["ai_users"], 2)
        self.assertEqual(a["balance_tokens"], 820)
        self.assertEqual(by_domain["im.dash-b.test"]["status"], "offline")
        # 实时动态：A 的 grant + 2 笔 usage + B 的 grant = 4 条流水
        self.assertEqual(len(out["recent"]), 4)
        # 模型分布环图：按用量降序（gpt-4o 150 > claude-x 30）
        self.assertEqual(
            [(m["model"], m["tokens"]) for m in out["models"]],
            [("openai/gpt-4o", 150), ("anthropic/claude-x", 30)],
        )
        # 24 小时趋势：24 个桶，总和=今日消耗（都发生在最近一小时内）
        self.assertEqual(len(out["hourly"]), 24)
        self.assertEqual(sum(h["tokens"] for h in out["hourly"]), 180)
        # 总发放 = A 附赠 1000 + B 附赠 500（_one_key 默认）
        self.assertEqual(out["totals"]["granted_total"], 1500)
        self.assertEqual(out["totals"]["tokens_yesterday"], 0)

    def test_dash_summary_keeps_legacy_users_compatible(self):
        """未升级节点只上报 users 时，大屏仍保留原数字而不变成 0。"""
        key = self._one_key()
        fleet.redeem(self.s, key, "im.legacy.test")
        fleet.heartbeat(self.s, key, "1.11.0", {"users": 2})

        out = fleet.dash_summary(self.s)

        self.assertEqual(out["oems"][0]["users"], 2)
        self.assertEqual(out["oems"][0]["accounts_total"], 2)
        self.assertEqual(out["totals"]["users"], 2)


if __name__ == "__main__":
    unittest.main()
