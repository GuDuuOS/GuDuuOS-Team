"""个人协作人能力名册（模块3.5）单元测试：repo + bot 端点 + 合并/隔离。

内存 SQLite、零 key。运行：.venv/bin/python -m unittest cosmac.tests.test_person
"""

from __future__ import annotations

import unittest

from cosmac.ai.tools import ToolContext
from cosmac.db import init_engine, session_scope
from cosmac.db.person_repo import delete_person, list_people, upsert_person


class TestPersonRepo(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)

    def test_upsert_list_delete(self) -> None:
        with session_scope() as s:
            upsert_person(s, owner="@a:h", person_id="@bob:h", name="小博",
                          role="剪辑", expertise="Pr 卡点")
            upsert_person(s, owner="@a:h", person_id="@cat:h", name="猫", role="设计")
        with session_scope() as s:
            ppl = list_people(s, "@a:h")
        self.assertEqual({p.person_id for p in ppl}, {"@bob:h", "@cat:h"})
        # 更新同一条不新增
        with session_scope() as s:
            upsert_person(s, owner="@a:h", person_id="@bob:h", expertise="改了")
        with session_scope() as s:
            ppl = list_people(s, "@a:h")
            bob = next(p for p in ppl if p.person_id == "@bob:h")
        self.assertEqual(len(ppl), 2)
        self.assertEqual(bob.expertise, "改了")
        # 删除
        with session_scope() as s:
            self.assertTrue(delete_person(s, "@a:h", "@bob:h"))
        with session_scope() as s:
            self.assertEqual([p.person_id for p in list_people(s, "@a:h")], ["@cat:h"])

    def test_owner_isolation(self) -> None:
        with session_scope() as s:
            upsert_person(s, owner="@a:h", person_id="@x:h")
            upsert_person(s, owner="@b:h", person_id="@y:h")
        with session_scope() as s:
            self.assertEqual([p.person_id for p in list_people(s, "@a:h")], ["@x:h"])
            self.assertEqual([p.person_id for p in list_people(s, "@b:h")], ["@y:h"])


def _bot():
    from cosmac.bots.appservice_bot import CosmacBot
    from cosmac.config import CosmacConfig

    # server_name 对齐测试域名(:h)——能力名册按 server_name 过滤外域假号,不对齐会误滤 @bob:h。
    bot = CosmacBot(CosmacConfig(llm_provider="echo", server_name="h"))
    bot._gate_allows = lambda u, c: True  # type: ignore
    return bot


class TestPersonEndpointsAndMerge(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)

    def test_endpoints_and_capability_merge_isolation(self) -> None:
        bot = _bot()
        bot.client.whoami = lambda t: {"a": "@alice:h", "c": "@carol:h"}.get(t)  # type: ignore
        # 未登录
        self.assertEqual(bot.handle_people_add("", {"person_id": "@b:h"})[0], 401)
        # 非法 id
        self.assertEqual(bot.handle_people_add("a", {"person_id": "bob"})[0], 400)
        # alice 加一个协作人
        code, _ = bot.handle_people_add("a", {
            "person_id": "@bob:h", "name": "小博", "role": "剪辑", "expertise": "Pr卡点"})
        self.assertEqual(code, 200)
        # 能力名册：alice 下达 → 含 @bob:h
        out_a = bot._list_capabilities_for_tool(ToolContext("!r:h", "@alice:h"))
        self.assertIn("@bob:h", out_a)
        self.assertIn("卡点", out_a)
        # 隔离：carol 下达 → 看不到 alice 的个人协作人
        out_c = bot._list_capabilities_for_tool(ToolContext("!r:h", "@carol:h"))
        self.assertNotIn("@bob:h", out_c)
        # 删除
        self.assertEqual(bot.handle_people_delete("a", {"person_id": "@bob:h"})[0], 200)
        self.assertEqual(bot.handle_people_list_mine("a")[1]["people"], [])


class TestPersonGating(unittest.TestCase):
    """个人协作人是付费功能：添加受 people_manage 门控。"""

    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)

    def test_add_gated_for_free_user(self) -> None:
        bot = _bot()
        bot.client.whoami = lambda t: "@free:h" if t == "f" else None  # type: ignore
        bot._gate_allows = lambda u, c: c != "people_manage"  # type: ignore
        bot._gate_denied_text = lambda c, ui=False: "需升级会员"  # type: ignore
        code, p = bot.handle_people_add("f", {"person_id": "@x:h"})
        self.assertEqual(code, 403)
        self.assertIn("升级", p["error"])


if __name__ == "__main__":
    unittest.main()
