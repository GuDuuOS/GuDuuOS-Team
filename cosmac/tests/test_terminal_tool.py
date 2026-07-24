# -*- coding: utf-8 -*-
"""终止性工具单测(负责人实报:AI 发了「同名专班怎么处理」选项卡却没等点选,又建了
第二个同名专班)。

ask_user_choice 是终止性工具:Agent 执行到它必须**立即结束本轮**,不再进入下一轮、
不调后续工具。本测用假 LLM 编排「第1轮调 ask_user_choice,若循环继续则第2轮会调
create_room」的脚本,验证 create_room **绝不被执行**。

运行:.venv/bin/python -m unittest cosmac.tests.test_terminal_tool
"""

from __future__ import annotations

import unittest
from typing import List

from cosmac.ai.agent import Agent
from cosmac.ai.base import LLMProvider, Message, ToolCall, ToolSpec, TurnResult
from cosmac.ai.tools import Toolbox, ToolContext
from cosmac.db import init_engine


class _Client:
    def __init__(self) -> None:
        self.cards: List[tuple] = []
        self.created: List[str] = []

    def send_card(self, room_id, body, card):
        self.cards.append((room_id, card))
        return "$card"

    def create_room(self, name, invitees=None, admins=None):
        self.created.append(name)
        return "!new:h"

    def set_state_event(self, *a, **k):
        return "$e"

    def get_state_event(self, *a, **k):
        return None

    def joined_member_count(self, room_id):
        return 2


class _ScriptLLM(LLMProvider):
    """按脚本逐轮返回;记录被调过几轮,便于断言循环是否提前终止。"""

    name = "script"

    def __init__(self, script: List[TurnResult]) -> None:
        self._script = script
        self.rounds = 0

    def complete(self, messages: List[Message]) -> str:
        return ""

    def complete_with_tools(self, messages, tools: List[ToolSpec]) -> TurnResult:
        r = self._script[min(self.rounds, len(self._script) - 1)]
        self.rounds += 1
        return r


class TestTerminalTool(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)
        self.client = _Client()
        self.tb = Toolbox(self.client)

    def test_ask_user_choice_stops_the_loop(self) -> None:
        # 脚本:第1轮发选择卡;第2轮(不该发生)会建群。若终止生效,第2轮永不执行。
        script = [
            TurnResult(text="我看看有没有同名的", tool_calls=[
                ToolCall(id="c1", name="ask_user_choice", arguments={
                    "question": "已有同名专班,怎么处理?",
                    "options": [{"label": "用已有的"}, {"label": "新建一个"}],
                })]),
            TurnResult(tool_calls=[
                ToolCall(id="c2", name="create_room", arguments={"name": "卡卡形象设计"})]),
            TurnResult(text="（不该到这）"),
        ]
        llm = _ScriptLLM(script)
        agent = Agent(llm=llm, toolbox=self.tb, system_prompt="x")
        out = agent.run("帮我建专班卡卡形象设计", ToolContext("!r:h", "@u:h", is_dm=True))
        # 选择卡发了、群绝不能建、循环只跑了 1 轮(没进第2轮)
        self.assertEqual(len(self.client.cards), 1)
        self.assertEqual(self.client.created, [])
        self.assertEqual(llm.rounds, 1)
        # 返回模型调工具前的引导语(交给 bot,bot 判空/非空决定发不发)
        self.assertEqual(out, "我看看有没有同名的")

    def test_is_terminal_flag(self) -> None:
        self.assertTrue(self.tb.is_terminal("ask_user_choice"))
        self.assertFalse(self.tb.is_terminal("create_room"))


if __name__ == "__main__":
    unittest.main()
