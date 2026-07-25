"""一键建专班 assemble_team（模块3.5 档3）+ 本专班任务RULE 注入 单元测试。

内存 SQLite、零 key；假 client 记录 建房/写state/发消息。
运行：.venv/bin/python -m unittest cosmac.tests.test_assemble_team
"""

from __future__ import annotations

import unittest

from cosmac.ai.tools import Toolbox, ToolCall, ToolContext
from cosmac.config import CHANNEL_CONFIG_EVENT_TYPE
from cosmac.db import init_engine, session_scope
from cosmac.db.task_repo import list_tasks


class FakeClient:
    def __init__(self) -> None:
        self.created: list = []
        self.states: list = []
        self.sent: list = []

    def create_room(self, name, invitees=None, admins=None):
        self.created.append((name, invitees, admins))
        return "!team:h"

    def invite_user(self, room_id, user_id):
        self.invited = getattr(self, "invited", [])
        self.invited.append(user_id)
        return True

    def set_state_event(self, room_id, etype, content, state_key=""):
        self.states.append((room_id, etype, content))
        return True

    def send_text(self, room_id, text, txn_id=None):
        self.sent.append((room_id, text))
        return "$e"

    def send_card(self, room_id, body, card):
        self.cards = getattr(self, "cards", [])
        self.cards.append((room_id, card))
        return "$e"


class TestAssembleTeam(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)
        self.client = FakeClient()
        self.tb = Toolbox(self.client)

    def _run(self, args):
        return self.tb.execute(
            ToolCall(id="x", name="assemble_team", arguments=args),
            ToolContext("!cur:h", "@owner:h"),
        )

    def test_full_provisioning(self) -> None:
        out = self._run({
            "project": "双11大促", "members": ["@a:h", "@b:h"],
            "lead_agent": "orchestrator", "worker_agents": ["copywriter"],
            "task_rule": "对外报价需主管确认", "skills": ["weekly"],
            "tasks": [{"title": "写文案", "executor_kind": "human", "executor_ref": "@a:h"}],
        })
        # 建房：名字对、发起人随建房邀请；其余成员逐个 invite_user（健壮性：坏 id 不搞崩建房）
        name, invitees, admins = self.client.created[0]
        self.assertEqual(name, "双11大促")
        self.assertEqual(invitees, ["@owner:h"])
        # 发起人 = 专班主人：建房时就提成 100 级管理员（否则改不了频道名/配置）
        self.assertEqual(admins, ["@owner:h"])
        self.assertEqual(set(self.client.invited), {"@a:h", "@b:h"})
        # 频道配置：任务RULE / 协作Agent / 项目主AI / 技能
        room, etype, content = self.client.states[0]
        self.assertEqual(etype, CHANNEL_CONFIG_EVENT_TYPE)
        self.assertEqual(content["taskRule"], "对外报价需主管确认")
        self.assertEqual(content["agentSlugs"], ["copywriter"])
        self.assertEqual(content["persona"]["agentSlug"], "orchestrator")
        self.assertEqual(content["persona"]["skill_slugs"], ["weekly"])
        # 任务派进新专班（作用域=新房间）
        with session_scope() as s:
            rows = list_tasks(s, room_ids=["!team:h"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].executor_ref, "@a:h")
        # 开班消息 + 回灌含 room_id
        self.assertTrue(any("专班" in t for _r, t in self.client.sent))
        self.assertIn("!team:h", out)
        # team_created 信号卡发到发起人所在房间（DM），带新专班 room_id，供客户端挂工作区
        tc = [c for r, c in self.client.cards if c.get("kind") == "team_created"]
        self.assertEqual(len(tc), 1)
        self.assertEqual(tc[0]["team_room"], "!team:h")

    def test_no_tasks_refuses_before_building(self) -> None:
        """没带任务分解时:不建房、不发消息,返回让模型先拆任务的提示(负责人实报:建专班后看板空)。"""
        out = self._run({"project": "空壳班", "worker_agents": ["copywriter"]})
        self.assertEqual(self.client.created, [])   # 没建房
        self.assertEqual(self.client.states, [])    # 没写频道配置
        self.assertIn("任务", out)                  # 提示要先拆任务
        with session_scope() as s:                  # 库里也没任何任务
            self.assertEqual(list_tasks(s, room_ids=["!team:h"]), [])

    def test_empty_task_titles_also_refused(self) -> None:
        """tasks 给了但全是空标题(等于没拆)——同样拦下,不建空专班。"""
        out = self._run({"project": "空标题班", "tasks": [{"title": "  "}, {"title": ""}]})
        self.assertEqual(self.client.created, [])
        self.assertIn("任务", out)

    def test_restricted_agent_not_bindable_by_unentitled_user(self) -> None:
        # M2 越权：发起人够不到的受限智能体，点名当 lead/worker 会被按 access 过滤后的可见集
        # 当成"缺口"剔除，绝不注入其付费人设。known_agents(for_user) 模拟按发起人过滤。
        self.tb.known_agents = (
            lambda for_user=None: {"open"} if for_user == "@owner:h" else {"open", "vip"}
        )
        out = self._run({
            "project": "越权班", "lead_agent": "vip", "worker_agents": ["vip", "open"],
            "tasks": [{"title": "占位任务", "executor_kind": "agent", "executor_ref": "open"}],
        })
        _room, _etype, content = self.client.states[0]
        # vip 既没当上 lead（persona.agentSlug 不是 vip），也没进 worker 列表
        self.assertNotEqual(content.get("persona", {}).get("agentSlug"), "vip")
        self.assertNotIn("vip", content.get("agentSlugs", []))
        # open 是发起人够得到的 → 正常绑定
        self.assertIn("open", content.get("agentSlugs", []))
        self.assertIn("越权班", out)  # 专班仍建成，只是没绑受限的 vip

    def test_create_room_binds_knowledge_and_rule(self) -> None:
        # 负责人需求:普通建频道就能把知识库/规则调进去,不必为绑资源建专班。
        out = self.tb.execute(
            ToolCall(id="x", name="create_room", arguments={
                "name": "资料频道", "knowledge": ["owner", "platform"], "rule": "对外资料需审核",
            }),
            ToolContext("!cur:h", "@owner:h"),
        )
        room, etype, content = self.client.states[0]
        self.assertEqual(room, "!team:h")
        self.assertEqual(etype, CHANNEL_CONFIG_EVENT_TYPE)
        self.assertIn("user:@owner:h", content["kbScopes"])
        self.assertIn("platform", content["kbScopes"])
        self.assertEqual(content["taskRule"], "对外资料需审核")
        self.assertIn("已绑定", out)
        # 不带 knowledge/rule 时也写 channel_config——默认植入「频道资源边界」规则
        # (负责人硬性要求:每次建频道都要有默认 RULE,频道 AI 只用本频道资源)。
        self.client.states.clear()
        self.tb.execute(
            ToolCall(id="y", name="create_room", arguments={"name": "普通频道"}),
            ToolContext("!cur:h", "@owner:h"),
        )
        self.assertEqual(len(self.client.states), 1)
        _, _, content2 = self.client.states[0]
        self.assertEqual(content2["rules"][0]["label"], "频道资源边界")
        self.assertNotIn("taskRule", content2)

    def test_workers_pulled_into_room_as_puppets(self) -> None:
        # 方案B:建专班时把每个协作 Agent 的傀儡账号拉进频道(注入回调);
        # 失败的不进"已进频道"名单,专班照常(退回方案A 人设应答)。
        pulled: list = []

        def _pull(room: str, slug: str) -> str:
            if slug == "broken":
                return ""  # 模拟账号建不了
            pulled.append((room, slug))
            return f"@guduu-ai-{slug}:h"

        self.tb.ensure_worker_in_room = _pull
        self.tb.known_agents = lambda for_user=None: {"copywriter", "broken"}
        self._run({"project": "傀儡班", "tasks": [{"title": "占位任务"}], "worker_agents": ["copywriter", "broken"]})
        self.assertEqual(pulled, [("!team:h", "copywriter")])
        # 开班消息:进了频道的标注"已进频道",失败的不标(退回人设应答)
        opening = "\n".join(t for _r, t in self.client.sent)
        self.assertIn("copywriter(已进频道)", opening)
        self.assertNotIn("broken(已进频道)", opening)

    def test_agent_tasks_trigger_auto_execute(self) -> None:
        # 派给 AI 同事的任务要触发自动执行回调(负责人需求:派了就干,不等人 @);
        # 人工任务不触发。回调收到的是这批任务里 agent 类的 task id。
        calls: list = []
        self.tb.auto_execute_agent_tasks = (
            lambda room, sender, ids, rule: calls.append((room, sender, list(ids), rule))
        )
        out = self._run({
            "project": "抓阄执行班",
            "task_rule": "按时交付",
            "tasks": [
                {"title": "制定规则", "executor_kind": "agent", "executor_ref": "copywriter"},
                {"title": "现场主持", "executor_kind": "human", "executor_ref": "@a:h"},
            ],
        })
        self.assertEqual(len(calls), 1)
        room, sender, ids, rule = calls[0]
        self.assertEqual(room, "!team:h")
        self.assertEqual(len(ids), 1)  # 只有 agent 那条
        self.assertEqual(rule, "按时交付")
        self.assertIn("已自动开始执行", out)  # 回灌里告知模型别让用户手动催

    def test_slug_variants_resolve_to_library_slug(self) -> None:
        # 负责人线上实测:库里是 marketing-campaign,模型写 marketing_campaign(下划线),
        # 精确匹配被误报"库里没有"→技能没绑上。宽容解析:_/-、大小写、中文名都要认。
        self.tb.known_agents = lambda for_user=None: {"planner": "选题策划"}
        self.tb.known_skills = lambda for_user=None: {"marketing-campaign": "营销活动策划"}
        out = self._run({
            "project": "抓阄班", "tasks": [{"title": "占位任务"}],
            "lead_agent": "Planner",                    # 大小写变体 → 认
            "skills": ["marketing_campaign", "营销活动策划"],  # 下划线变体+中文名 → 都认并去重
        })
        _room, _etype, content = self.client.states[0]
        self.assertEqual(content["persona"]["agentSlug"], "planner")  # 解析成库里真 slug
        self.assertEqual(content["persona"]["skill_slugs"], ["marketing-campaign"])
        self.assertNotIn("库里没有", out)  # 不再误报缺口
        # 真没有的仍要报缺口、不写进配置
        out2 = self._run({"project": "抓阄班2", "tasks": [{"title": "占位任务"}], "skills": ["ghost-skill"]})
        self.assertIn("ghost-skill", out2)
        _room2, _etype2, content2 = self.client.states[1]
        self.assertNotIn("skill_slugs", content2.get("persona", {}))

    def test_knowledge_bound_into_channel(self) -> None:
        # 知识库"调进频道":owner→发起人个人库对全班开放;platform→平台共享库。
        # 写进 channel_config.kbScopes,频道分身检索时纳入(见 _group_context/_kb_retrieve)。
        self._run({"project": "招生班", "tasks": [{"title": "占位任务"}], "knowledge": ["owner", "platform"]})
        _room, _etype, content = self.client.states[0]
        self.assertIn("user:@owner:h", content["kbScopes"])
        self.assertIn("platform", content["kbScopes"])

    def test_no_knowledge_no_kbscopes(self) -> None:
        # 不传 knowledge → 不写 kbScopes(不引入空字段)
        self._run({"project": "空班", "tasks": [{"title": "占位任务"}]})
        _room, _etype, content = self.client.states[0]
        self.assertNotIn("kbScopes", content)

    def test_failed_invite_does_not_break_team(self) -> None:
        # 健壮性：某成员邀请失败（如账号不存在）→ 专班照样建成、配置照写、如实告知未邀到
        self.client.invite_user = lambda room, uid: uid != "@ghost:h"  # @ghost 邀不到
        out = self._run({"project": "测试班", "tasks": [{"title": "占位任务"}], "members": ["@a:h", "@ghost:h"]})
        # 专班仍建成（频道配置写入成功）
        self.assertTrue(self.client.states)
        self.assertEqual(self.client.states[0][1], CHANNEL_CONFIG_EVENT_TYPE)
        # 回灌如实反映：邀到 1 人、1 人没邀到
        self.assertIn("邀到 1 人", out)
        self.assertIn("@ghost:h", out)
        self.assertIn("没邀到", out)

    def test_builtin_persona_when_no_lead(self) -> None:
        self._run({"project": "小项目", "tasks": [{"title": "占位任务"}]})
        _room, _etype, content = self.client.states[0]
        # 没给 lead_agent → 用内置编排人设
        self.assertIn("项目主AI", content["persona"]["prompt"])
        self.assertNotIn("agentSlug", content["persona"])

    def test_requires_project_name(self) -> None:
        out = self._run({"project": "  "})
        self.assertIn("起个名字", out)
        self.assertEqual(self.client.created, [])  # 没建房

    def test_dedup_channel_name_when_collision(self) -> None:
        # 已有同名频道「税务自查」→ 新专班改叫「税务自查专班」,避免左栏两个一样的频道。
        self.client.joined_rooms = lambda: ["!exist:h"]                         # type: ignore
        self.client.get_state_event = lambda rid, et, sk="": (                  # type: ignore
            {"name": "税务自查"} if et == "m.room.name" else None)              # 无 create/ai/dm 标记 → channel
        out = self._run({"project": "税务自查", "tasks": [{"title": "占位任务"}], "members": ["@a:h"]})
        self.assertEqual(self.client.created[0][0], "税务自查专班")             # 建房用去重名
        self.assertIn("税务自查专班", out)                                      # 回灌用去重名

    def test_no_dedup_when_no_collision(self) -> None:
        # 没有同名频道 → 名字原样,不加后缀
        self.client.joined_rooms = lambda: []                                   # type: ignore
        self._run({"project": "全新项目", "tasks": [{"title": "占位任务"}]})
        self.assertEqual(self.client.created[0][0], "全新项目")


class TestTaskReviewTools(unittest.TestCase):
    """档4 派单+审核回填：list_room_tasks / update_task（含跨频道越权防护）。"""

    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)
        self.tb = Toolbox(FakeClient())
        # 在 !team:h 频道下建两条任务
        from cosmac.db.task_repo import create_tasks
        with session_scope() as s:
            rows = create_tasks(s, goal="大促", items=[
                {"title": "写文案", "executor_kind": "human", "executor_ref": "@a:h"},
                {"title": "出图", "executor_kind": "agent", "executor_ref": "designer"},
            ], room_id="!team:h", sender="@owner:h")
            self.tid = rows[0].id

    def _exec(self, name, args, room="!team:h"):
        return self.tb.execute(
            ToolCall(id="x", name=name, arguments=args),
            ToolContext(room, "@owner:h"),
        )

    def test_list_room_tasks(self) -> None:
        out = self._exec("list_room_tasks", {})
        self.assertIn("写文案", out)
        self.assertIn("出图", out)
        self.assertIn(f"#{self.tid}", out)

    def test_list_room_tasks_by_room_name(self) -> None:
        """负责人线上实测:私聊里问「查XX专班进度」要能按名字精确解析到该频道。

        撞前缀场景:「讲座活动」与「讲座活动专班」并存,传全名必须命中专班而非母频道;
        查非当前频道要求发起人是该频道成员(越权防护)。
        """
        c = self.tb.client
        NAMES = {"!mother:h": "讲座活动", "!team:h": "讲座活动专班"}
        c.joined_rooms = lambda: list(NAMES)  # type: ignore
        c.get_state_event = (  # type: ignore
            lambda rid, etype, *a: {"name": NAMES[rid]} if etype == "m.room.name" and rid in NAMES else None
        )
        members = {"!team:h": [{"user_id": "@owner:h"}], "!mother:h": [{"user_id": "@other:h"}]}
        c.get_members = lambda rid: members.get(rid, [])  # type: ignore
        # 在私聊房(非任务所在频道)里点名查「讲座活动专班」→ 精确命中,列出它的任务
        out = self._exec("list_room_tasks", {"room": "讲座活动专班"}, room="!dm:h")
        self.assertIn("写文案", out)
        self.assertIn("讲座活动专班", out)
        # 传母频道名 → 解析到母频道,但发起人不在里面 → 拒绝(不泄露任务)
        out2 = self._exec("list_room_tasks", {"room": "讲座活动"}, room="!dm:h")
        self.assertIn("你不在", out2)

    def test_update_task_approve(self) -> None:
        # 审核通过 → done + 回填结果
        out = self._exec("update_task", {"task_id": self.tid, "status": "done", "result": "已交付链接X"})
        self.assertIn("done", out)
        from cosmac.db.task_repo import get_task
        with session_scope() as s:
            t = get_task(s, self.tid)
        self.assertEqual(t.status, "done")
        self.assertEqual(t.result, "已交付链接X")
        self.assertEqual(t.progress, 100)  # done 自动补满

    def test_update_task_reject(self) -> None:
        # 打回 → doing + 批注
        self._exec("update_task", {"task_id": self.tid, "status": "doing", "result": "打回：标题不够吸睛"})
        from cosmac.db.task_repo import get_task
        with session_scope() as s:
            t = get_task(s, self.tid)
        self.assertEqual(t.status, "doing")
        self.assertIn("打回", t.result)

    def test_update_task_invalid_status_rejected(self) -> None:
        # M6：非法状态直接拒绝，绝不"假成功"（旧行为：task_repo 静默丢弃、工具回"已更新→blocked"）
        out = self._exec("update_task", {"task_id": self.tid, "status": "blocked", "result": "等资料"})
        self.assertIn("待办", out)  # 提示只能是 待办/进行中/已完成
        from cosmac.db.task_repo import get_task
        with session_scope() as s:
            t = get_task(s, self.tid)
        self.assertEqual(t.status, "todo")            # 状态没被改动
        self.assertNotEqual(t.result, "等资料")        # result 也没写（整条被拦）

    def test_update_task_status_synonym_normalized(self) -> None:
        # M6：模型给同义词（in_progress/完成）也能归一化到合法状态
        self._exec("update_task", {"task_id": self.tid, "status": "in_progress"})
        from cosmac.db.task_repo import get_task
        with session_scope() as s:
            self.assertEqual(get_task(s, self.tid).status, "doing")

    def test_update_task_cross_channel_blocked(self) -> None:
        # 从别的频道改本任务 → 拒绝（越权防护：只能改本频道的任务）
        out = self._exec("update_task", {"task_id": self.tid, "status": "done"}, room="!other:h")
        self.assertIn("没找到", out)
        from cosmac.db.task_repo import get_task
        with session_scope() as s:
            t = get_task(s, self.tid)
        self.assertEqual(t.status, "todo")  # 未被改动


def _bot_with_channel(channel_cfg, agents_state=None):
    """造一个 bot，其假 client 返回给定的 channel_config 与（可选）全局 agents。"""
    from cosmac.bots.appservice_bot import CosmacBot
    from cosmac.config import AGENTS_EVENT_TYPE, CosmacConfig

    bot = CosmacBot(CosmacConfig(llm_provider="echo"))

    class C:
        def resolve_alias(self, a):
            return "!ctrl:h"

        def get_state_event(self, room, etype, key=""):
            if etype == CHANNEL_CONFIG_EVENT_TYPE:
                return channel_cfg
            if etype == AGENTS_EVENT_TYPE:
                return agents_state
            return None

        def set_displayname(self, *a, **k):
            pass

        def send_text(self, *a, **k):
            return "$e"

    bot.client = C()
    bot._gate_allows = lambda u, c: True  # type: ignore
    return bot


class TestWorkerRouting(unittest.TestCase):
    """档3b：专班里 @协作 Agent 名 → 换该 worker 人设回应；任务RULE 不变。"""

    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)
        self.agents = {"agents": [
            {"slug": "designer", "name": "分镜师", "system_prompt": "你画分镜",
             "skill_slugs": ["storyboard"], "model": "", "enabled": True},
        ]}
        self.cfg = {"persona": {"prompt": "我是项目主AI"}, "taskRule": "对外报价需确认",
                    "agentSlugs": ["designer"]}

    def test_named_worker_overrides_persona(self) -> None:
        bot = _bot_with_channel(self.cfg, self.agents)
        gctx = bot._group_context("!team:h")
        routed = bot._apply_worker_routing("请 designer 出一版分镜", gctx)
        self.assertIn("分镜师", routed["persona"])
        self.assertIn("你画分镜", routed["persona"])
        self.assertEqual(routed["skill_slugs"], ["storyboard"])
        # 任务RULE 不变（worker 仍受专班约束）
        self.assertEqual(routed["task_rule"], "对外报价需确认")

    def test_no_mention_keeps_lead(self) -> None:
        bot = _bot_with_channel(self.cfg, self.agents)
        gctx = bot._group_context("!team:h")
        routed = bot._apply_worker_routing("项目进度怎么样了", gctx)
        self.assertIn("项目主AI", routed["persona"])  # 没点名 → 维持 lead

    def test_no_workers_is_noop(self) -> None:
        bot = _bot_with_channel({"persona": {"prompt": "普通群人设"}}, self.agents)
        gctx = bot._group_context("!r:h")
        routed = bot._apply_worker_routing("designer 你好", gctx)
        self.assertEqual(routed["persona"], gctx["persona"])  # 非专班→不路由


class TestTaskRuleInjection(unittest.TestCase):
    """本专班任务RULE 注入：项目主AI 被频道 taskRule 约束。"""

    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)

    def _bot(self, channel_cfg):
        return _bot_with_channel(channel_cfg)

    def test_group_context_reads_task_rule(self) -> None:
        bot = self._bot({"persona": {"prompt": "人设X"}, "taskRule": "只做分配与审核"})
        gctx = bot._group_context("!r:h")
        self.assertEqual(gctx["task_rule"], "只做分配与审核")

    def test_addendum_injects_task_rule_high_priority(self) -> None:
        bot = self._bot({"persona": {"prompt": "人设X"}, "taskRule": "对外报价需主管确认"})
        add = bot._skill_addendum("!r:h", "@u:h", query="")
        self.assertIn("对外报价需主管确认", add)
        self.assertIn("本专班任务约束", add)
        # 任务RULE 应排在人设之前（优先级更高）
        self.assertLess(add.index("本专班任务约束"), add.index("人设X"))


if __name__ == "__main__":
    unittest.main()
