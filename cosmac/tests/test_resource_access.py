# -*- coding: utf-8 -*-
"""资源级「可用范围」(access)判定的单元测试。

覆盖判定矩阵(所有人/等级/仅管理员/指定模板/未知值容错)与
_global_skill_items(for_user=...) 的过滤生效。不连 Synapse、不连 DB
(管理员判定/等级/模板查询全部打桩)。

运行:.venv/bin/python -m unittest cosmac.tests.test_resource_access
"""

from __future__ import annotations

import unittest

from cosmac.bots.appservice_bot import CosmacBot
from cosmac.config import CosmacConfig

CTRL = "!ctrl:test"


class FakeClient:
    """只喂控制室技能 state 的假 client。"""

    def __init__(self, skills):
        self._skills = skills

    def set_displayname(self, *_a, **_k):
        pass

    def resolve_alias(self, _alias):
        return CTRL

    def get_state_event(self, room_id, etype, state_key=""):
        if etype == "cosmac.skills" and room_id == CTRL:
            return {"skills": self._skills}
        return None


def _bot(skills=None) -> CosmacBot:
    bot = CosmacBot(CosmacConfig(llm_provider="echo"))
    bot.client = FakeClient(skills or [])
    # 打桩:管理员/等级/模板三个依赖(真实现分别读控制室/members/DB)
    bot._is_platform_admin = lambda uid: uid == "@adm:test"  # type: ignore
    bot.members.get_tier = lambda uid: {  # type: ignore
        "@paid:test": "paid", "@creator:test": "creator",
    }.get(uid, "free")
    bot._user_template = lambda uid: {"@edu:test": "edu-tpl"}.get(uid, "")  # type: ignore
    return bot


class TestResourceVisible(unittest.TestCase):
    def setUp(self) -> None:
        self.bot = _bot()

    def test_public_and_empty_visible_to_all(self) -> None:
        for access in ("", "public", None):
            self.assertTrue(self.bot._resource_visible({"access": access}, "@free:test"))

    def test_admin_only(self) -> None:
        item = {"access": "admin"}
        self.assertTrue(self.bot._resource_visible(item, "@adm:test"))
        self.assertFalse(self.bot._resource_visible(item, "@paid:test"))

    def test_tier_threshold(self) -> None:
        item = {"access": "paid"}
        self.assertFalse(self.bot._resource_visible(item, "@free:test"))
        self.assertTrue(self.bot._resource_visible(item, "@paid:test"))
        self.assertTrue(self.bot._resource_visible(item, "@creator:test"))  # 更高档也行
        self.assertTrue(self.bot._resource_visible(item, "@adm:test"))      # 管理员永远可用

    def test_template_scoped(self) -> None:
        item = {"access": "tpl:edu-tpl,film-tpl"}
        self.assertTrue(self.bot._resource_visible(item, "@edu:test"))
        self.assertFalse(self.bot._resource_visible(item, "@free:test"))  # 没选模板
        self.assertTrue(self.bot._resource_visible(item, "@adm:test"))

    def test_unknown_value_fails_open(self) -> None:
        # 后台写坏一个值不至于全员失效——未知取值按所有人可见
        self.assertTrue(self.bot._resource_visible({"access": "whatever"}, "@free:test"))


class TestSkillItemsFiltered(unittest.TestCase):
    def test_for_user_filters_by_access(self) -> None:
        skills = [
            {"slug": "a", "enabled": True},                       # 所有人
            {"slug": "b", "enabled": True, "access": "paid"},     # 付费+
            {"slug": "c", "enabled": True, "access": "admin"},    # 仅管理员
            {"slug": "d", "enabled": True, "access": "tpl:edu-tpl"},
        ]
        bot = _bot(skills)
        # 不传 for_user:全量(资源存在性校验等配置场景)
        self.assertEqual({s["slug"] for s in bot._global_skill_items()}, {"a", "b", "c", "d"})
        # 免费用户:只剩公共
        self.assertEqual(
            {s["slug"] for s in bot._global_skill_items(for_user="@free:test")}, {"a"}
        )
        # 付费用户:公共+付费
        self.assertEqual(
            {s["slug"] for s in bot._global_skill_items(for_user="@paid:test")}, {"a", "b"}
        )
        # edu 模板用户(免费档):公共+模板专属
        self.assertEqual(
            {s["slug"] for s in bot._global_skill_items(for_user="@edu:test")}, {"a", "d"}
        )
        # 管理员:全量
        self.assertEqual(
            {s["slug"] for s in bot._global_skill_items(for_user="@adm:test")},
            {"a", "b", "c", "d"},
        )


if __name__ == "__main__":
    unittest.main()
