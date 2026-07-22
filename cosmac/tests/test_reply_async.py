# -*- coding: utf-8 -*-
"""多账号并发 AI 回复单测(负责人实报:一个账号 AI 执行中,另一账号完全无响应)。

根因:appservice 事务是串行等 ack 的,_handle_event 里同步跑 LLM 长任务会堵死
整个事件流。修复=回复主体剥进线程池:事务立即返回;同房间加锁保序,不同房并发。

三条验收:
1. 线程池模式下 _handle_event 立即返回,不等 LLM(事务不被长任务卡住);
2. 不同房间的两条消息真并发(慢回复不阻塞另一房);
3. 同一房间的两条消息严格串行且保序(不乱序/不交叉)。

内存 SQLite、零 key。运行:.venv/bin/python -m unittest cosmac.tests.test_reply_async
"""

from __future__ import annotations

import threading
import time
import unittest

from cosmac.db import init_engine


class FakeClient:
    """最小假 client:让事件走到 DM 慢路径(≤2人=私聊,对每句都回)。"""

    def set_typing(self, room_id, typing, timeout_ms=30000):
        pass

    def send_text(self, room_id, text, txn_id=None):
        return "$e"

    def joined_member_count(self, room_id):
        return 2

    def get_messages(self, room_id, limit=20):
        return []

    def resolve_alias(self, alias):
        return None

    def get_state_event(self, room_id, etype, state_key=""):
        return None


def _bot():
    from cosmac.bots.appservice_bot import CosmacBot
    from cosmac.config import CosmacConfig

    bot = CosmacBot(CosmacConfig(llm_provider="echo"))
    bot.client = FakeClient()  # type: ignore
    # 不打桩 _reply_pool——本测试就是要验证真实线程池行为
    bot._try_handle_command = lambda *a, **k: False  # type: ignore
    bot._gate_allows = lambda u, c: True  # type: ignore
    return bot


def _event(room: str, body: str, sender: str = "@u:h") -> dict:
    return {
        "type": "m.room.message",
        "content": {"msgtype": "m.text", "body": body},
        "sender": sender,
        "room_id": room,
        "event_id": "$" + body,
    }


class TestReplyAsync(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)
        self.bot = _bot()
        self.calls: list = []          # [(room, body, 开始时刻)] 按实际执行序记录
        self.done = threading.Event()  # 计数完成信号
        self._lock = threading.Lock()
        self._expect = 0

    def tearDown(self) -> None:
        pool = getattr(self.bot, "_reply_pool", None)
        if pool is not None:
            pool.shutdown(wait=True)

    def _stub_reply(self, sleep_s: float = 0.0):
        """把真实回复主体换成可观测的桩:记录(房间,内容,时刻),可注入慢延迟模拟 LLM。"""

        def fake(room_id, sender, user_text, text, content, is_dm, event_id, mentioned_ids):
            with self._lock:
                self.calls.append((room_id, user_text, time.monotonic()))
            if sleep_s:
                time.sleep(sleep_s)
            with self._lock:
                if len(self.calls) >= self._expect:
                    self.done.set()

        self.bot._reply_to_message = fake  # type: ignore

    def test_pool_mode_returns_immediately(self) -> None:
        """事务线程不等 LLM:慢回复(0.5s)下 _handle_event 必须毫秒级返回。"""
        self.assertIsNotNone(self.bot._reply_pool)  # 默认就是线程池模式
        self._stub_reply(sleep_s=0.5)
        self._expect = 1
        t0 = time.monotonic()
        self.bot._handle_event(_event("!a:h", "hi"))
        elapsed = time.monotonic() - t0
        self.assertLess(elapsed, 0.2, f"事务线程被回复阻塞了 {elapsed:.2f}s")
        self.assertTrue(self.done.wait(3), "异步回复最终没执行")

    def test_different_rooms_run_concurrently(self) -> None:
        """A 房 AI 慢任务执行中,B 房消息不必等它——两房并发,总耗时≈单个任务。"""
        self._stub_reply(sleep_s=0.6)
        self._expect = 2
        t0 = time.monotonic()
        self.bot._handle_event(_event("!a:h", "q1", sender="@u1:h"))
        self.bot._handle_event(_event("!b:h", "q2", sender="@u2:h"))
        self.assertTrue(self.done.wait(3), "两条回复没都执行")
        total = time.monotonic() - t0
        # 串行会 ≥1.2s;并发应接近 0.6s。留裕量断 <1.1s 即证明没串行。
        self.assertLess(total, 1.1, f"两房疑似串行执行(耗时 {total:.2f}s)")

    def test_same_room_is_serialized_in_order(self) -> None:
        """同房间两条消息:锁保证不交叉执行,且按提交顺序回复(不乱序)。"""
        self._stub_reply(sleep_s=0.3)
        self._expect = 2
        self.bot._handle_event(_event("!a:h", "first"))
        self.bot._handle_event(_event("!a:h", "second"))
        self.assertTrue(self.done.wait(3))
        bodies = [c[1] for c in self.calls]
        self.assertEqual(bodies, ["first", "second"])
        # 串行证据:第二条的开始时刻晚于第一条开始+sleep(即等到第一条执行完)
        self.assertGreaterEqual(self.calls[1][2] - self.calls[0][2], 0.28)

    def test_sync_mode_still_works(self) -> None:
        """_reply_pool=None(单测/调试开关)→ 原同步语义,返回前回复已执行。"""
        self.bot._reply_pool = None
        self._stub_reply()
        self._expect = 1
        self.bot._handle_event(_event("!a:h", "hi"))
        self.assertEqual(len(self.calls), 1)  # 无需 wait——同步路径返回即完成


if __name__ == "__main__":
    unittest.main()
