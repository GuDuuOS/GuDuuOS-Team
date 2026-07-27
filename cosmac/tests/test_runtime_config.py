"""管理后台「AI 配置」运行时下发的单元测试。

不依赖运行中的 Synapse、不需要 key：用假 MatrixClient 模拟"控制室里读到的配置"，
验证 bot 会按下发的人设/模型/工具开关热应用，且**读不到时完全回退启动配置**。

运行：.venv/bin/python -m unittest cosmac.tests.test_runtime_config
"""

from __future__ import annotations

import os
import unittest
from typing import Any, Dict, Optional

from cosmac.ai.tools import ToolContext
from cosmac.ai.base import ToolCall
from cosmac.bots.appservice_bot import CosmacBot
from cosmac.config import CosmacConfig


class FakeClient:
    """假 MatrixClient：构造期 set_displayname 等被调到也无所谓，只关心配置读取。"""

    def __init__(self, alias_room: Optional[str], state: Optional[Dict[str, Any]]):
        self._alias_room = alias_room
        self._state = state

    # CosmacBot 构造/启动会用到的方法，给空实现
    def set_displayname(self, *_a, **_k): pass
    def send_text(self, *_a, **_k): return "$e"

    # 配置读取相关
    def resolve_alias(self, alias: str) -> Optional[str]:
        return self._alias_room

    def get_state_event(self, room_id, event_type, state_key=""):
        return self._state


def _bot(alias_room, state) -> CosmacBot:
    """构造一个用假 client 的 bot（provider=echo，无需 key）。"""
    bot = CosmacBot(CosmacConfig(llm_provider="echo"))
    bot.client = FakeClient(alias_room, state)  # 换成假 client
    return bot


class TestRuntimeConfig(unittest.TestCase):
    def test_no_control_room_keeps_startup_config(self) -> None:
        # 控制室解析不到 → 覆盖为空 → 签名不变、全工具启用（零回归）
        bot = _bot(alias_room=None, state=None)
        before = bot._applied_sig
        bot._apply_runtime_config()
        self.assertEqual(bot._applied_sig, before)
        # 本断言的意义是「控制室拿不到配置时，工具**一个都不该被停用**」——
        # 数字本身会随新增工具变化，加了工具就把它同步过来（别改成 >=，那样
        # "工具被意外停用"就漏过去了）。
        # 21 = 原 18 + 导入的 preview/import 两个 + 替代 SDK WebFetch 的 fetch_url。
        self.assertEqual(len(bot.toolbox.specs()), 21)

    def test_persona_override_rebuilds_agent(self) -> None:
        # 下发新人设 → 签名变、Agent 被换成新对象、system_prompt 生效
        bot = _bot("!ctrl:host", {"system_prompt": "你是测试版人设"})
        old_agent = bot.agent
        bot._apply_runtime_config()
        self.assertEqual(bot._applied_sig[2], "你是测试版人设")
        self.assertIsNot(bot.agent, old_agent)
        self.assertEqual(bot.agent.system_prompt, "你是测试版人设")

    def test_provider_switch_via_control_room(self) -> None:
        # 控制室下发 provider+model → bot 热切到对应后端（不再只能改人设）。
        # key 只走服务端环境变量：这里临时设 ARK_API_KEY 模拟服务器已配好密钥。
        from unittest import mock

        from cosmac.ai.openai_compat import OpenAICompatProvider
        bot = _bot(
            "!ctrl:host",
            {"provider": "deepseek", "model": "deepseek-v3.2"},
        )
        with mock.patch.dict(os.environ, {"ARK_API_KEY": "env-key"}):
            bot._apply_runtime_config()
        self.assertEqual(bot._applied_sig[0], "deepseek")
        self.assertIsInstance(bot.llm, OpenAICompatProvider)

    def test_api_key_from_control_room_is_ignored(self) -> None:
        # 安全回归：即便控制室事件里塞了 api_key，bot 也绝不采用它——
        # 密钥只走服务端环境变量；签名里的 key 段恒为 ""（build_provider 传 api_key=""）。
        bot = _bot(
            "!ctrl:host",
            {"provider": "deepseek", "api_key": "leaked-key", "model": "x"},
        )
        bot._apply_runtime_config()
        self.assertEqual(bot._applied_sig[3], "")  # 网页/事件传的 key 不进签名、不被使用
        # overrides 也不该把 api_key 读出来
        self.assertNotIn("api_key", bot._read_overrides())

    def test_tool_toggle_filters_specs(self) -> None:
        # 只启用 create_room → specs 只剩它(+ 永远在线的核心 create_tasks/search_knowledge/web_search)；停用的执行被拒
        bot = _bot("!ctrl:host", {"enabled_tools": ["create_room"]})
        bot._apply_runtime_config()
        names = [s.name for s in bot.toolbox.specs()]
        self.assertEqual(
            names,
            ["create_room", "invite_to_room", "list_my_rooms", "create_tasks", "search_knowledge", "web_search", "query_hr", "query_sales", "list_capabilities", "assemble_team", "list_room_tasks", "update_task", "ask_user_choice", "archive_project"],
        )  # always-on 不受开关约束
        out = bot.toolbox.execute(
            ToolCall(id="x", name="send_message_to_room", arguments={"text": "hi"}),
            ToolContext("!r:host", "@a:host"),
        )
        self.assertIn("停用", out)

    def test_cache_avoids_refetch(self) -> None:
        # 20s 缓存：第一次读到配置后，把 state 改掉也仍返回缓存（不重复打服务器）
        bot = _bot("!ctrl:host", {"system_prompt": "甲"})
        first = bot._read_overrides()
        self.assertEqual(first.get("system_prompt"), "甲")
        bot.client._state = {"system_prompt": "乙"}  # 改掉源
        second = bot._read_overrides()  # 仍在缓存窗口内
        self.assertEqual(second.get("system_prompt"), "甲")

    def test_read_failure_falls_back(self) -> None:
        # get_state_event 抛异常 → _read_overrides 不崩、回退（空/上次），_apply 不报错
        bot = _bot("!ctrl:host", {"system_prompt": "甲"})

        def boom(*_a, **_k):
            raise RuntimeError("network down")

        bot.client.get_state_event = boom  # type: ignore
        # 不应抛异常
        bot._apply_runtime_config()

    def test_transient_failure_keeps_tool_restriction(self) -> None:
        # 回归：读配置抖动失败绝不能"失效开放"把工具限制清空。
        bot = _bot("!ctrl:host", {"enabled_tools": ["create_room"]})
        bot._apply_runtime_config()
        # create_tasks 是 always-on 核心工具，限制集里也有它；其余受限
        self.assertEqual(
            [s.name for s in bot.toolbox.specs()],
            ["create_room", "invite_to_room", "list_my_rooms", "create_tasks", "search_knowledge", "web_search", "query_hr", "query_sales", "list_capabilities", "assemble_team", "list_room_tasks", "update_task", "ask_user_choice", "archive_project"],
        )

        def boom(*_a, **_k):
            raise RuntimeError("403")  # 模拟无权限/网络抖动

        bot.client.get_state_event = boom  # type: ignore
        bot._cfg_cache_ts = float("-inf")  # 让 20s 缓存失效，强制重读
        bot._apply_runtime_config()
        # 关键：仍只剩 create_room(+always-on create_tasks)，没有恢复成全部工具
        self.assertEqual(
            [s.name for s in bot.toolbox.specs()],
            ["create_room", "invite_to_room", "list_my_rooms", "create_tasks", "search_knowledge", "web_search", "query_hr", "query_sales", "list_capabilities", "assemble_team", "list_room_tasks", "update_task", "ask_user_choice", "archive_project"],
        )

    def test_require_tokens_raises_when_missing(self) -> None:
        # appservice 密钥缺失必须明确报错（不再硬编码、不静默用泄露的旧 key）
        with self.assertRaises(RuntimeError):
            CosmacConfig(as_token="", hs_token="").require_tokens()
        # 两个都有值则正常通过
        CosmacConfig(as_token="a", hs_token="b").require_tokens()


if __name__ == "__main__":
    unittest.main()
