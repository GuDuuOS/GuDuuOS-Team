"""存储空间配额(storage_mb)单测:用量核算口径、预检端点、个人库入库硬管控。

负责人需求:每个账号有自己的存储空间(附件+个人知识库),前台可见、按会员等级收费。
"""

from __future__ import annotations

import unittest
from typing import Optional

from cosmac.bots.appservice_bot import CosmacBot
from cosmac.config import CosmacConfig
from cosmac.db import init_engine, session_scope

U = "@u:h"


class _C:
    def whoami(self, token: str) -> Optional[str]:
        return U if token == "tok" else None

    def resolve_alias(self, alias):
        return None

    def get_state_event(self, *a, **k):
        return None

    def set_displayname(self, *a, **k):
        pass


def _bot() -> CosmacBot:
    bot = CosmacBot(CosmacConfig(llm_provider="echo", server_name="h"))
    bot.client = _C()
    return bot


class TestStorageQuota(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)
        self.bot = _bot()
        # 配额直接桩定上限,不依赖控制室(gating/quotas 读不到时的默认行为另有测试)
        self.bot._quota_limit = lambda uid, key: 1 if key == "storage_mb" else -1  # 1MB
        self.bot._gate_allows = lambda *a, **k: True

    def test_kb_bytes_counted(self) -> None:
        # 个人库入库后,存储用量应包含其文本字节
        from cosmac.db import kb
        from cosmac.db.models import SCOPE_USER

        with session_scope() as s:
            kb.ingest_document(s, scope=SCOPE_USER, scope_id=U,
                               title="t", source="upload", text="啊" * 1000)
        self.bot._storage_cache = {}
        self.assertGreaterEqual(self.bot._storage_bytes(U), 1000)

    def test_check_endpoint_over_limit(self) -> None:
        # 预检:本次上传会超 1MB 上限 → ok=False 且带升级提示
        code, payload = self.bot.handle_storage_check("tok", str(2 * 1048576))
        self.assertEqual(code, 200)
        self.assertFalse(payload["ok"])
        self.assertIn("存储空间不足", payload["error"])

    def test_check_endpoint_within_limit(self) -> None:
        code, payload = self.bot.handle_storage_check("tok", "1024")
        self.assertEqual(code, 200)
        self.assertTrue(payload["ok"])

    def test_unlimited_tier(self) -> None:
        self.bot._quota_limit = lambda uid, key: -1
        code, payload = self.bot.handle_storage_check("tok", str(10**9))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["limit_mb"], -1)

    def test_kb_add_enforced(self) -> None:
        # 个人知识库入库(服务端硬管控):**累计**用量逼近上限后,再加一篇即拒
        # (单篇另有 2 万字上限先拦超大文档;存储配额管的是累计,故桩定存量接近 1MB)
        self.bot._storage_bytes = lambda uid: 1048576 - 10  # type: ignore
        code, payload = self.bot.handle_kb_add("tok", {"title": "小文档", "content": "再来二十个字" * 5})
        self.assertEqual(code, 400)
        self.assertIn("存储空间不足", payload["error"])


class TestOnboardIngestKb(unittest.TestCase):
    """#3 修复:入驻批量灌库端点必须与 handle_kb_add 套同一批服务端硬闸。"""

    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)
        self.bot = _bot()
        self.bot._gate_allows = lambda *a, **k: True

    def _count(self) -> int:
        from cosmac.db import kb, session_scope
        from cosmac.db.models import SCOPE_USER
        with session_scope() as s:
            return len(kb.list_docs(s, scope=SCOPE_USER, scope_id=U))

    def test_knowledge_gate_blocks_all(self) -> None:
        # 知识库门控未过 → 一篇都不灌(静默,不打断引导)
        self.bot._gate_allows = lambda *a, **k: False
        self.bot._quota_limit = lambda uid, key: -1
        docs = [{"title": f"t{i}", "content": "内容内容"} for i in range(3)]
        code, payload = self.bot.handle_onboard_ingest_kb("tok", {"docs": docs})
        self.assertEqual(code, 200)
        self.assertEqual(payload["ingested"], 0)
        self.assertEqual(self._count(), 0)

    def test_kb_docs_quota_caps_ingest(self) -> None:
        # 篇数配额=2 → 传 5 篇只灌 2 篇(免费用户模板知识不会绕过篇数上限)
        self.bot._quota_limit = lambda uid, key: 2 if key == "kb_docs" else -1
        docs = [{"title": f"t{i}", "content": "内容内容"} for i in range(5)]
        code, payload = self.bot.handle_onboard_ingest_kb("tok", {"docs": docs})
        self.assertEqual(code, 200)
        self.assertEqual(payload["ingested"], 2)
        self.assertEqual(self._count(), 2)

    def test_storage_quota_caps_ingest(self) -> None:
        # 存储配额:桩定起始存量接近 1MB 上限 → 再灌就停
        self.bot._quota_limit = lambda uid, key: 1 if key == "storage_mb" else -1  # 1MB
        self.bot._storage_bytes = lambda uid: 1048576 - 5  # type: ignore
        docs = [{"title": "t", "content": "十个字十个字"}]  # >5 字符
        code, payload = self.bot.handle_onboard_ingest_kb("tok", {"docs": docs})
        self.assertEqual(payload["ingested"], 0)

    def test_oversized_doc_skipped(self) -> None:
        # 单篇超 MAX_DOC_CHARS → 跳过该篇,其余正常灌
        from cosmac.db.kb_cmd import MAX_DOC_CHARS
        self.bot._quota_limit = lambda uid, key: -1
        docs = [
            {"title": "big", "content": "字" * (MAX_DOC_CHARS + 1)},
            {"title": "ok", "content": "正常内容"},
        ]
        code, payload = self.bot.handle_onboard_ingest_kb("tok", {"docs": docs})
        self.assertEqual(payload["ingested"], 1)
        self.assertEqual(self._count(), 1)


if __name__ == "__main__":
    unittest.main()
