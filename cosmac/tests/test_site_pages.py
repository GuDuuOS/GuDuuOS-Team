"""公开页面内容（handle_site_page：注册页 隐私政策/帮助中心）单测。

要点：默认稿兜底(未配置/控制室读不到也有内容)、后台配置覆盖、key 白名单。
"""

from __future__ import annotations

import unittest
from typing import Optional

from cosmac.bots.appservice_bot import CosmacBot
from cosmac.config import CosmacConfig


class FakeClient:
    def __init__(self, pages: Optional[dict] = None, broken: bool = False):
        self._pages = pages
        self._broken = broken

    def resolve_alias(self, alias: str) -> Optional[str]:
        if self._broken:
            raise RuntimeError("控制室不可达")
        return "!ctrl:h"

    def get_state_event(self, room_id, etype, state_key=""):
        if etype == "cosmac.pages":
            return self._pages
        return None

    def set_displayname(self, *a, **k):
        pass


def _bot(pages=None, broken=False) -> CosmacBot:
    bot = CosmacBot(CosmacConfig(llm_provider="echo", server_name="h"))
    bot.client = FakeClient(pages, broken)
    return bot


class TestSitePages(unittest.TestCase):
    def test_default_when_unconfigured(self) -> None:
        code, p = _bot(pages=None).handle_site_page("privacy")
        self.assertEqual(code, 200)
        self.assertEqual(p["title"], "隐私政策")
        self.assertIn("我们收集什么", p["md"])   # 内置默认稿

    def test_config_overrides_default(self) -> None:
        pages = {"help": {"title": "使用指南", "md": "第一步:注册。"}}
        code, p = _bot(pages=pages).handle_site_page("help")
        self.assertEqual(code, 200)
        self.assertEqual(p["title"], "使用指南")
        self.assertEqual(p["md"], "第一步:注册。")

    def test_empty_config_falls_back(self) -> None:
        # 后台把正文清空 → 回落默认稿(公开页面绝不能空白)
        pages = {"privacy": {"title": "x", "md": "   "}}
        code, p = _bot(pages=pages).handle_site_page("privacy")
        self.assertEqual(code, 200)
        self.assertIn("我们收集什么", p["md"])

    def test_broken_control_room_falls_back(self) -> None:
        code, p = _bot(broken=True).handle_site_page("help")
        self.assertEqual(code, 200)
        self.assertIn("快速上手", p["md"])

    def test_unknown_key_404(self) -> None:
        code, _ = _bot().handle_site_page("evil")
        self.assertEqual(code, 404)


if __name__ == "__main__":
    unittest.main()
