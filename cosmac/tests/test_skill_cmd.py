"""「技能」聊天命令的单元测试（内存 SQLite，纯逻辑、不连 Matrix）。

运行：.venv/bin/python -m unittest cosmac.tests.test_skill_cmd
"""

from __future__ import annotations

import unittest

from cosmac.db import init_engine, session_scope
from cosmac.db import repo
from cosmac.db.models import SCOPE_ROOM, SCOPE_USER
from cosmac.db.skill_cmd import handle_skill_command, looks_like_skill_command

ROOM = "!ops:example.invalid"
USER = "@alice:example.invalid"


def run(text: str, *, is_dm: bool = False, can_write: bool = True) -> str:
    with session_scope() as s:
        return handle_skill_command(
            s,
            is_dm=is_dm,
            room_id=ROOM,
            user_id=USER,
            text=text,
            can_write=can_write,
        )


class TestSkillCommandDetect(unittest.TestCase):
    def test_looks_like(self) -> None:
        self.assertTrue(looks_like_skill_command("技能 列表"))
        self.assertTrue(looks_like_skill_command("技能列表"))  # 中文无空格
        self.assertTrue(looks_like_skill_command("/技能 添加 x"))
        self.assertTrue(looks_like_skill_command("skill list"))
        self.assertFalse(looks_like_skill_command("skillful 写法"))  # 词边界，不误伤
        self.assertFalse(looks_like_skill_command("帮我建个群"))


class TestSkillCommand(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)

    def test_help_when_bare(self) -> None:
        self.assertIn("技能命令", run("技能"))
        self.assertIn("技能命令", run("技能 帮助"))

    def test_add_then_listed_and_persisted(self) -> None:
        out = run("技能 添加 weekly-report ｜ 周报 ｜ 按三步生成本周数据周报")
        self.assertIn("已新建", out)
        # 群里建 → room 作用域、room_id = ROOM
        with session_scope() as s:
            sk = repo.get_skill(s, SCOPE_ROOM, ROOM, "weekly-report")
            self.assertIsNotNone(sk)
            assert sk is not None
            self.assertEqual(sk.name, "周报")
            self.assertIn("三步", sk.instructions)
        self.assertIn("weekly-report", run("技能 列表"))

    def test_add_update_does_not_wipe_unset_fields(self) -> None:
        run("技能 添加 kb ｜ 检索 ｜ 原正文")
        # 二次只改名称，不传正文 → 正文应保留
        out = run("技能 添加 kb ｜ 新名")
        self.assertIn("已更新", out)
        with session_scope() as s:
            sk = repo.get_skill(s, SCOPE_ROOM, ROOM, "kb")
            assert sk is not None
            self.assertEqual(sk.name, "新名")
            self.assertEqual(sk.instructions, "原正文")  # 未传 → 不被清空

    def test_disable_enable_delete(self) -> None:
        run("技能 添加 s1 ｜ 技能一")
        self.assertIn("已停用", run("技能 停用 s1"))
        with session_scope() as s:
            sk = repo.get_skill(s, SCOPE_ROOM, ROOM, "s1")
            assert sk is not None
            self.assertFalse(sk.enabled)
        self.assertIn("已启用", run("技能 启用 s1"))
        self.assertIn("已删除", run("技能 删除 s1"))
        self.assertIn("没找到", run("技能 删除 s1"))  # 再删

    def test_dm_scope_is_user(self) -> None:
        # 私聊里建 → 个人技能（user 作用域，scope_id = 发起人）
        run("技能 添加 mine ｜ 我的", is_dm=True)
        with session_scope() as s:
            self.assertIsNotNone(repo.get_skill(s, SCOPE_USER, USER, "mine"))
            # 不会落到 room 作用域
            self.assertIsNone(repo.get_skill(s, SCOPE_ROOM, ROOM, "mine"))

    def test_add_requires_slug(self) -> None:
        self.assertIn("不能为空", run("技能 添加 ｜ 只有名称"))

    def test_unknown_subcommand(self) -> None:
        self.assertIn("没听懂", run("技能 乱七八糟"))

    # —— #1 群级写权限闸 ——
    def test_non_admin_cannot_write_room_skill(self) -> None:
        # 非管理员（can_write=False）在群里改技能被挡，但仍能查看
        self.assertIn("只有群管理员", run("技能 添加 x ｜ 名", can_write=False))
        self.assertIn("只有群管理员", run("技能 删除 x", can_write=False))
        self.assertIn("只有群管理员", run("技能 停用 x", can_write=False))
        self.assertNotIn("只有群管理员", run("技能 列表", can_write=False))  # 查看放行
        # 确实没写进去
        with session_scope() as s:
            self.assertIsNone(repo.get_skill(s, SCOPE_ROOM, ROOM, "x"))

    def test_non_admin_can_write_own_dm_skill(self) -> None:
        # 私聊个人技能不受 can_write 影响（只影响自己）
        out = run("技能 添加 mine ｜ 我的", is_dm=True, can_write=False)
        self.assertIn("已新建", out)
        with session_scope() as s:
            self.assertIsNotNone(repo.get_skill(s, SCOPE_USER, USER, "mine"))

    # —— #2 容量上限 ——
    def test_instructions_length_capped(self) -> None:
        from cosmac.db.skill_cmd import MAX_INSTRUCTIONS_LEN
        long_body = "字" * (MAX_INSTRUCTIONS_LEN + 1)
        self.assertIn("正文太长", run(f"技能 添加 big ｜ 名 ｜ {long_body}"))

    def test_count_cap_per_scope(self) -> None:
        from cosmac.db.skill_cmd import MAX_SKILLS_PER_SCOPE
        for i in range(MAX_SKILLS_PER_SCOPE):
            run(f"技能 添加 s{i} ｜ 技能{i}")
        out = run("技能 添加 overflow ｜ 超额")
        self.assertIn("数量上限", out)
        with session_scope() as s:
            self.assertIsNone(repo.get_skill(s, SCOPE_ROOM, ROOM, "overflow"))


if __name__ == "__main__":
    unittest.main()
