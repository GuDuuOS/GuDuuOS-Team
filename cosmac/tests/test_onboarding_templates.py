"""#9 回归：入驻模板对普通用户可见——bot 代读私有控制室并只返回已上架模板。

背景：模板存私有控制室 state event，普通用户读控制室必 403、旧前端静默回退内置模板，后台配的
模板永不生效。新增 handle_onboarding_templates 由 bot（控制室成员）代读。
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, List, Optional

from cosmac.bots.appservice_bot import CosmacBot
from cosmac.config import ONBOARDING_TEMPLATES_EVENT_TYPE, CosmacConfig

CTRL = "!ctrl:h"


class _Client:
    def __init__(self, templates: Optional[List[Dict[str, Any]]], ctrl=CTRL) -> None:
        self._templates = templates
        self._ctrl = ctrl

    def whoami(self, token: str) -> Optional[str]:
        return "@u:h" if token == "tok" else None

    def resolve_alias(self, alias: str) -> Optional[str]:
        return self._ctrl

    def get_state_event(self, room_id, event_type, state_key=""):
        if event_type == ONBOARDING_TEMPLATES_EVENT_TYPE and self._templates is not None:
            return {"templates": self._templates}
        return None


def _bot(templates, ctrl=CTRL) -> CosmacBot:
    bot = CosmacBot(CosmacConfig(llm_provider="echo", server_name="h"))
    bot.client = _Client(templates, ctrl)  # type: ignore
    return bot


class TestOnboardingTemplates(unittest.TestCase):
    def test_requires_login(self) -> None:
        code, _ = _bot([]).handle_onboarding_templates("bad")
        self.assertEqual(code, 401)

    def test_returns_enabled_templates(self) -> None:
        tpls = [
            {"key": "film", "label": "影视工作室", "tier": "paid",
             "kbDocs": [{"title": "手册", "content": "正文"}], "channels": ["制作"]},
            {"key": "hidden", "label": "未上架", "enabled": False},
            {"key": "", "label": "缺key"},          # 脏数据丢弃
        ]
        code, payload = _bot(tpls).handle_onboarding_templates("tok")
        self.assertEqual(code, 200)
        keys = [t["key"] for t in payload["templates"]]
        self.assertEqual(keys, ["film"])            # 只返回已上架且字段齐的
        t0 = payload["templates"][0]
        self.assertEqual(t0["tier"], "paid")
        self.assertEqual(t0["kbDocs"], [{"title": "手册", "content": "正文"}])
        self.assertEqual(t0["channels"], ["制作"])

    def test_no_control_room_returns_empty(self) -> None:
        # 控制室解析不到 → 空列表（前端回退内置模板，不报错）
        code, payload = _bot([], ctrl=None).handle_onboarding_templates("tok")
        self.assertEqual(code, 200)
        self.assertEqual(payload["templates"], [])

    def test_unconfigured_returns_empty(self) -> None:
        # 控制室在、但没配模板 state → 空列表
        code, payload = _bot(None).handle_onboarding_templates("tok")
        self.assertEqual(code, 200)
        self.assertEqual(payload["templates"], [])


if __name__ == "__main__":
    unittest.main()
