"""入驻模板 P2 引导接入·绑定真生效 单元测试（内存 SQLite、零 key、假 client）。

验证：引导按模板写进频道 channel_config 的「模型 / 技能 / 默认工作流」会被 bot 的
_group_context 读到、并在 _skill_addendum 里对 AI 生效（人设/RULE 路径已有别的测试覆盖，
这里补模型/技能/工作流这几条之前标 P2b 的字段）。

运行：.venv/bin/python -m unittest cosmac.tests.test_onboarding_binding
"""

from __future__ import annotations

import unittest

from cosmac.config import (
    AGENTS_EVENT_TYPE,
    CHANNEL_CONFIG_EVENT_TYPE,
    WORKFLOWS_EVENT_TYPE,
)


def _bot_with(channel_cfg, workflows=None):
    """造一个 bot，其假 client 按事件类型返回给定的频道配置 / 全局工作流定义。"""
    from cosmac.bots.appservice_bot import CosmacBot
    from cosmac.config import CosmacConfig

    bot = CosmacBot(CosmacConfig(llm_provider="echo"))

    class C:
        def resolve_alias(self, a):
            return "!ctrl:h"

        def get_state_event(self, room, etype, key=""):
            if etype == CHANNEL_CONFIG_EVENT_TYPE:
                return channel_cfg
            if etype == WORKFLOWS_EVENT_TYPE:
                return {"workflows": workflows or []}
            return None

        def set_displayname(self, *a, **k):
            pass

        def send_text(self, *a, **k):
            return "$e"

    bot.client = C()
    return bot


class TestOnboardingChannelBinding(unittest.TestCase):
    def test_group_context_reads_model_skill_workflow(self) -> None:
        # 引导按模板写入的 persona.model/skill_slugs + 顶层 workflowSlugs 都要被读到
        cfg = {
            "persona": {"prompt": "你是美妆运营助手", "model": "deepseek-v3.2",
                        "skill_slugs": ["weekly", "xhs"]},
            "workflowSlugs": ["cover-gen", "ghost"],
        }
        bot = _bot_with(cfg)
        g = bot._group_context("!ws:h")
        self.assertIn("美妆运营助手", g["persona"])
        self.assertEqual(g["model"], "deepseek-v3.2")          # 模型覆盖真生效
        self.assertEqual(g["skill_slugs"], ["weekly", "xhs"])  # 技能真生效
        self.assertEqual(g["workflow_slugs"], ["cover-gen", "ghost"])

    def test_preset_workflows_resolves_names_and_skips_missing(self) -> None:
        wfs = [{"slug": "cover-gen", "name": "封面生成", "enabled": True}]
        bot = _bot_with({}, workflows=wfs)
        # cover-gen 解析成名字；ghost 不存在 → 跳过
        text = bot._preset_workflows_text(["cover-gen", "ghost"])
        self.assertIn("封面生成", text)
        self.assertIn("cover-gen", text)
        self.assertNotIn("ghost", text)
        self.assertIn("run_workflow", text)
        # 全不存在 → 空串（不硬塞噪声进 prompt）
        self.assertEqual(bot._preset_workflows_text(["ghost"]), "")
        self.assertEqual(bot._preset_workflows_text([]), "")

    def test_addendum_surfaces_preset_workflows(self) -> None:
        cfg = {"persona": {"prompt": "助手"}, "workflowSlugs": ["cover-gen"]}
        wfs = [{"slug": "cover-gen", "name": "封面生成", "enabled": True}]
        bot = _bot_with(cfg, workflows=wfs)
        add = bot._skill_addendum("!ws:h", "@u:h", query="")
        # 文案随「智能体也能绑工作流」一并改口径:不再只讲入驻模板,而是"本频道可直接调用"
        self.assertIn("本频道可直接调用的工作流", add)
        self.assertIn("封面生成", add)



class AgentWorkflowBindingTest(unittest.TestCase):
    """智能体绑定工作流（「让 Agent 真能干活」第一步）。

    覆盖两件事：① 绑定的工作流进得了上下文、说得进 prompt；
    ② 「绑定即授权」的豁免口径**收得住**——只对精确命中的 slug 生效，不是万能钥匙。
    """

    def _bot(self, agent_wfs, tpl_wfs=None):
        """造一个绑了智能体的频道；该智能体带 agent_wfs，模板预置 tpl_wfs。"""
        from cosmac.bots.appservice_bot import CosmacBot
        from cosmac.config import CosmacConfig

        bot = CosmacBot(CosmacConfig(llm_provider="echo"))
        agents = [{
            "slug": "ops", "name": "运维助手", "description": "",
            "system_prompt": "你是运维助手", "model": "", "skill_slugs": [],
            "workflow_slugs": agent_wfs, "enabled": True,
        }]
        wfs = [
            {"slug": "cover-gen", "name": "封面生成", "enabled": True},
            {"slug": "deploy", "name": "部署流水线", "enabled": True},
            {"slug": "secret-op", "name": "机密操作", "enabled": True},
        ]
        cfg = {"persona": {"agentSlug": "ops"}, "workflowSlugs": tpl_wfs or []}

        class C:
            def resolve_alias(self, a):
                return "!ctrl:h"

            def get_state_event(self, room, etype, key=""):
                if etype == CHANNEL_CONFIG_EVENT_TYPE:
                    return cfg
                if etype == WORKFLOWS_EVENT_TYPE:
                    return {"workflows": wfs}
                if etype == AGENTS_EVENT_TYPE:
                    return {"agents": agents}
                return None

            def set_displayname(self, *a, **k):
                pass

            def send_text(self, *a, **k):
                return "$e"

        bot.client = C()
        return bot

    def test_agent_workflows_enter_context_and_merge_with_template(self) -> None:
        """智能体自带的 + 模板预置的都要在，且不重复。"""
        bot = self._bot(["deploy"], tpl_wfs=["cover-gen"])
        gctx = bot._group_context_uncached("!room:h")
        self.assertEqual(gctx["workflow_slugs"], ["cover-gen", "deploy"])  # 模板在前、智能体追加
        # 智能体绑的和模板预置的撞了 → 只留一份
        bot2 = self._bot(["cover-gen"], tpl_wfs=["cover-gen"])
        self.assertEqual(bot2._group_context_uncached("!room:h")["workflow_slugs"], ["cover-gen"])

    def test_bound_workflow_reaches_prompt(self) -> None:
        bot = self._bot(["deploy"])
        add = bot._skill_addendum("!room:h", "@u:h", query="")
        self.assertIn("部署流水线", add)
        self.assertIn("run_workflow", add)

    def test_binding_exempts_gate_only_for_that_slug(self) -> None:
        """核心安全断言：豁免只认精确命中的 slug，不是"绑了一个就全放行"。"""
        from cosmac.ai.tools import ToolCall, ToolContext, Toolbox

        class _C:  # 假 client：本用例只验门控分支，走不到真正的连接器调用
            def resolve_alias(self, a):
                return "!ctrl:h"

            def get_state_event(self, *a, **k):
                return None

        box = Toolbox(_C())
        box.gate_check = lambda sender, tool: "需要升级会员"   # 一律拒绝
        ctx = ToolContext(room_id="!r:h", sender="@u:h", authorized_workflows=("deploy",))

        def run(**args):
            return box.execute(ToolCall(id="t1", name="run_workflow", arguments=args), ctx)

        # 绑定的 slug → 绕过门控（落到工具体内，报的是"没有连接器"而非"需要升级"）
        self.assertNotIn("需要升级", run(slug="deploy"))
        # 没绑的 slug → 照样被门控拦下
        self.assertIn("需要升级", run(slug="secret-op"))
        # 不带 slug（列清单）→ 属查询语义，不豁免
        self.assertIn("需要升级", run())
        # 豁免绝不外溢到别的工具
        self.assertIn("需要升级", box.execute(ToolCall(id="t2", name="create_room", arguments={}), ctx))
        # 没有任何绑定时，run_workflow 一律受门控
        bare = ToolContext(room_id="!r:h", sender="@u:h")
        self.assertIn("需要升级", box.execute(ToolCall(id="t3", name="run_workflow", arguments={"slug": "deploy"}), bare))

    def test_context_default_is_immutable_and_empty(self) -> None:
        """默认值必须是不可变空元组——dataclass 用可变默认值会让所有实例共享同一个 list。"""
        from cosmac.ai.tools import ToolContext

        a = ToolContext(room_id="!a:h", sender="@u:h")
        b = ToolContext(room_id="!b:h", sender="@u:h")
        self.assertEqual(a.authorized_workflows, ())
        self.assertIs(a.authorized_workflows, b.authorized_workflows)
        self.assertIsInstance(a.authorized_workflows, tuple)


if __name__ == "__main__":
    unittest.main()
