# -*- coding: utf-8 -*-
"""发行版默认配置落地单测(负责人:人设/配额/门控作为系统默认基础,出厂即有)。

seed_default_control_config 把代码内置默认写进控制室 state event,让后台可见可改:
- system_prompt 空 → 补默认人设，并清理历史 provider/model/key 当前态；
- gating/quotas 缺 → 写目录默认;
- **幂等**:已配的值绝不覆盖;bot 无写权限时静默跳过。

运行:.venv/bin/python -m unittest cosmac.tests.test_seed_default_config
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, Optional

from cosmac.bots.appservice_bot import CosmacBot
from cosmac.config import (
    AI_CONFIG_EVENT_TYPE, GATING_EVENT_TYPE, QUOTAS_EVENT_TYPE, CosmacConfig,
)
from cosmac.db import init_engine


class _C:
    """打桩控制室:记录写入的 state,可预置已有内容验证幂等。"""

    def __init__(self, existing: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
        self.state: Dict[str, Dict[str, Any]] = existing or {}
        self.writes: list = []

    def resolve_alias(self, alias):
        return "!ctrl:h"

    def get_state_event(self, room, etype, state_key=""):
        return self.state.get(etype)

    def set_state_event(self, room, etype, content, state_key=""):
        self.state[etype] = content
        self.writes.append((etype, content))
        return True

    def whoami(self, t):
        return "@u:h"

    def set_displayname(self, *a, **k):
        pass


def _bot(client: _C) -> CosmacBot:
    bot = CosmacBot(CosmacConfig(
        llm_provider="deepseek", server_name="h",
        control_room_alias="#cosmac-ctrl:h"))
    bot.client = client  # type: ignore
    return bot


class TestSeedDefaultConfig(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)

    def test_seeds_all_when_empty(self) -> None:
        c = _C()  # 全空控制室(新装实例)
        bot = _bot(c)
        n = bot.seed_default_control_config()
        self.assertEqual(n, 3)  # 人设 + 门控 + 配额
        # 人设落地且非空，模型选择不再写入 Matrix 控制室
        ai = c.state[AI_CONFIG_EVENT_TYPE]
        self.assertTrue(ai["system_prompt"].strip())
        self.assertNotIn("provider", ai)
        # 门控/配额落地成后台读得懂的格式
        self.assertIn("gates", c.state[GATING_EVENT_TYPE])
        self.assertIn("limits", c.state[QUOTAS_EVENT_TYPE])
        self.assertIn("ai_msg_daily", c.state[QUOTAS_EVENT_TYPE]["limits"])

    def test_idempotent_second_run_writes_nothing(self) -> None:
        c = _C()
        bot = _bot(c)
        bot.seed_default_control_config()
        c.writes.clear()
        self.assertEqual(bot.seed_default_control_config(), 0)  # 二次零写入
        self.assertEqual(c.writes, [])

    def test_never_overwrites_configured_values(self) -> None:
        # 管理员已配的人设/门控/配额,seed 绝不覆盖
        c = _C({
            AI_CONFIG_EVENT_TYPE: {"system_prompt": "我的自定义人设"},
            GATING_EVENT_TYPE: {"gates": {"ai_chat": "paid"}},
            QUOTAS_EVENT_TYPE: {"limits": {"teams": {"free": 9}}},
        })
        bot = _bot(c)
        self.assertEqual(bot.seed_default_control_config(), 0)
        self.assertEqual(c.state[AI_CONFIG_EVENT_TYPE]["system_prompt"], "我的自定义人设")
        self.assertEqual(c.state[GATING_EVENT_TYPE]["gates"], {"ai_chat": "paid"})

    def test_fills_only_missing_persona(self) -> None:
        # 旧 provider 配了但人设空 → 补人设并清除第二套模型配置
        c = _C({AI_CONFIG_EVENT_TYPE: {"provider": "deepseek", "system_prompt": ""}})
        bot = _bot(c)
        bot.seed_default_control_config()
        ai = c.state[AI_CONFIG_EVENT_TYPE]
        self.assertTrue(ai["system_prompt"].strip())     # 补了默认人设
        self.assertNotIn("provider", ai)

    def test_no_control_room_skips(self) -> None:
        c = _C()
        c.resolve_alias = lambda a: None  # 解析不到控制室
        bot = _bot(c)
        self.assertEqual(bot.seed_default_control_config(), 0)
        self.assertEqual(c.writes, [])


if __name__ == "__main__":
    unittest.main()
