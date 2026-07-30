"""AI 回复并发闸门回归测试。

验证同一用户即使从不同房间同时发消息，也只能串行进入完整回复流程；这条约束保护
“配额/钱包前查 → LLM → 结算”不被并发穿透。不同用户仍由线程池并发，不在这里降级。
"""

from __future__ import annotations

import threading
import unittest
from typing import Any, Dict, List

from cosmac.bots.appservice_bot import CosmacBot
from cosmac.config import CosmacConfig


class ReplyConcurrencyTest(unittest.TestCase):
    """覆盖 :meth:`CosmacBot._reply_locked` 的用户级串行保证。"""

    def test_same_user_across_rooms_is_serialized(self) -> None:
        """第一条未完成时，第二个房间的同用户回复不得进入计费/模型主体。"""
        bot = CosmacBot(CosmacConfig(llm_provider="echo"))
        if bot._reply_pool is not None:
            bot._reply_pool.shutdown(wait=False)
            bot._reply_pool = None

        entered_first = threading.Event()
        release_first = threading.Event()
        state_lock = threading.Lock()
        state: Dict[str, int] = {"active": 0, "max_active": 0, "calls": 0}

        def fake_reply(*args: Any, **kwargs: Any) -> None:
            """模拟慢 LLM；记录同一时刻进入主体的调用数。"""
            del args, kwargs
            with state_lock:
                state["calls"] += 1
                call_no = state["calls"]
                state["active"] += 1
                state["max_active"] = max(state["max_active"], state["active"])
            if call_no == 1:
                entered_first.set()
                release_first.wait(timeout=3)
            with state_lock:
                state["active"] -= 1

        bot._reply_to_message = fake_reply  # type: ignore[method-assign]
        common: List[Any] = ["@same:h", "问题", "问题", {}, True, "$event", []]
        first = threading.Thread(
            target=bot._reply_locked,
            args=("!room-a:h", *common),
        )
        second = threading.Thread(
            target=bot._reply_locked,
            args=("!room-b:h", *common),
        )
        first.start()
        self.assertTrue(entered_first.wait(timeout=3))
        second.start()
        try:
            # 第二线程即使已启动，也应卡在同一用户的锁外，不能进入 fake_reply。
            second.join(timeout=0.15)
            with state_lock:
                self.assertEqual(state["calls"], 1)
                self.assertEqual(state["max_active"], 1)
        finally:
            release_first.set()
            first.join(timeout=3)
            second.join(timeout=3)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        with state_lock:
            self.assertEqual(state["calls"], 2)
            self.assertEqual(state["max_active"], 1)


if __name__ == "__main__":
    unittest.main()
