# -*- coding: utf-8 -*-
"""个人标注 ↔ 平台能力打通单测(负责人拍板 A+B)。

背景:前台「我的协作人」是**个人级**名册(按 owner 隔离,存 cosmac DB),后台「人员能力」
是**平台级**(控制室 cosmac.people),两套互不可见,负责人实报"设置后没同步"。
A: handle_admin_people_notes —— 管理员只读聚合全平台个人标注;
B: handle_people_promote —— 管理员把自己的一条个人标注提升为平台能力(幂等覆盖同 id)。

运行:.venv/bin/python -m unittest cosmac.tests.test_people_sync
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, List, Optional

from cosmac.bots.appservice_bot import CosmacBot
from cosmac.config import PEOPLE_EVENT_TYPE, CosmacConfig
from cosmac.db import init_engine, session_scope
from cosmac.db.person_repo import upsert_person

ME = "@boss:h"
OTHER = "@lisi:h"


class _C:
    """打桩:控制室可读写 cosmac.people。"""

    def __init__(self, people: Optional[List[Dict[str, Any]]] = None) -> None:
        self.state: Dict[str, Any] = {PEOPLE_EVENT_TYPE: {"people": people or []}}
        self.writes: List[Any] = []
        self.can_write = True

    def resolve_alias(self, a):
        return "!ctrl:h"

    def get_state_event(self, room, etype, state_key=""):
        return self.state.get(etype)

    def set_state_event(self, room, etype, content, state_key=""):
        if not self.can_write:
            return None
        self.state[etype] = content
        self.writes.append(content)
        return "$e"

    def whoami(self, t):
        return ME

    def set_displayname(self, *a, **k):
        pass


def _bot(client: _C, is_admin: bool = True) -> CosmacBot:
    bot = CosmacBot(CosmacConfig(llm_provider="echo", server_name="h",
                                 control_room_alias="#cosmac-ctrl:h"))
    bot.client = client  # type: ignore
    bot._is_platform_admin = lambda uid: is_admin  # type: ignore
    return bot


class TestAdminPeopleNotes(unittest.TestCase):
    """A:管理员只读看到全平台个人标注。"""

    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)
        with session_scope() as s:
            upsert_person(s, owner=ME, person_id="@duxz01:h", role="内容编辑", expertise="校对润色")
            upsert_person(s, owner=OTHER, person_id="@duxz01:h", role="文案", expertise="标题")

    def test_aggregates_by_person(self) -> None:
        bot = _bot(_C())
        code, out = bot.handle_admin_people_notes("tok")
        self.assertEqual(code, 200)
        notes = out["notes"]["@duxz01:h"]
        self.assertEqual(len(notes), 2)                      # 两个人都标注了同一人
        owners = {n["owner"] for n in notes}
        self.assertEqual(owners, {ME, OTHER})

    def test_admin_only(self) -> None:
        bot = _bot(_C(), is_admin=False)
        code, _ = bot.handle_admin_people_notes("tok")
        self.assertEqual(code, 403)


class TestPromote(unittest.TestCase):
    """B:个人标注提升为平台能力。"""

    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)
        with session_scope() as s:
            upsert_person(s, owner=ME, person_id="@duxz01:h", name="小杜",
                          role="内容编辑", expertise="校对润色")

    def test_promote_writes_platform_roster(self) -> None:
        c = _C()
        bot = _bot(c)
        code, out = bot.handle_people_promote("tok", {"person_id": "@duxz01:h"})
        self.assertEqual(code, 200)
        people = c.state[PEOPLE_EVENT_TYPE]["people"]
        self.assertEqual(len(people), 1)
        self.assertEqual(people[0]["user_id"], "@duxz01:h")
        self.assertEqual(people[0]["role"], "内容编辑")

    def test_promote_overwrites_same_id_keeps_others(self) -> None:
        # 平台已有同一人的旧值 + 另一个人:同 id 覆盖,别人原样保留(幂等)
        c = _C([
            {"user_id": "@duxz01:h", "role": "旧角色", "expertise": "旧擅长"},
            {"user_id": "@keep:h", "role": "别动我", "expertise": "x"},
        ])
        bot = _bot(c)
        bot.handle_people_promote("tok", {"person_id": "@duxz01:h"})
        people = {p["user_id"]: p for p in c.state[PEOPLE_EVENT_TYPE]["people"]}
        self.assertEqual(people["@duxz01:h"]["role"], "内容编辑")   # 被新值覆盖
        self.assertEqual(people["@keep:h"]["role"], "别动我")       # 其他条目不动

    def test_promote_requires_admin(self) -> None:
        bot = _bot(_C(), is_admin=False)
        code, _ = bot.handle_people_promote("tok", {"person_id": "@duxz01:h"})
        self.assertEqual(code, 403)

    def test_promote_missing_note_404(self) -> None:
        bot = _bot(_C())
        code, _ = bot.handle_people_promote("tok", {"person_id": "@nobody:h"})
        self.assertEqual(code, 404)

    def test_promote_reports_write_failure(self) -> None:
        # 没有控制室写权限时如实报错,不假装成功(否则用户以为同步了其实没有)
        c = _C()
        c.can_write = False
        bot = _bot(c)
        code, out = bot.handle_people_promote("tok", {"person_id": "@duxz01:h"})
        self.assertEqual(code, 500)
        self.assertIn("失败", out["error"])


if __name__ == "__main__":
    unittest.main()
