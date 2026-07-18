# -*- coding: utf-8 -*-
"""频道知识隔离单测(负责人实报泄漏:个人知识库内容在频道对话里被 RAG 出来)。

铁律:频道里的 AI 只能用**本频道**的知识库(含管理员显式绑定进频道的知识源);
个人库/全局图文只在私聊(全局助理)里默认可用。另验:频道「规则」tab 真正注入、
频道模式恒注入「频道资源纪律」、建频道默认写入「频道资源边界」规则。

运行:.venv/bin/python -m unittest cosmac.tests.test_channel_kb_isolation
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, Optional

from cosmac.bots.appservice_bot import CosmacBot
from cosmac.config import CosmacConfig
from cosmac.db import init_engine, session_scope
from cosmac.db import kb
from cosmac.db.models import SCOPE_ROOM, SCOPE_USER

ROOM = "!team:h"
U = "@u:h"


class _C:
    """打桩 client:channel_config 可配;其余最小实现。"""

    def __init__(self) -> None:
        self.cfg: Dict[str, Any] = {}

    def get_state_event(self, room_id: str, etype: str, state_key: str = "") -> Optional[Dict[str, Any]]:
        if etype == "cosmac.channel_config":
            return self.cfg
        return None

    def is_joined_member(self, room_id: str, user_id: str) -> bool:
        return True

    def whoami(self, token):
        return U

    def resolve_alias(self, alias):
        return None

    def set_displayname(self, *a, **k):
        pass


def _bot() -> CosmacBot:
    bot = CosmacBot(CosmacConfig(llm_provider="echo", server_name="h"))
    bot.client = _C()
    bot._gate_allows = lambda uid, cap: True  # type: ignore
    bot._doc_can_read = lambda uid: True  # type: ignore
    return bot


def _seed_kb() -> None:
    """个人库放平台机密文档;房间库放频道文档。"""
    with session_scope() as s:
        kb.ingest_document(s, scope=SCOPE_USER, scope_id=U,
                           title="平台项目路线图", source="t",
                           text="模块4交易系统进行中,P1地基已完成,mock支付跑通全链路。")
        kb.ingest_document(s, scope=SCOPE_ROOM, scope_id=ROOM,
                           title="频道拍摄手册", source="t",
                           text="拍摄流程:先定分镜,再排日程,模块设备清单在附录。")


class TestChannelKbIsolation(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)
        self.bot = _bot()
        _seed_kb()

    def test_channel_mode_excludes_user_kb(self) -> None:
        """频道隔离:同一查询,频道模式只命中频道库;个人库(平台路线图)绝不出现。"""
        hits = self.bot._kb_retrieve(ROOM, U, "模块 进行中 拍摄",
                                     include_user_scope=False)
        titles = [t for t, _, _ in hits]
        self.assertNotIn("平台项目路线图", titles)
        self.assertIn("频道拍摄手册", titles)

    def test_dm_mode_still_includes_user_kb(self) -> None:
        """私聊(全局助理)不受影响:个人库照常可检索。"""
        hits = self.bot._kb_retrieve("!dm:h", U, "模块 交易系统 路线图",
                                     include_user_scope=True)
        titles = [t for t, _, _ in hits]
        self.assertIn("平台项目路线图", titles)

    def test_explicit_binding_overrides_isolation(self) -> None:
        """管理员显式把某人个人库绑进频道(bound_sources user:) → 隔离下仍生效(绑定=授权)。"""
        hits = self.bot._kb_retrieve(ROOM, U, "模块 交易系统 路线图",
                                     include_user_scope=False,
                                     bound_sources=[f"user:{U}"])
        titles = [t for t, _, _ in hits]
        self.assertIn("平台项目路线图", titles)

    def test_channel_addendum_has_policy_dm_not(self) -> None:
        """「频道资源纪律」在频道模式恒注入(覆盖存量频道);私聊不注入。"""
        ch = self.bot._skill_addendum(ROOM, U, query="随便问问", is_dm=False)
        dm = self.bot._skill_addendum("!dm:h", U, query="随便问问", is_dm=True)
        self.assertIn("频道资源纪律", ch)
        self.assertNotIn("频道资源纪律", dm)

    def test_rules_tab_injected(self) -> None:
        """频道管理「规则」tab 的规则真正注入(此前从未生效——配了等于摆设)。"""
        self.bot.client.cfg = {"rules": [
            {"label": "报价审批", "desc": "对外报价必须先经负责人确认"},
            {"label": "频道资源边界", "desc": ""},
        ]}
        out = self.bot._skill_addendum(ROOM, U, query="报价", is_dm=False)
        self.assertIn("本频道规则", out)
        self.assertIn("报价审批:对外报价必须先经负责人确认", out)
        self.assertIn("频道资源边界", out)

    def test_channel_kb_context_skips_global_docs(self) -> None:
        """频道隔离下全局图文教程也不纳入 RAG(平台内容非本频道资源)。"""
        called: list = []
        orig = self.bot._kb_retrieve

        def spy(room_id, sender, query, **kw):
            called.append(kw.get("extra_scopes") or [])
            return orig(room_id, sender, query, **kw)
        self.bot._kb_retrieve = spy  # type: ignore
        self.bot._kb_context(ROOM, U, "拍摄", channel_isolated=True)
        self.assertNotIn(self.bot._GLOBAL_DOC_ROOM, called[0])
        called.clear()
        self.bot._kb_context("!dm:h", U, "拍摄", channel_isolated=False)
        self.assertIn(self.bot._GLOBAL_DOC_ROOM, called[0])


if __name__ == "__main__":
    unittest.main()
