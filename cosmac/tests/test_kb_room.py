"""频道知识库（SCOPE_ROOM）上传/列出/删除的授权与越权回归测试。

红线：
  - 上传/删除仅**频道管理员**(power≥50)；普通成员 403。
  - 列出仅**频道成员**；非成员 403。
  - 删除做越权防护：只能删属于**本频道**的文档（防遍历 id 删别处的库）。
"""

from __future__ import annotations

import unittest
from typing import Optional

from cosmac.bots.appservice_bot import CosmacBot
from cosmac.config import CosmacConfig
from cosmac.db import init_engine

ROOM = "!room:h"
OTHER = "!other:h"
BOSS = "@boss:h"    # 本频道管理员 power=100
MEM = "@mem:h"      # 本频道普通成员 power=0
OUT = "@out:h"      # 非本频道成员


class FakeClient:
    def __init__(self) -> None:
        self.tokens = {"tok_boss": BOSS, "tok_mem": MEM, "tok_out": OUT}
        self._members = {ROOM: {BOSS, MEM}}

    def whoami(self, token: str) -> Optional[str]:
        return self.tokens.get(token)

    def resolve_alias(self, _alias: str) -> Optional[str]:
        return "!ctrl:h"

    def get_state_event(self, room_id, event_type, _state_key=""):
        if event_type != "m.room.power_levels":
            return None  # cosmac.gating / cosmac.members 等 → 走默认(free,放行)
        if room_id == ROOM:
            return {"users": {BOSS: 100, MEM: 0}}
        return {"users": {}}

    def is_joined_member(self, room_id: str, user_id: str) -> bool:
        return user_id in self._members.get(room_id, set())


def _bot() -> CosmacBot:
    bot = CosmacBot(CosmacConfig(llm_provider="echo"))
    bot.client = FakeClient()
    return bot


class TestKbRoom(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)
        self.bot = _bot()
        # 隔离 knowledge 门控：无控制室时 GatingStore 会 fail-closed 到"仅管理员"(安全设计)。
        # 这里只测 KB 房间级授权(成员/管理员/越权),门控另有测试,故直接放行。
        self.bot._gate_allows = lambda *a, **k: True  # type: ignore

    def test_admin_add_list_delete(self) -> None:
        # 管理员上传 → 200，列出可见；删除后清零。
        code, payload = self.bot.handle_kb_room_add(
            "tok_boss", {"room_id": ROOM, "title": "手册", "content": "小儿推拿步骤如下……"})
        self.assertEqual(code, 200, payload)
        doc_id = payload["id"]

        code, payload = self.bot.handle_kb_room_list("tok_boss", ROOM)
        self.assertEqual(code, 200)
        self.assertEqual([d["title"] for d in payload["docs"]], ["手册"])

        # 成员也能读（列出）
        code, payload = self.bot.handle_kb_room_list("tok_mem", ROOM)
        self.assertEqual(code, 200)
        self.assertEqual(len(payload["docs"]), 1)

        code, payload = self.bot.handle_kb_room_delete("tok_boss", {"room_id": ROOM, "id": doc_id})
        self.assertEqual(code, 200)
        code, payload = self.bot.handle_kb_room_list("tok_boss", ROOM)
        self.assertEqual(payload["docs"], [])

    def test_member_cannot_add_or_delete(self) -> None:
        # 普通成员(power=0)不能上传/删除。
        code, _ = self.bot.handle_kb_room_add(
            "tok_mem", {"room_id": ROOM, "title": "x", "content": "y"})
        self.assertEqual(code, 403)
        code, _ = self.bot.handle_kb_room_delete("tok_mem", {"room_id": ROOM, "id": 1})
        self.assertEqual(code, 403)

    def test_non_member_cannot_list(self) -> None:
        code, _ = self.bot.handle_kb_room_list("tok_out", ROOM)
        self.assertEqual(code, 403)

    def test_delete_cross_room_blocked(self) -> None:
        # 越权防护：删一个不属于本频道的文档 → 404（即便你是本频道管理员）。
        from cosmac.db import kb, session_scope
        from cosmac.db.models import SCOPE_ROOM

        with session_scope() as s:
            other = kb.ingest_document(
                s, scope=SCOPE_ROOM, scope_id=OTHER, title="别的频道", source="upload", text="内容")
            other_id = other.id
        code, _ = self.bot.handle_kb_room_delete("tok_boss", {"room_id": ROOM, "id": other_id})
        self.assertEqual(code, 404)

    def test_empty_content_rejected(self) -> None:
        code, _ = self.bot.handle_kb_room_add(
            "tok_boss", {"room_id": ROOM, "title": "空", "content": "   "})
        self.assertEqual(code, 400)


class TestKbScopeAuthz(unittest.TestCase):
    """#4 越权防护：kbScopes 绑定的 user:/room: 来源，检索时按成员资格授权，不得裸读他人库。"""

    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)
        self.bot = _bot()
        self.bot._gate_allows = lambda *a, **k: True  # type: ignore

    def _seed_user_kb(self, uid: str) -> None:
        from cosmac.db import kb, session_scope
        from cosmac.db.models import SCOPE_USER
        with session_scope() as s:
            kb.ingest_document(
                s, scope=SCOPE_USER, scope_id=uid,
                title="机密周报", source="upload",
                text="季度机密营收数据与复盘要点：营收增长三成，核心指标周报复盘。")

    _Q = "机密 营收 周报 复盘 数据"

    def test_bind_non_member_personal_kb_blocked(self) -> None:
        # 攻击者在自己的房间绑 user:@受害者；受害者非本房成员 → 检索不到其个人库。
        self._seed_user_kb(OUT)  # @out 是"受害者"，不在 ROOM 里
        hits = self.bot._kb_retrieve(
            ROOM, BOSS, self._Q, bound_sources=[f"user:{OUT}"])
        titles = [t for t, _txt, _s in hits]
        self.assertNotIn("机密周报", titles)

    def test_bind_member_personal_kb_allowed(self) -> None:
        # 合法：属主是本频道成员（发起人把自己的库开放给专班）→ 检索得到。
        self._seed_user_kb(MEM)  # @mem 是 ROOM 成员
        hits = self.bot._kb_retrieve(
            ROOM, BOSS, self._Q, bound_sources=[f"user:{MEM}"])
        titles = [t for t, _txt, _s in hits]
        self.assertIn("机密周报", titles)

    def test_bind_room_kb_requires_sender_membership(self) -> None:
        # 绑 room:!别的频道，但当前发言人不是该频道成员 → 跨频道读被拒。
        from cosmac.db import kb, session_scope
        from cosmac.db.models import SCOPE_ROOM
        with session_scope() as s:
            kb.ingest_document(
                s, scope=SCOPE_ROOM, scope_id=OTHER,
                title="别的频道机密", source="upload",
                text="季度机密营收数据与复盘要点：营收增长三成，核心指标周报复盘。")
        # BOSS 不是 OTHER 的成员（FakeClient._members 只把 BOSS/MEM 放进 ROOM）
        hits = self.bot._kb_retrieve(
            ROOM, BOSS, self._Q, bound_sources=[f"room:{OTHER}"])
        titles = [t for t, _txt, _s in hits]
        self.assertNotIn("别的频道机密", titles)


if __name__ == "__main__":
    unittest.main()
