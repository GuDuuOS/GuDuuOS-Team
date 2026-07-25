"""知识库引擎单元测试（内存 SQLite + 哈希词袋嵌入，零 key、零基建）。

哈希嵌入给的是词法相似度，足以验证「入库→检索 top-K 排序、作用域隔离、删除级联」。
运行：.venv/bin/python -m unittest cosmac.tests.test_kb
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

from cosmac.ai.embeddings import HashingEmbedder, cosine, get_embedder
from cosmac.db import init_engine, session_scope
from cosmac.db.kb import (
    chunk_text,
    delete_doc,
    ingest_document,
    list_docs,
    sanitize_text,
    search,
)
from cosmac.db.models import SCOPE_ROOM

ROOM_A = "!a:host"
ROOM_B = "!b:host"
EMB = HashingEmbedder()  # 确定性，测试用同一个


class TestChunking(unittest.TestCase):
    def test_short_text_one_chunk(self) -> None:
        self.assertEqual(chunk_text("短文本"), ["短文本"])

    def test_long_text_split_with_overlap(self) -> None:
        text = "。".join(f"第{i}句内容很长很长很长很长很长很长" for i in range(120))
        chunks = chunk_text(text, size=300, overlap=50)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c) <= 320 for c in chunks))  # 容断点附近的少量超出


class TestSanitize(unittest.TestCase):
    """入库前清洗 NUL/控制字符(负责人实报:上传含 NUL 的 CSV 报"数据库不可用")。"""

    def test_strips_nul_and_controls(self) -> None:
        # NUL + 其它 C0 控制码去掉;\t\n\r 与正文保留
        self.assertEqual(sanitize_text("价格\x00表\x01\n白金\t4520\r\n"), "价格表\n白金\t4520\r\n")

    def test_ingest_csv_with_nul_succeeds(self) -> None:
        """含 NUL 的 CSV 文本能正常入库(以前会因 Postgres 拒 NUL 而抛错被兜底成"数据库不可用")。"""
        init_engine("sqlite://", create_all=True)
        with session_scope() as s:
            doc = ingest_document(
                s, scope=SCOPE_ROOM, scope_id=ROOM_A,
                title="价格\x00表", source="upload",
                text="名称,价格\x00\n白金系列,4520\n晶钻系列,8900", embedder=EMB,
            )
            self.assertNotIn("\x00", doc.title)
            self.assertTrue(all("\x00" not in c.text for c in doc.chunks))
            self.assertTrue(doc.chunks)  # 清洗后仍有内容、正常切块入库


class TestEmbedder(unittest.TestCase):
    def test_no_key_falls_back_to_hashing(self) -> None:
        # 无 embedding key → 默认拿到哈希词袋。清掉可能被别的用例leak进环境的 key，
        # 保证本断言只验「无 key 时的降级」这件事（测试隔离）。
        clear = {k: "" for k in
                 ("COSMAC_EMBED_API_KEY", "OPENAI_API_KEY", "ARK_API_KEY")}
        with mock.patch.dict(os.environ, clear, clear=False):
            for k in clear:
                os.environ.pop(k, None)
            self.assertIsInstance(get_embedder(), HashingEmbedder)

    def test_hashing_self_similarity(self) -> None:
        v = EMB.embed_one("周报 数据 复盘")
        self.assertAlmostEqual(cosine(v, v), 1.0, places=5)


class TestKnowledgeBase(unittest.TestCase):
    def setUp(self) -> None:
        init_engine("sqlite://", create_all=True)

    def _seed_room_a(self) -> None:
        with session_scope() as s:
            ingest_document(s, scope=SCOPE_ROOM, scope_id=ROOM_A, title="周报规范",
                            text="周报怎么写：每周一汇总三平台数据，给出涨粉和完播复盘。", embedder=EMB)
            ingest_document(s, scope=SCOPE_ROOM, scope_id=ROOM_A, title="拍摄脚本",
                            text="短视频拍摄脚本：分镜、运镜、口播节奏与封面设计。", embedder=EMB)

    def test_ingest_creates_doc_and_chunks(self) -> None:
        with session_scope() as s:
            doc = ingest_document(s, scope=SCOPE_ROOM, scope_id=ROOM_A,
                                  title="t", text="一段不太长的内容。", embedder=EMB)
            self.assertIsNotNone(doc.id)
        with session_scope() as s:
            docs = list_docs(s, scope=SCOPE_ROOM, scope_id=ROOM_A)
            self.assertEqual(len(docs), 1)
            self.assertEqual(len(docs[0].chunks), 1)
            self.assertTrue(docs[0].chunks[0].embedding)  # 嵌入已落库

    def test_search_ranks_relevant_first(self) -> None:
        self._seed_room_a()
        with session_scope() as s:
            hits = search(s, query="周报 数据 复盘 怎么写", scope=SCOPE_ROOM, scope_id=ROOM_A, k=2, embedder=EMB)
            self.assertTrue(hits)
            # 与「周报」相关的文档分块应排第一
            self.assertIn("周报", hits[0][0].text)
            self.assertGreater(hits[0][1], hits[-1][1] if len(hits) > 1 else -1)

    def test_scope_isolation(self) -> None:
        self._seed_room_a()
        with session_scope() as s:
            # B 群没有任何文档 → 搜不到
            self.assertEqual(search(s, query="周报", scope=SCOPE_ROOM, scope_id=ROOM_B, embedder=EMB), [])

    def test_embed_tag_stored(self) -> None:
        # #2：入库时记下 embedder 的向量空间标识
        with session_scope() as s:
            doc = ingest_document(s, scope=SCOPE_ROOM, scope_id=ROOM_A,
                                  title="t", text="一段内容。", embedder=EMB)
            self.assertEqual(doc.chunks[0].embed_tag, EMB.tag)  # "hash:256"

    def test_cross_embedder_not_mixed(self) -> None:
        # #2 核心：换了 embedder（不同向量空间）后，旧分块绝不参与检索（否则乱序/失真）。
        self._seed_room_a()  # 用 EMB(hash:256) 入库
        other = HashingEmbedder(dim=128)  # 不同维度 → tag 不同 "hash:128"
        self.assertNotEqual(other.tag, EMB.tag)
        with session_scope() as s:
            hits = search(s, query="周报 数据 复盘", scope=SCOPE_ROOM,
                          scope_id=ROOM_A, embedder=other)
            self.assertEqual(hits, [])  # 旧 tag 的分块被过滤掉

    def test_qvec_reused(self) -> None:
        # #3：传入预算好的 qvec 时，search 不再自己 embed（用传入的向量算分）
        self._seed_room_a()
        with session_scope() as s:
            qvec = EMB.embed_one("周报 数据 复盘")
            hits = search(s, query="x", scope=SCOPE_ROOM, scope_id=ROOM_A,
                          embedder=EMB, qvec=qvec)
            self.assertTrue(hits)
            self.assertIn("周报", hits[0][0].text)

    def test_delete_cascades_chunks(self) -> None:
        with session_scope() as s:
            doc = ingest_document(s, scope=SCOPE_ROOM, scope_id=ROOM_A,
                                  title="t", text="内容一二三。", embedder=EMB)
            did = doc.id
        with session_scope() as s:
            self.assertTrue(delete_doc(s, did))
        with session_scope() as s:
            self.assertEqual(len(list_docs(s, scope=SCOPE_ROOM, scope_id=ROOM_A)), 0)
            # 分块也应随之删除
            self.assertEqual(search(s, query="内容", scope=SCOPE_ROOM, scope_id=ROOM_A, embedder=EMB), [])

    def test_delete_by_source(self) -> None:
        # 文档页↔知识库同步：按 source 精确清理某一页，不误删同作用域其它来源的文档。
        from cosmac.db.kb import delete_by_source
        with session_scope() as s:
            ingest_document(s, scope=SCOPE_ROOM, scope_id=ROOM_A, title="页1",
                            source="docpage:1", text="教程第一页内容。", embedder=EMB)
            ingest_document(s, scope=SCOPE_ROOM, scope_id=ROOM_A, title="页2",
                            source="docpage:2", text="教程第二页内容。", embedder=EMB)
            ingest_document(s, scope=SCOPE_ROOM, scope_id=ROOM_A, title="别的",
                            source="other", text="无关文档。", embedder=EMB)
        with session_scope() as s:
            n = delete_by_source(s, scope=SCOPE_ROOM, scope_id=ROOM_A, source="docpage:1")
            self.assertEqual(n, 1)
        with session_scope() as s:
            titles = sorted(d.title for d in list_docs(s, scope=SCOPE_ROOM, scope_id=ROOM_A))
            self.assertEqual(titles, ["别的", "页2"])  # 只删了 docpage:1


if __name__ == "__main__":
    unittest.main()
