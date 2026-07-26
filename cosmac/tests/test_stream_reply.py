"""流式回复（_StreamWriter）单元测试。

覆盖：首次发草稿、节流（间隔/字数/次数上限）、定格返回"已发过别再发"、失败即停用回落、
傀儡身份走 *_as 接口、空回复保留草稿。纯内存假 client，不碰网络。
"""

from __future__ import annotations

import unittest

from cosmac.bots.appservice_bot import _StreamWriter


class FakeClient:
    """记录所有发送/编辑调用的假 client；可配置某次开始失败。"""

    def __init__(self, fail_send: bool = False, fail_edit_after: int = -1):
        self.sent = []          # [(room, text, as_user)]
        self.edits = []         # [(room, event_id, text, as_user)]
        self.fail_send = fail_send
        self.fail_edit_after = fail_edit_after   # -1=不失败；N=第 N+1 次编辑起失败

    def send_text(self, room_id, text, txn_id=None):
        if self.fail_send:
            return None
        self.sent.append((room_id, text, ""))
        return f"$ev{len(self.sent)}"

    def send_text_as(self, room_id, text, user_id, txn_id=None):
        if self.fail_send:
            return None
        self.sent.append((room_id, text, user_id))
        return f"$ev{len(self.sent)}"

    def edit_text(self, room_id, event_id, new_text):
        if 0 <= self.fail_edit_after <= len(self.edits):
            return False
        self.edits.append((room_id, event_id, new_text, ""))
        return True

    def edit_text_as(self, room_id, event_id, new_text, user_id):
        if 0 <= self.fail_edit_after <= len(self.edits):
            return False
        self.edits.append((room_id, event_id, new_text, user_id))
        return True


def _writer(client, as_user="", *, instant=True) -> _StreamWriter:
    """建一个 writer；instant=True 时把节流阈值降到 0，方便逐笔断言。"""
    w = _StreamWriter(client, "!r:h", as_user)
    if instant:
        w._MIN_INTERVAL = 0.0
        w._MIN_CHARS = 0
    return w


class StreamWriterTests(unittest.TestCase):
    def test_first_chunk_sends_draft(self) -> None:
        c = FakeClient()
        w = _writer(c)
        w("你好")
        self.assertEqual(len(c.sent), 1)
        self.assertEqual(c.sent[0][1], "你好")
        self.assertEqual(c.edits, [])

    def test_subsequent_chunks_edit_same_message(self) -> None:
        c = FakeClient()
        w = _writer(c)
        w("你好")
        w("你好，世界")
        w("你好，世界！")
        self.assertEqual(len(c.sent), 1)          # 始终只有一条消息
        self.assertEqual(len(c.edits), 2)
        self.assertEqual(c.edits[-1][2], "你好，世界！")

    def test_throttle_by_interval_and_chars(self) -> None:
        c = FakeClient()
        w = _StreamWriter(c, "!r:h")              # 用真实阈值（1.2s / 24 字）
        w("第一段")                                 # 首次：直接发
        w("第一段再加一点")                          # 间隔不够 → 不编辑
        self.assertEqual(len(c.sent), 1)
        self.assertEqual(len(c.edits), 0)
        w._last_ts -= 10.0                        # 把上次编辑时间往前推 10 秒 = 假装已过间隔
        # （注意不能置 0：monotonic() 在某些平台就是从 0 附近起算，置 0 反而不算"过了很久"）
        w("第一段再加一点")                          # 字数增量不够 24 → 仍不编辑
        self.assertEqual(len(c.edits), 0)
        w("第一段" + "x" * 30)                      # 字数够了 → 编辑
        self.assertEqual(len(c.edits), 1)

    def test_max_edits_cap(self) -> None:
        c = FakeClient()
        w = _writer(c)
        w("start")
        for i in range(60):
            w("start" + "x" * i)
        self.assertLessEqual(len(c.edits), w._MAX_EDITS)

    def test_finalize_owns_message(self) -> None:
        c = FakeClient()
        w = _writer(c)
        w("半截")
        self.assertTrue(w.finalize("完整的最终回复"))     # True=调用方别再发
        self.assertEqual(c.edits[-1][2], "完整的最终回复")

    def test_finalize_skips_redundant_edit(self) -> None:
        c = FakeClient()
        w = _writer(c)
        w("就这些")
        n = len(c.edits)
        self.assertTrue(w.finalize("就这些"))            # 草稿已是最终文本
        self.assertEqual(len(c.edits), n)                # 不多发一条编辑事件

    def test_finalize_without_draft_returns_false(self) -> None:
        """引擎没吐过正文（如纯工具调用）→ 没有草稿 → 调用方照常走一次性发送。"""
        c = FakeClient()
        w = _writer(c)
        self.assertFalse(w.finalize("最终回复"))

    def test_empty_final_keeps_draft(self) -> None:
        """终止性工具场景：最终回复为空，草稿里的引导语保留、不再发空消息。"""
        c = FakeClient()
        w = _writer(c)
        w("我看到有同名专班，请选择：")
        self.assertTrue(w.finalize(""))
        self.assertEqual(len(c.sent), 1)

    def test_send_failure_disables_and_falls_back(self) -> None:
        c = FakeClient(fail_send=True)
        w = _writer(c)
        w("你好")
        self.assertTrue(w._broken)
        self.assertFalse(w.finalize("最终"))            # False=调用方必须自己发
        self.assertEqual(c.sent, [])

    def test_edit_failure_at_finalize_falls_back(self) -> None:
        """定格失败时必须回落——否则用户只能看到半截话。"""
        c = FakeClient(fail_edit_after=0)               # 第一次编辑就失败
        w = _writer(c)
        w("半截")
        self.assertFalse(w.finalize("完整回复"))

    def test_puppet_identity_uses_as_apis(self) -> None:
        c = FakeClient()
        w = _writer(c, as_user="@guduu-ai-copywriter:h")
        w("同事说话")
        w("同事说话，继续")
        self.assertEqual(c.sent[0][2], "@guduu-ai-copywriter:h")
        self.assertEqual(c.edits[0][3], "@guduu-ai-copywriter:h")

    def test_blank_partial_ignored(self) -> None:
        c = FakeClient()
        w = _writer(c)
        w("   ")
        w("")
        self.assertEqual(c.sent, [])


if __name__ == "__main__":
    unittest.main()
