# -*- coding: utf-8 -*-
"""嵌入故障降级单测(线上实报:embeddings 打网关 403 → 知识库上传整个 500)。

ResilientEmbedder:真嵌入调用失败 → 进程内**永久**降级哈希词袋(粘性 flag),
入库/检索共用同一向量空间(tag 跟随生效后端),不再让入库被嵌入故障拖垮。

运行:.venv/bin/python -m unittest cosmac.tests.test_embed_fallback
"""

from __future__ import annotations

import unittest

from cosmac.ai.embeddings import Embedder, HashingEmbedder, ResilientEmbedder


class _BoomEmbedder(Embedder):
    """打桩:模拟网关 403/网络断——每次调用都抛,并记调用次数。"""

    name = "boom"
    calls = 0

    @property
    def tag(self) -> str:
        return "boom:v1"

    def embed(self, texts):
        _BoomEmbedder.calls += 1
        raise RuntimeError("403 该接口不在网关白名单内")


class TestResilientEmbedder(unittest.TestCase):
    def setUp(self) -> None:
        ResilientEmbedder._degraded = False  # 类级粘性 flag,逐测重置
        _BoomEmbedder.calls = 0

    def test_failure_degrades_and_still_returns_vectors(self) -> None:
        emb = ResilientEmbedder(_BoomEmbedder())
        vecs = emb.embed(["产品手册第一章"])
        self.assertEqual(len(vecs), 1)          # 入库不再抛——拿到哈希向量
        self.assertGreater(len(vecs[0]), 0)

    def test_degradation_is_sticky(self) -> None:
        emb = ResilientEmbedder(_BoomEmbedder())
        emb.embed(["a"])
        emb.embed(["b"])
        self.assertEqual(_BoomEmbedder.calls, 1)  # 失败一次后不再碰坏后端

    def test_tag_follows_effective_backend(self) -> None:
        emb = ResilientEmbedder(_BoomEmbedder())
        self.assertEqual(emb.tag, "boom:v1")      # 未降级:真后端空间
        emb.embed(["x"])
        self.assertEqual(emb.tag, HashingEmbedder().tag)  # 降级后:hash 空间(与向量一致)

    def test_sticky_flag_shared_across_instances(self) -> None:
        # 入库与检索各自 get_embedder() 出的实例必须一致降级,否则向量空间分裂
        a = ResilientEmbedder(_BoomEmbedder())
        a.embed(["x"])
        b = ResilientEmbedder(_BoomEmbedder())
        self.assertEqual(b.tag, HashingEmbedder().tag)
        b.embed(["y"])
        self.assertEqual(_BoomEmbedder.calls, 1)  # 新实例也不再碰坏后端


if __name__ == "__main__":
    unittest.main()
