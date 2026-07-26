"""Token 钱包 + 流水账（模块4 变现·Token 经济 P1）单元测试。

覆盖：wallet_repo 原子增减/守卫扣费/流水，parse_token_config 默认与覆盖，WalletStore 的
建钱包赠送/用量前拦/按真实用量扣费(含扣到 0 为止)/充值/调整/查流水。零 key、内存 SQLite。
"""

from __future__ import annotations

import unittest

from cosmac.db import init_engine, session_scope, wallet_repo
from cosmac.wallet import WalletStore, parse_token_config


class _FakeClient:
    """假控制室客户端：把给定的 token_config 事件原样返回。"""

    def __init__(self, ev):
        self._ev = ev

    def resolve_alias(self, a):
        return "!ctrl:h"

    def get_state_event(self, room, etype, key=""):
        return self._ev


class TestWalletRepo(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)

    def test_credit_and_balance(self) -> None:
        with session_scope() as s:
            self.assertEqual(wallet_repo.get_balance(s, "@a:h"), 0)
            bal = wallet_repo.credit(s, "@a:h", 100, reason="recharge", ref="o1")
            self.assertEqual(bal, 100)
            bal = wallet_repo.credit(s, "@a:h", 50, reason="grant")
            self.assertEqual(bal, 150)
        with session_scope() as s:
            w = wallet_repo.get_or_create(s, "@a:h")
            self.assertEqual(w.balance, 150)
            self.assertEqual(w.total_in, 150)   # 累计入账
            self.assertEqual(w.total_out, 0)

    def test_credit_rejects_non_positive(self) -> None:
        with session_scope() as s:
            with self.assertRaises(ValueError):
                wallet_repo.credit(s, "@a:h", 0, reason="recharge")
            with self.assertRaises(ValueError):
                wallet_repo.credit(s, "@a:h", -5, reason="recharge")

    def test_try_debit_guard(self) -> None:
        with session_scope() as s:
            wallet_repo.credit(s, "@a:h", 100, reason="recharge")
        # 够扣：扣成，返回新余额
        with session_scope() as s:
            self.assertEqual(wallet_repo.try_debit(s, "@a:h", 30, reason="ai_usage"), 70)
        # 不够扣：返回 None，余额不动、不记流水
        with session_scope() as s:
            self.assertIsNone(wallet_repo.try_debit(s, "@a:h", 999, reason="ai_usage"))
            self.assertEqual(wallet_repo.get_balance(s, "@a:h"), 70)
        # 恰好扣光
        with session_scope() as s:
            self.assertEqual(wallet_repo.try_debit(s, "@a:h", 70, reason="ai_usage"), 0)
            self.assertEqual(wallet_repo.get_balance(s, "@a:h"), 0)

    def test_try_debit_zero_is_noop(self) -> None:
        with session_scope() as s:
            wallet_repo.credit(s, "@a:h", 10, reason="grant")
        with session_scope() as s:
            self.assertEqual(wallet_repo.try_debit(s, "@a:h", 0, reason="ai_usage"), 10)
            # 零扣不记流水
            self.assertEqual(len(wallet_repo.list_ledger(s, "@a:h")), 1)  # 仅那笔 grant

    def test_ledger_records_and_order(self) -> None:
        with session_scope() as s:
            wallet_repo.credit(s, "@a:h", 100, reason="recharge", ref="o1", note="充值")
            wallet_repo.try_debit(s, "@a:h", 20, reason="ai_usage", ref="!room", note="AI 对话")
        with session_scope() as s:
            rows = wallet_repo.list_ledger(s, "@a:h")
            self.assertEqual(len(rows), 2)
            # 新→旧：最近的消费在前
            self.assertEqual(rows[0].reason, "ai_usage")
            self.assertEqual(rows[0].delta, -20)
            self.assertEqual(rows[0].balance_after, 80)
            self.assertEqual(rows[1].reason, "recharge")
            self.assertEqual(rows[1].delta, 100)
            self.assertEqual(rows[1].balance_after, 100)

    def test_adjust_positive_and_negative(self) -> None:
        with session_scope() as s:
            self.assertEqual(wallet_repo.adjust(s, "@a:h", 50, note="补偿"), 50)
            self.assertEqual(wallet_repo.adjust(s, "@a:h", -20, note="扣回"), 30)
            # 负向超额：返回 None、不改
            self.assertIsNone(wallet_repo.adjust(s, "@a:h", -999))
            self.assertEqual(wallet_repo.get_balance(s, "@a:h"), 30)


class TestParseConfig(unittest.TestCase):
    def test_defaults(self) -> None:
        cfg = parse_token_config(None)
        self.assertFalse(cfg["enabled"])       # 默认关
        self.assertEqual(cfg["markup"], 1.0)
        self.assertEqual(cfg["tokens_per_yuan"], 1000)
        self.assertEqual(cfg["free_grant"], 0)
        self.assertEqual(cfg["min_balance"], 1)

    def test_override(self) -> None:
        cfg = parse_token_config(
            {"enabled": True, "markup": 1.5, "tokens_per_yuan": 500,
             "free_grant": 2000, "min_balance": 10}
        )
        self.assertTrue(cfg["enabled"])
        self.assertEqual(cfg["markup"], 1.5)
        self.assertEqual(cfg["tokens_per_yuan"], 500)
        self.assertEqual(cfg["free_grant"], 2000)
        self.assertEqual(cfg["min_balance"], 10)

    def test_bad_values_fallback(self) -> None:
        cfg = parse_token_config({"markup": "abc", "tokens_per_yuan": 0, "free_grant": -5})
        self.assertEqual(cfg["markup"], 1.0)         # 非法回退
        self.assertEqual(cfg["tokens_per_yuan"], 1)  # 下限 1
        self.assertEqual(cfg["free_grant"], 0)       # 下限 0


class TestWalletStore(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)

    def _store(self, **cfg) -> WalletStore:
        base = {"enabled": True, "markup": 1.0, "tokens_per_yuan": 1000,
                "free_daily": 0, "free_grant": 0, "min_balance": 1}
        base.update(cfg)
        return WalletStore(_FakeClient(base), "#ctrl:h", ttl=0)

    def test_disabled_is_passthrough(self) -> None:
        st = self._store(enabled=False, free_grant=5000)
        self.assertFalse(st.enabled())
        # 关：前拦放行、不扣、不发赠送
        self.assertIsNone(st.precheck("@u:h"))
        self.assertEqual(st.ensure_wallet("@u:h"), 0)  # 关时不赠送
        r = st.charge_usage("@u:h", real_tokens=1000)
        self.assertEqual(r["charged"], 0)

    def test_ensure_wallet_grants_once(self) -> None:
        st = self._store(free_grant=2000)
        self.assertEqual(st.ensure_wallet("@u:h"), 2000)  # 首次赠送
        self.assertEqual(st.ensure_wallet("@u:h"), 2000)  # 幂等，不重复送
        self.assertEqual(st.balance("@u:h"), 2000)

    def test_precheck_blocks_when_empty(self) -> None:
        st = self._store(free_daily=0, free_grant=0, min_balance=1)
        msg = st.precheck("@u:h")   # 空钱包、无赠送、无免费额度
        self.assertIsNotNone(msg)
        self.assertIn("充值", msg)

    def test_precheck_passes_when_funded(self) -> None:
        st = self._store(free_grant=100)
        self.assertIsNone(st.precheck("@u:h"))  # 赠送 100 > min_balance

    def test_charge_usage_markup_and_ceil(self) -> None:
        st = self._store(markup=1.5)
        st.recharge("@u:h", 1000, order_no="o1")
        # 真实 100 token × 1.5 = 150
        r = st.charge_usage("@u:h", real_tokens=100, model="deepseek")
        self.assertEqual(r["charged"], 150)
        self.assertEqual(r["balance"], 850)
        self.assertFalse(r["capped"])
        # 向上取整：33 × 1.5 = 49.5 → 50
        r2 = st.charge_usage("@u:h", real_tokens=33)
        self.assertEqual(r2["charged"], 50)

    def test_charge_usage_caps_at_balance(self) -> None:
        st = self._store(markup=1.0)
        st.recharge("@u:h", 40, order_no="o1")
        # 应扣 100 但只有 40 → 扣 40、capped=True、余额 0
        r = st.charge_usage("@u:h", real_tokens=100)
        self.assertEqual(r["charged"], 40)
        self.assertEqual(r["balance"], 0)
        self.assertTrue(r["capped"])
        # meta 里仍记真实应扣（对账/展示用）
        rows = self._ledger_rows("@u:h")
        self.assertEqual(rows[0]["meta"]["cost"], 100)
        self.assertTrue(rows[0]["meta"]["capped"])

    def test_free_daily_covers_usage_without_touching_wallet(self) -> None:
        st = self._store(free_daily=100, markup=1.0)
        st.recharge("@u:h", 500, order_no="o1")  # 钱包有 500
        # 真实 60 token × 1.0 = 60，全走今日免费额度
        r = st.charge_usage("@u:h", real_tokens=60)
        self.assertEqual(r["from_free"], 60)
        self.assertEqual(r["from_wallet"], 0)
        self.assertEqual(st.balance("@u:h"), 500)  # 钱包没动
        self.assertEqual(st.free_daily_status("@u:h"), {"total": 100, "used": 60, "remaining": 40})
        # 免费额度消费不进钱包流水（余额没变）
        self.assertEqual(len(st.ledger("@u:h")), 1)  # 仅那笔充值

    def test_free_daily_then_wallet_spillover(self) -> None:
        st = self._store(free_daily=100, markup=1.0)
        st.recharge("@u:h", 500, order_no="o1")
        # 真实 130 token：前 100 走免费额度、剩 30 扣钱包
        r = st.charge_usage("@u:h", real_tokens=130)
        self.assertEqual(r["from_free"], 100)
        self.assertEqual(r["from_wallet"], 30)
        self.assertEqual(r["charged"], 130)
        self.assertEqual(st.balance("@u:h"), 470)
        self.assertEqual(st.free_daily_status("@u:h")["remaining"], 0)

    def test_free_daily_exhausted_and_no_wallet_caps(self) -> None:
        st = self._store(free_daily=50, markup=1.0)  # 无充值，钱包 0
        r = st.charge_usage("@u:h", real_tokens=80)  # 免费 50 + 钱包 0
        self.assertEqual(r["from_free"], 50)
        self.assertEqual(r["from_wallet"], 0)
        self.assertTrue(r["capped"])
        self.assertEqual(r["charged"], 50)

    def test_precheck_passes_on_free_daily_alone(self) -> None:
        st = self._store(free_daily=100, free_grant=0)  # 钱包空，但有今日免费额度
        self.assertIsNone(st.precheck("@u:h"))

    def test_precheck_blocks_when_free_and_wallet_both_empty(self) -> None:
        st = self._store(free_daily=100, markup=1.0)
        # 先把今日免费额度用光（钱包也空）
        st.charge_usage("@u:h", real_tokens=100)
        msg = st.precheck("@u:h")
        self.assertIsNotNone(msg)
        self.assertIn("充值", msg)

    def test_recharge_and_ledger(self) -> None:
        st = self._store()
        st.recharge("@u:h", 500, order_no="o9", note="充值 5 元")
        rows = st.ledger("@u:h")
        self.assertEqual(rows[0]["reason"], "recharge")
        self.assertEqual(rows[0]["delta"], 500)
        self.assertEqual(rows[0]["ref"], "o9")

    def test_adjust(self) -> None:
        st = self._store()
        self.assertEqual(st.adjust("@u:h", 100, operator="@admin:h"), 100)
        self.assertEqual(st.adjust("@u:h", -30), 70)

    def test_yuan_to_tokens(self) -> None:
        st = self._store(tokens_per_yuan=1000)
        self.assertEqual(st.yuan_to_tokens(9.9), 9900)

    def _ledger_rows(self, uid):
        return self._store().ledger(uid)


if __name__ == "__main__":
    unittest.main()
