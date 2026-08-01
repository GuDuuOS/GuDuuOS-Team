"""cosmac.db.service（技能 → 提示）的单元测试。

内存 SQLite，纯逻辑：验证按作用域汇总生效技能的顺序/过滤，以及渲染成提示文本。
运行：.venv/bin/python -m unittest cosmac.tests.test_skill_service
"""

from __future__ import annotations

import unittest

from cosmac.db import init_engine, session_scope
from cosmac.db import repo
from cosmac.db.models import SCOPE_GLOBAL, SCOPE_ROOM, SCOPE_USER
from cosmac.db.service import (
    effective_skill_prompt,
    effective_skills,
    render_skill_prompt,
)

ROOM = "!ops:example.invalid"
USER = "@alice:example.invalid"


class TestSkillService(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)

    def _seed(self) -> None:
        with session_scope() as s:
            repo.upsert_skill(s, SCOPE_GLOBAL, "", "g", name="全局技能", instructions="G")
            repo.upsert_skill(s, SCOPE_ROOM, ROOM, "r", name="群技能", instructions="R")
            repo.upsert_skill(s, SCOPE_USER, USER, "u", name="个人技能", instructions="U")
            # 停用的不应出现
            repo.upsert_skill(s, SCOPE_ROOM, ROOM, "off", name="停用", enabled=False)
            # 别的房间的不应出现
            repo.upsert_skill(s, SCOPE_ROOM, "!other:x", "x", name="别群")

    def test_effective_order_and_scoping(self) -> None:
        self._seed()
        with session_scope() as s:
            got = effective_skills(s, room_id=ROOM, user_id=USER)
            names = [k.name for k in got]
            # 顺序：全局 → 本群 → 本人；停用 / 别群 都不在
            self.assertEqual(names, ["全局技能", "群技能", "个人技能"])

    def test_only_global_when_no_context(self) -> None:
        self._seed()
        with session_scope() as s:
            got = effective_skills(s)  # 无房间/无人 → 只剩全局
            self.assertEqual([k.slug for k in got], ["g"])

    def test_render_and_prompt(self) -> None:
        self._seed()
        with session_scope() as s:
            text = effective_skill_prompt(s, room_id=ROOM, user_id=USER)
        self.assertIn("你已装载以下技能", text)
        self.assertIn("群技能", text)
        self.assertIn("U", text)  # 个人技能正文

    def test_empty_renders_blank(self) -> None:
        # 没有任何技能 → 空串（bot 据此不注入 addendum）
        self.assertEqual(render_skill_prompt([]), "")
        with session_scope() as s:
            self.assertEqual(effective_skill_prompt(s, room_id=ROOM), "")

    def test_total_prompt_capped(self) -> None:
        # #2：技能多了，渲染总长度有上限，超预算停止注入剩余并提示
        from cosmac.db.service import MAX_TOTAL_PROMPT_CHARS

        big = "字" * 1500  # 每条接近上限
        with session_scope() as s:
            for i in range(20):  # 20×1500 远超预算
                repo.upsert_skill(
                    s, SCOPE_ROOM, ROOM, f"s{i}", name=f"技能{i}", instructions=big
                )
            text = effective_skill_prompt(s, room_id=ROOM)
        self.assertLessEqual(len(text), MAX_TOTAL_PROMPT_CHARS + 200)  # 容一句提示的余量
        self.assertIn("未注入", text)


if __name__ == "__main__":
    unittest.main()
