# -*- coding: utf-8 -*-
"""AI 任务自动执行(_run_agent_tasks)单测:派给 AI 同事的任务真的被执行并回填。

负责人需求背景:专班派单给 copywriter 后没人执行、任务躺在看板超时。
覆盖:成功链路(产出发频道+看板 done+链式上下文)、失败兜底(退回 todo+提示)、
非 agent 任务/已完成任务跳过、单轮上限截断。DB 用内存 SQLite;LLM/Matrix 全打桩。

运行:.venv/bin/python -m unittest cosmac.tests.test_agent_task_autorun
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import List

from cosmac.bots.appservice_bot import CosmacBot
from cosmac.config import CosmacConfig
from cosmac.db import init_engine, session_scope
from cosmac.db.task_repo import create_tasks, get_task

ROOM = "!team:h"
U = "@u:h"

AGENTS = {
    "copywriter": {"slug": "copywriter", "name": "文案", "system_prompt": "你是文案专家", "model": ""},
    "analyst": {"slug": "analyst", "name": "数据分析", "system_prompt": "你是分析师", "model": ""},
}


class _FakeLLM:
    """打桩 LLM:记录收到的消息;可配置抛错。"""

    def __init__(self) -> None:
        self.calls: List[list] = []
        self.fail_on: set = set()  # 第 N 次调用抛错(1 起)

    def complete(self, messages) -> str:
        self.calls.append(messages)
        if len(self.calls) in self.fail_on:
            raise RuntimeError("LLM 挂了")
        return f"产出#{len(self.calls)}"


class _C:
    def __init__(self) -> None:
        self.sent: List[tuple] = []

    def send_text(self, room_id, text):
        self.sent.append((room_id, text))
        return "$evt"

    def whoami(self, token):
        return U

    def resolve_alias(self, alias):
        return None

    def get_state_event(self, *a, **k):
        return None

    def set_displayname(self, *a, **k):
        pass


def _bot(llm: _FakeLLM) -> CosmacBot:
    bot = CosmacBot(CosmacConfig(llm_provider="echo", server_name="h"))
    bot.client = _C()
    bot._find_global_agent = lambda slug: AGENTS.get(slug)  # type: ignore
    bot._agent_for_model = lambda m: SimpleNamespace(llm=llm)  # type: ignore
    return bot


def _mk_tasks(items) -> List[int]:
    with session_scope() as s:
        created = create_tasks(s, goal="车位抓阄", items=items, room_id=ROOM, sender=U)
        return [t.id for t in created]


def _task(tid: int):
    with session_scope() as s:
        t = get_task(s, tid)
        return SimpleNamespace(status=t.status, result=t.result, progress=t.progress)


class TestAgentTaskAutorun(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)
        self.llm = _FakeLLM()
        self.bot = _bot(self.llm)

    def test_success_chain(self) -> None:
        ids = _mk_tasks([
            {"title": "制定抓阄规则", "executor_kind": "agent", "executor_ref": "copywriter"},
            {"title": "风险分析", "executor_kind": "agent", "executor_ref": "analyst"},
        ])
        self.bot._run_agent_tasks(ROOM, U, ids, task_rule="按时交付")
        # 两个任务都完成、result 回填
        for tid in ids:
            t = _task(tid)
            self.assertEqual(t.status, "done")
            self.assertEqual(t.progress, 100)
            self.assertTrue(t.result.startswith("产出#"))
        # 产出发进了专班频道(两条交付 + 一条收尾汇报)
        texts = [x[1] for x in self.bot.client.sent]
        self.assertTrue(any("【文案】交付任务" in x for x in texts))
        self.assertTrue(any("【数据分析】交付任务" in x for x in texts))
        self.assertTrue(any("成功 2/2" in x for x in texts))
        # 链式上下文:第二个任务的 user 消息里带上了第一个任务的产出;RULE 注入 system
        second_msgs = self.llm.calls[1]
        self.assertIn("产出#1", second_msgs[1].content)
        self.assertIn("按时交付", second_msgs[0].content)

    def test_failure_falls_back_to_todo(self) -> None:
        self.llm.fail_on = {1}
        ids = _mk_tasks([
            {"title": "制定规则", "executor_kind": "agent", "executor_ref": "copywriter"},
            {"title": "风险分析", "executor_kind": "agent", "executor_ref": "analyst"},
        ])
        self.bot._run_agent_tasks(ROOM, U, ids, task_rule="")
        # 第一个失败:退回 todo、result 记录原因;第二个不受阻断、照常完成
        t1, t2 = _task(ids[0]), _task(ids[1])
        self.assertEqual(t1.status, "todo")
        self.assertIn("自动执行失败", t1.result)
        self.assertEqual(t2.status, "done")
        texts = [x[1] for x in self.bot.client.sent]
        self.assertTrue(any("自动执行失败" in x for x in texts))
        self.assertTrue(any("成功 1/2" in x for x in texts))

    def test_skips_non_agent_and_done(self) -> None:
        ids = _mk_tasks([
            {"title": "人工任务", "executor_kind": "human", "executor_ref": "@a:h"},
            {"title": "AI任务", "executor_kind": "agent", "executor_ref": "copywriter"},
        ])
        # 人工任务混进 id 列表也会被跳过(只执行 agent 的)
        self.bot._run_agent_tasks(ROOM, U, ids, task_rule="")
        self.assertEqual(_task(ids[0]).status, "todo")
        self.assertEqual(_task(ids[1]).status, "done")
        self.assertEqual(len(self.llm.calls), 1)

    def test_mine_agent_executes_without_puppet(self) -> None:
        """评审 #10 回归:派给发起人自建智能体 → 用其真实人设执行,但不注册全局傀儡。"""
        registered: List[str] = []
        self.bot.client.register_appservice_user = (  # type: ignore
            lambda lp: registered.append(lp) or True)
        self.bot._my_agent_items = lambda owner: [  # type: ignore
            {"slug": "my-writer", "name": "小说写手", "system_prompt": "你是我的写手", "model": ""}
        ] if owner == U else []
        ids = _mk_tasks([{"title": "写一章", "executor_kind": "agent", "executor_ref": "my-writer"}])
        self.bot._run_agent_tasks(ROOM, U, ids, task_rule="")
        self.assertEqual(_task(ids[0]).status, "done")
        # 自建人设进了 system 消息;没有为它注册傀儡账号
        self.assertIn("你是我的写手", self.llm.calls[0][0].content)
        self.assertEqual(registered, [])

    def test_unknown_executor_skipped_with_notice(self) -> None:
        """评审 #10 回归:执行者 slug 全局/自建都查不到 → 不硬跑,留看板+频道提示。"""
        self.bot._my_agent_items = lambda owner: []  # type: ignore
        ids = _mk_tasks([{"title": "神秘任务", "executor_kind": "agent", "executor_ref": "ghost"}])
        self.bot._run_agent_tasks(ROOM, U, ids, task_rule="")
        t = _task(ids[0])
        self.assertEqual(t.status, "todo")
        self.assertIn("不在智能体库", t.result)
        self.assertEqual(len(self.llm.calls), 0)  # 没拿空人设烧 LLM
        texts = [x[1] for x in self.bot.client.sent]
        self.assertTrue(any("不在智能体库" in x for x in texts))

    def test_quota_stops_execution(self) -> None:
        """评审 #5 回归:发起人当日 AI 额度用完 → 停止剩余任务并在频道说明,成功才扣额。"""
        consumed: List[bool] = []

        def _quota(user_id, metric, consume=True):
            # 前 1 次放行;之后按"额度用完"拦。consume=True 的调用单独记数。
            if consume:
                consumed.append(True)
                return None
            return None if len(consumed) < 1 else "额度用完"

        self.bot._rate_quota_blocked = _quota  # type: ignore
        ids = _mk_tasks([
            {"title": f"任务{i}", "executor_kind": "agent", "executor_ref": "copywriter"}
            for i in range(3)
        ])
        self.bot._run_agent_tasks(ROOM, U, ids, task_rule="")
        # 只执行了第 1 个(成功后扣 1 次额度),后 2 个因超额停住、留在看板
        self.assertEqual(len(self.llm.calls), 1)
        self.assertEqual(consumed, [True])
        self.assertEqual(_task(ids[0]).status, "done")
        self.assertEqual(_task(ids[1]).status, "todo")
        texts = [x[1] for x in self.bot.client.sent]
        self.assertTrue(any("额度已用完" in x for x in texts))

    def test_round_cap(self) -> None:
        items = [{"title": f"任务{i}", "executor_kind": "agent", "executor_ref": "copywriter"}
                 for i in range(10)]
        ids = _mk_tasks(items)
        self.bot._run_agent_tasks(ROOM, U, ids, task_rule="")
        # 只执行前 8 个(单轮上限),其余留看板;收尾汇报提到超限
        self.assertEqual(len(self.llm.calls), 8)
        self.assertEqual(_task(ids[8]).status, "todo")
        texts = [x[1] for x in self.bot.client.sent]
        self.assertTrue(any("超出单轮上限" in x for x in texts))


if __name__ == "__main__":
    unittest.main()
