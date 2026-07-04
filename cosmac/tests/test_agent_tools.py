"""Agent 工具调用循环的单元测试。

不依赖运行中的 Synapse、不需要任何 API key：
  - 用一个"假大脑"(FakeLLM) 按脚本先要求调用工具、再给最终答复；
  - 用一个"假 MatrixClient"(FakeClient) 记录工具到底有没有真的被调到。
这样就能纯逻辑验证「模型决定调工具 → 工具真的执行 → 结果回灌 → 给出最终回复」整条链路。

运行：.venv/bin/python -m unittest cosmac.tests.test_agent_tools
"""

from __future__ import annotations

import unittest
from typing import List

from cosmac.ai.agent import Agent
from cosmac.ai.base import LLMProvider, Message, ToolCall, ToolSpec, TurnResult
from cosmac.ai.tools import Toolbox, ToolContext


class FakeClient:
    """假的 MatrixClient：只记录被调用了什么，不连任何服务器。"""

    def __init__(self) -> None:
        self.created: List[str] = []
        self.sent: List[tuple] = []

    def create_room(self, name, invitees=None):
        self.created.append(name)
        return "!fakeroom:test"  # 假装建好了，返回一个 room_id

    def send_text(self, room_id, text):
        self.sent.append((room_id, text))
        return "$fakeevent"

    def get_members(self, room_id):
        return [{"user_id": "@alice:test", "display_name": "Alice"}]

    def get_messages(self, room_id, limit=20):
        return [{"sender": "@alice:test", "body": "历史消息一条"}]

    def is_joined_member(self, room_id, user_id):
        return room_id == "!allowed:test" and user_id == "@alice:test"

    # 工作流越权闸用：当作 1:1 私聊（放行），不干扰工具执行测试
    def joined_member_count(self, room_id):
        return 2

    def get_state_event(self, room_id, etype, state_key=""):
        # !named:test 房有名字(给 list_my_rooms 测试);其余无 state
        if etype == "m.room.name" and room_id == "!allowed:test":
            return {"name": "测试频道"}
        return None

    def joined_rooms(self):
        # bot 在两个房:用户 alice 只在 !allowed:test(见 is_joined_member)
        return ["!allowed:test", "!secret:test"]

    def invite_user(self, room_id, user_id):
        return True

    def set_state_event(self, room_id, etype, content, state_key=""):
        self.states = getattr(self, "states", [])
        self.states.append((room_id, etype, content))
        return "$stateevent"

    def send_card(self, room_id, text, data):
        return "$cardevent"


class FakeLLM(LLMProvider):
    """假大脑：按预设脚本逐轮返回 TurnResult（先调工具，再给最终文本）。"""

    name = "fake"

    def __init__(self, script: List[TurnResult]) -> None:
        self._script = script
        self._i = 0
        self.seen_tools: List[str] = []  # 记录每轮拿到的工具名，验证确实把工具喂进去了
        self.seen_messages: List[Message] = []  # 记录最近一轮的消息，验证 system 注入

    def complete(self, messages: List[Message]) -> str:  # 接口要求，测试用不到
        return "（不该走到这里）"

    def complete_with_tools(self, messages, tools: List[ToolSpec]) -> TurnResult:
        self.seen_tools = [t.name for t in tools]
        self.seen_messages = list(messages)
        result = self._script[self._i]
        self._i += 1
        return result


class TestAgentTools(unittest.TestCase):
    def _agent(self, script):
        self.client = FakeClient()
        toolbox = Toolbox(self.client)  # 真工具箱，但底层是假 client
        llm = FakeLLM(script)
        return Agent(llm=llm, toolbox=toolbox, system_prompt="测试人设"), llm

    def test_model_calls_create_room_then_answers(self) -> None:
        # 脚本：第一轮要求建群，第二轮给最终答复
        script = [
            TurnResult(
                tool_calls=[
                    ToolCall(id="c1", name="create_room", arguments={"name": "爆款专班"})
                ]
            ),
            TurnResult(text="已经帮你把『爆款专班』群建好啦！"),
        ]
        agent, llm = self._agent(script)
        reply = agent.run("帮我建个爆款专班群", ToolContext("!cur:test", "@alice:test"))

        # 工具真的被执行了（假 client 记录到建群）
        self.assertEqual(self.client.created, ["爆款专班"])
        # 最终回复是模型第二轮给的文本
        self.assertEqual(reply, "已经帮你把『爆款专班』群建好啦！")
        # 模型每轮都拿到了 4 个工具的说明书
        self.assertIn("create_room", llm.seen_tools)

    def test_create_room_invites_requester(self) -> None:
        # 验证 ToolContext 注入：建群默认把发起人拉进去
        captured = {}
        client = FakeClient()
        client.create_room = lambda name, invitees=None: (  # type: ignore
            captured.update(name=name, invitees=invitees) or "!r:test"
        )
        toolbox = Toolbox(client)
        out = toolbox.execute(
            ToolCall(id="x", name="create_room", arguments={"name": "群A"}),
            ToolContext("!cur:test", "@bob:test"),
        )
        self.assertEqual(captured["name"], "群A")
        self.assertIn("@bob:test", captured["invitees"])  # 发起人被自动邀请
        self.assertIn("群A", out)

    def test_cross_room_tools_require_sender_membership(self) -> None:
        # 双层作用域后:跨房只在**全局模式(私聊,is_dm=True)**才谈成员身份;频道模式一律锁本房。
        client = FakeClient()
        toolbox = Toolbox(client)
        # 全局模式:非成员房被拒(不越权)
        denied = toolbox.execute(
            ToolCall(id="x", name="get_recent_messages", arguments={"room_id": "!secret:test"}),
            ToolContext("!cur:test", "@alice:test", is_dm=True),
        )
        self.assertIn("不能替你读写", denied)
        # 全局模式:成员房放行
        allowed = toolbox.execute(
            ToolCall(id="x", name="get_recent_messages",
                     arguments={"room_id": "!allowed:test", "limit": 999}),
            ToolContext("!cur:test", "@alice:test", is_dm=True),
        )
        self.assertIn("最近聊天记录", allowed)
        # 频道模式:即便是成员房也锁死(频道分身只看本频道)
        locked = toolbox.execute(
            ToolCall(id="x", name="get_recent_messages", arguments={"room_id": "!allowed:test"}),
            ToolContext("!cur:test", "@alice:test", is_dm=False),
        )
        self.assertIn("专属 AI", locked)

    def test_no_tool_calls_returns_text(self) -> None:
        # 模型不调工具时，直接返回文本
        agent, _ = self._agent([TurnResult(text="你好呀")])
        reply = agent.run("在吗", ToolContext("!c:test", "@a:test"))
        self.assertEqual(reply, "你好呀")

    def test_history_inserted_between_system_and_current(self) -> None:
        # 短期记忆：历史消息应排在 system 之后、当前 user 之前，顺序保留
        agent, llm = self._agent([TurnResult(text="好的")])
        hist = [
            Message(role="user", content="上一句问题"),
            Message(role="assistant", content="上一句回答"),
        ]
        agent.run("现在的问题", ToolContext("!c:test", "@a:test"), history=hist)
        roles = [m.role for m in llm.seen_messages]
        contents = [m.content for m in llm.seen_messages]
        self.assertEqual(roles, ["system", "user", "assistant", "user"])
        self.assertEqual(contents[-3:], ["上一句问题", "上一句回答", "现在的问题"])

    def test_extra_system_merged_into_single_system_message(self) -> None:
        # 技能 addendum 应与常驻人设合并成「单条」system 消息（兼容只认一个 system 的 provider）
        agent, llm = self._agent([TurnResult(text="好的")])
        agent.run("在吗", ToolContext("!c:test", "@a:test"), extra_system="技能说明X")
        systems = [m for m in llm.seen_messages if m.role == "system"]
        self.assertEqual(len(systems), 1)
        self.assertIn("测试人设", systems[0].content)  # 常驻人设
        self.assertIn("技能说明X", systems[0].content)  # 注入的技能

    def test_search_knowledge_forwards_to_injected_callback(self) -> None:
        # search_knowledge 工具应把 query + ctx 转发给 bot 注入的 kb_search 回调
        client = FakeClient()
        toolbox = Toolbox(client)
        captured = {}
        toolbox.kb_search = lambda query, ctx: (  # type: ignore
            captured.update(query=query, room=ctx.room_id) or "命中：《手册》一段资料"
        )
        out = toolbox.execute(
            ToolCall(id="k", name="search_knowledge", arguments={"query": "退款政策"}),
            ToolContext("!cur:test", "@alice:test"),
        )
        self.assertEqual(captured["query"], "退款政策")
        self.assertEqual(captured["room"], "!cur:test")
        self.assertIn("命中", out)

    def test_search_knowledge_graceful_without_callback(self) -> None:
        # 未注入 kb_search（单测/未接 bot）时不报错，返回"不可用"文案
        out = Toolbox(FakeClient()).execute(
            ToolCall(id="k", name="search_knowledge", arguments={"query": "x"}),
            ToolContext("!c:test", "@a:test"),
        )
        self.assertIn("不可用", out)

    def test_search_knowledge_is_default_on(self) -> None:
        # 智能问答核心工具：默认出现在喂给模型的工具清单里
        names = [s.name for s in Toolbox(FakeClient()).specs()]
        self.assertIn("search_knowledge", names)

    def test_web_search_default_on(self) -> None:
        # 联网搜索是"会上网查"的核心，默认出现在工具清单里
        names = [s.name for s in Toolbox(FakeClient()).specs()]
        self.assertIn("web_search", names)

    def test_web_search_degrades_without_key(self) -> None:
        # 没配搜索 key（测试环境）→ get_searcher 降级 Disabled → 工具明确说"未配置"，不报错
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {}, clear=False):
            for k in ("COSMAC_SEARCH_API_KEY", "TAVILY_API_KEY", "BRAVE_API_KEY"):
                os.environ.pop(k, None)
            out = Toolbox(FakeClient()).execute(
                ToolCall(id="w", name="web_search", arguments={"query": "今天的新闻"}),
                ToolContext("!c:test", "@a:test"),
            )
        self.assertIn("未配置", out)

    def test_list_capabilities_forwards_and_default_on(self) -> None:
        # 默认在工具清单里，且把调用转发给注入的 list_capabilities 回调
        toolbox = Toolbox(FakeClient())
        self.assertIn("list_capabilities", [s.name for s in toolbox.specs()])
        seen = {}
        toolbox.list_capabilities = lambda ctx: (  # type: ignore
            seen.update(room=ctx.room_id) or "名册：@a 文案"
        )
        out = toolbox.execute(
            ToolCall(id="c", name="list_capabilities", arguments={}),
            ToolContext("!cur:test", "@alice:test"),
        )
        self.assertEqual(seen["room"], "!cur:test")
        self.assertIn("名册", out)

    def test_list_capabilities_graceful_without_callback(self) -> None:
        out = Toolbox(FakeClient()).execute(
            ToolCall(id="c", name="list_capabilities", arguments={}),
            ToolContext("!c:test", "@a:test"),
        )
        self.assertIn("不可用", out)

    def test_ask_user_choice_sends_choice_card(self) -> None:
        # ask_user_choice 应发一张 cosmac.card{kind:choice} 富卡（带选项），结束本轮等点选
        client = FakeClient()
        sent_cards = []
        client.send_card = lambda room, body, card: (  # type: ignore
            sent_cards.append((room, card)) or "$e"
        )
        out = Toolbox(client).execute(
            ToolCall(id="c", name="ask_user_choice", arguments={
                "question": "邀请谁加入专班？",
                "options": [{"label": "小雨", "value": "@xiaoyu:h"}, {"label": "阿设", "value": "@adesign:h"}],
                "multi": True,
            }),
            ToolContext("!cur:test", "@a:test"),
        )
        self.assertEqual(len(sent_cards), 1)
        room, card = sent_cards[0]
        self.assertEqual(room, "!cur:test")
        self.assertEqual(card["kind"], "choice")
        self.assertTrue(card["multi"])
        self.assertEqual([o["value"] for o in card["options"]], ["@xiaoyu:h", "@adesign:h"])
        self.assertIn("等", out)  # "等 TA 点选后我再继续"

    def test_max_steps_guard(self) -> None:
        # 模型一直要求调工具（不收敛），Agent 应在 max_steps 后兜底退出，不死循环
        loop = TurnResult(
            tool_calls=[ToolCall(id="c", name="list_room_members", arguments={})]
        )
        client = FakeClient()
        agent = Agent(FakeLLM([loop] * 10), Toolbox(client), max_steps=3)
        reply = agent.run("看看谁在", ToolContext("!c:test", "@a:test"))
        self.assertIn("没能完成", reply)


class AssembleTeamGapsTest(unittest.TestCase):
    """组班链路完善:库里没有的资源要提醒缺口;没给任务RULE要自动生成保底。"""

    def setUp(self) -> None:
        self.client = FakeClient()
        self.tb = Toolbox(self.client)
        # 库里只有这些资源
        self.tb.known_agents = lambda: {"planner"}
        self.tb.known_skills = lambda: {"copywriter"}

    def _assemble(self, **kw):
        args = {"project": "测试专班"}
        args.update(kw)
        return self.tb.execute(
            ToolCall(id="x", name="assemble_team", arguments=args),
            ToolContext("!cur:test", "@alice:test", is_dm=True),
        )

    def test_missing_resources_reported(self) -> None:
        out = self._assemble(
            lead_agent="不存在的AI", worker_agents=["planner", "幽灵"], skills=["copywriter", "剪辑"],
        )
        self.assertIn("资源库里没有", out)
        self.assertIn("不存在的AI", out)
        self.assertIn("幽灵", out)
        self.assertIn("剪辑", out)
        # 存在的资源正常绑定:检查写进 state 的配置
        cfg = next(c for (_r, et, c) in self.client.states if et.endswith("config") or "persona" in c)
        self.assertEqual(cfg.get("agentSlugs"), ["planner"])
        self.assertEqual(cfg.get("persona", {}).get("skill_slugs"), ["copywriter"])
        # lead 回退内置人设(prompt 而非 agentSlug)
        self.assertIn("prompt", cfg.get("persona", {}))

    def test_rule_auto_generated_when_absent(self) -> None:
        out = self._assemble(tasks=[{"title": "写脚本"}, {"title": "拍摄"}])
        self.assertIn("自动生成的基础版", out)
        cfg = next(c for (_r, _et, c) in self.client.states if "taskRule" in c)
        self.assertIn("测试专班", cfg["taskRule"])
        self.assertIn("写脚本", cfg["taskRule"])

    def test_rule_kept_when_given(self) -> None:
        out = self._assemble(task_rule="只做A不做B")
        self.assertIn("按你的要求", out)
        cfg = next(c for (_r, _et, c) in self.client.states if "taskRule" in c)
        self.assertEqual(cfg["taskRule"], "只做A不做B")


class RoomAccessScopeTest(unittest.TestCase):
    """双层作用域:频道模式锁本频道、全局模式按成员放行(cosmac.ai_session 隔离墙)。"""

    def setUp(self) -> None:
        self.tb = Toolbox(FakeClient())

    def test_current_room_always_ok(self) -> None:
        # 目标=当前房,两种模式都放行
        ctx_ch = ToolContext("!cur:test", "@alice:test", is_dm=False)
        self.assertEqual(self.tb._check_room_access("!cur:test", ctx_ch), "")

    def test_channel_mode_blocks_other_room(self) -> None:
        # 频道模式:即便用户是那房间成员(!allowed),也拒绝跨房
        ctx = ToolContext("!cur:test", "@alice:test", is_dm=False)
        msg = self.tb._check_room_access("!allowed:test", ctx)
        self.assertNotEqual(msg, "")
        self.assertIn("频道", msg)

    def test_global_mode_allows_member_room(self) -> None:
        # 全局模式(私聊):用户是成员的房放行
        ctx = ToolContext("!cur:test", "@alice:test", is_dm=True)
        self.assertEqual(self.tb._check_room_access("!allowed:test", ctx), "")

    def test_list_my_rooms_channel_mode_refused(self) -> None:
        # 频道模式:分身不提供跨频道清单
        out = self.tb.execute(
            ToolCall(id="x", name="list_my_rooms", arguments={}),
            ToolContext("!cur:test", "@alice:test", is_dm=False),
        )
        self.assertIn("专属 AI", out)

    def test_list_my_rooms_global_mode_lists_member_rooms_only(self) -> None:
        # 全局模式:只列发起人在的房(!allowed),不暴露 TA 不在的(!secret)
        out = self.tb.execute(
            ToolCall(id="x", name="list_my_rooms", arguments={}),
            ToolContext("!cur:test", "@alice:test", is_dm=True),
        )
        self.assertIn("!allowed:test", out)
        self.assertIn("测试频道", out)
        self.assertNotIn("!secret:test", out)

    def test_global_mode_blocks_non_member_room(self) -> None:
        # 全局模式:用户不在的房仍拒绝(不越权)
        ctx = ToolContext("!cur:test", "@alice:test", is_dm=True)
        msg = self.tb._check_room_access("!secret:test", ctx)
        self.assertNotEqual(msg, "")
        self.assertIn("成员", msg)


class SendMessageTargetTest(unittest.TestCase):
    """send_message 目标房防呆(QA 实测:私聊里让 AI 发公告,消息落进私聊,群成员收不到)。"""

    def setUp(self) -> None:
        self.client = FakeClient()
        self.tb = Toolbox(self.client)

    def test_dm_without_target_refused(self) -> None:
        # 私聊里不指定目标群 → 拦下并引导给群名,一条消息都不真发
        out = self.tb.execute(
            ToolCall(id="x", name="send_message_to_room", arguments={"text": "公告"}),
            ToolContext("!cur:test", "@alice:test", is_dm=True),
        )
        self.assertIn("私聊", out)
        self.assertEqual(self.client.sent, [])

    def test_dm_room_name_resolved_and_sent(self) -> None:
        # 私聊里给群名 → 解析成 room_id 并真的发进那个群
        out = self.tb.execute(
            ToolCall(
                id="x", name="send_message_to_room",
                arguments={"text": "公告", "room_name": "测试频道"},
            ),
            ToolContext("!cur:test", "@alice:test", is_dm=True),
        )
        self.assertIn("已往房间", out)
        self.assertEqual(self.client.sent, [("!allowed:test", "公告")])

    def test_channel_mode_defaults_to_current_room(self) -> None:
        # 频道里 @AI 发消息不带目标 → 发到本频道(原有行为不变)
        out = self.tb.execute(
            ToolCall(id="x", name="send_message_to_room", arguments={"text": "hi"}),
            ToolContext("!cur:test", "@alice:test", is_dm=False),
        )
        self.assertIn("已往房间", out)
        self.assertEqual(self.client.sent, [("!cur:test", "hi")])


class InvitePromoteRetryTest(unittest.TestCase):
    """邀人 403(bot 在用户建的频道里无邀请权限)→ 自动提权(make_room_admin)→ 重试成功。"""

    def test_invite_403_promotes_and_retries(self) -> None:
        client = FakeClient()
        calls = {"n": 0}

        def inv_status(_room, _uid):
            calls["n"] += 1
            # 第一次 403(无权限),提权后的第二次成功
            return (calls["n"] > 1, 200 if calls["n"] > 1 else 403,
                    "" if calls["n"] > 1 else "no permission")

        client.invite_user_status = inv_status  # type: ignore
        client.homeserver_url = "http://fake"  # type: ignore
        client.bot_user_id = "@bot:test"  # type: ignore
        tb = Toolbox(client)
        import cosmac.registration as reg
        orig = reg.make_room_admin
        reg.make_room_admin = lambda *_a, **_k: (200, {"ok": True})  # type: ignore
        try:
            out = tb.execute(
                ToolCall(id="i", name="invite_to_room",
                         arguments={"user_id": "@x:test", "room_id": "!cur:test"}),
                ToolContext("!cur:test", "@alice:test"),
            )
        finally:
            reg.make_room_admin = orig  # type: ignore
        self.assertIn("已邀请", out)
        self.assertEqual(calls["n"], 2)  # 403 后确实重试了一次

    def test_invite_failure_reports_real_reason(self) -> None:
        # 提权不可用(无 ADMIN_TOKEN)时,失败文案带上服务器真实报错,不再瞎猜
        client = FakeClient()
        client.invite_user_status = lambda _r, _u: (False, 403, "not allowed")  # type: ignore
        client.homeserver_url = "http://fake"  # type: ignore
        client.bot_user_id = "@bot:test"  # type: ignore
        tb = Toolbox(client)
        import cosmac.registration as reg
        orig = reg.make_room_admin
        reg.make_room_admin = lambda *_a, **_k: (503, {"error": "未配置"})  # type: ignore
        try:
            out = tb.execute(
                ToolCall(id="i", name="invite_to_room",
                         arguments={"user_id": "@x:test", "room_id": "!cur:test"}),
                ToolContext("!cur:test", "@alice:test"),
            )
        finally:
            reg.make_room_admin = orig  # type: ignore
        self.assertIn("403", out)
        self.assertIn("not allowed", out)


class ProgressVisibilityTest(unittest.TestCase):
    """AI 执行过程可见:legacy 引擎回调触发 + 进度报告器 发送→编辑→定格。"""

    def test_agent_run_fires_progress_cb(self) -> None:
        script = [
            TurnResult(tool_calls=[ToolCall(id="1", name="create_room", arguments={"name": "群A"})]),
            TurnResult(text="建好了"),
        ]
        client = FakeClient()
        toolbox = Toolbox(client)
        llm = FakeLLM(script)
        agent = Agent(llm=llm, toolbox=toolbox, system_prompt="sys")
        seen = []
        agent.run("建群A", ToolContext("!cur:test", "@alice:test"),
                  progress_cb=lambda n, a: seen.append((n, a)))
        self.assertEqual(seen, [("create_room", {"name": "群A"})])

    def test_reporter_send_then_edit_then_finish(self) -> None:
        from cosmac.bots.appservice_bot import _ProgressReporter

        class _Cli:
            def __init__(self):
                self.sent, self.edits = [], []
            def send_text(self, room, text):
                self.sent.append(text)
                return "$ev1"
            def edit_text(self, room, ev, text):
                self.edits.append((ev, text))
                return True

        cli = _Cli()
        rep = _ProgressReporter(cli, "!r:test")
        rep("assemble_team", {"project": "暑期招生"})
        rep("create_tasks", {"goal": "招生"})
        rep.finish()
        # 第一步:发新消息;后续+定格:编辑同一条
        self.assertEqual(len(cli.sent), 1)
        self.assertIn("组建专班「暑期招生」", cli.sent[0])
        self.assertEqual(len(cli.edits), 2)
        self.assertTrue(all(ev == "$ev1" for ev, _ in cli.edits))
        self.assertIn("执行过程（2 步）", cli.edits[-1][1].replace("(", "（").replace(")", "）"))

    def test_reporter_silent_without_tools(self) -> None:
        from cosmac.bots.appservice_bot import _ProgressReporter

        class _Cli:
            def __init__(self): self.sent = []
            def send_text(self, room, text):
                self.sent.append(text)
                return "$e"
            def edit_text(self, room, ev, text): return True

        cli = _Cli()
        rep = _ProgressReporter(cli, "!r:test")
        rep.finish()   # 没有任何工具调用 → 不发过程消息
        self.assertEqual(cli.sent, [])


if __name__ == "__main__":
    unittest.main()
