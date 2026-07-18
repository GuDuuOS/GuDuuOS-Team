# -*- coding: utf-8 -*-
"""存量频道默认规则补写单测(负责人:每个频道都要有可见 RULE,存量不能漏)。

运行:.venv/bin/python -m unittest cosmac.tests.test_rules_backfill
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, List, Optional, Tuple

from cosmac.bots.appservice_bot import CosmacBot
from cosmac.config import CosmacConfig
from cosmac.db import init_engine


class _C:
    """打桩 client:三个房——无规则频道 / 已有规则频道 / 控制室。"""

    def __init__(self) -> None:
        self.cfgs: Dict[str, Dict[str, Any]] = {
            "!bare:h": {"persona": {"aiName": "旧人设"}, "kbScopes": ["platform"]},
            "!ruled:h": {"rules": [{"label": "自定义规则", "desc": "x"}]},
            "!ctrl:h": {},
        }
        self.names = {"!bare:h": "老专班", "!ruled:h": "有规频道", "!ctrl:h": "CosMac 控制室"}
        self.written: List[Tuple[str, Dict[str, Any]]] = []

    def joined_rooms(self) -> list:
        return list(self.cfgs.keys())

    def get_state_event(self, room: str, etype: str, state_key: str = "") -> Optional[Dict[str, Any]]:
        if etype == "cosmac.channel_config":
            return dict(self.cfgs.get(room) or {})
        if etype == "m.room.name":
            return {"name": self.names.get(room, "")}
        return None

    def set_state_event(self, room: str, etype: str, content: Dict[str, Any], state_key: str = "") -> bool:
        self.written.append((room, content))
        return True

    def whoami(self, token):
        return "@u:h"

    def resolve_alias(self, alias):
        return None

    def set_displayname(self, *a, **k):
        pass


class TestRulesBackfill(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)
        self.bot = CosmacBot(CosmacConfig(llm_provider="echo", server_name="h"))
        self.bot.client = _C()
        # 全部房间判为频道(控制室靠名字排除);判定方法在 toolbox 上
        self.bot.toolbox._room_kind = lambda rid: "channel"  # type: ignore

    def test_backfills_only_bare_channels_and_merges(self) -> None:
        n = self.bot.backfill_channel_rules()
        self.assertEqual(n, 1)
        [(room, content)] = self.bot.client.written
        self.assertEqual(room, "!bare:h")
        # 补上了默认规则
        self.assertEqual(content["rules"][0]["label"], "频道资源边界")
        # merge 语义:原有 persona/kbScopes 一个不丢(set_state_event 是覆盖,不 merge 会抹掉)
        self.assertEqual(content["persona"], {"aiName": "旧人设"})
        self.assertEqual(content["kbScopes"], ["platform"])

    def test_idempotent_second_run_writes_nothing(self) -> None:
        self.bot.backfill_channel_rules()
        # 把第一轮的结果"落库"进桩,再跑一遍 → 零写入
        for room, content in self.bot.client.written:
            self.bot.client.cfgs[room] = content
        self.bot.client.written.clear()
        self.assertEqual(self.bot.backfill_channel_rules(), 0)
        self.assertEqual(self.bot.client.written, [])


if __name__ == "__main__":
    unittest.main()
