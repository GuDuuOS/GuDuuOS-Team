"""知识库引擎：入库（切块 + 嵌入）与检索（语义相似度 top-K）。

设计取舍（见 CLAUDE.md §3）：
- 检索 v1 在 **Python 里算余弦相似度**（嵌入已 L2 归一化，点积即余弦），在「该作用域的
  分块」上排序取 top-K。**SQLite / Postgres 都能跑、本地可验**；不依赖 pgvector。
- 规模化后（分块上万）再在 Postgres 上换 pgvector 列 + 近邻索引提速；接口不变。

作用域沿用 Skill/Agent 那套：room=本群知识库 / user=个人 / global=全平台。
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from cosmac.ai.embeddings import Embedder, cosine, get_embedder
from cosmac.db.models import SCOPE_ROOM, KnowledgeChunk, KnowledgeDoc

# 切块参数：按字符长度切，带重叠避免把一句话拦腰截断丢了上下文。
DEFAULT_CHUNK_SIZE = 500
DEFAULT_CHUNK_OVERLAP = 80


def chunk_text(
    text: str,
    size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> List[str]:
    """把长文本切成带重叠的块。优先在段落/句子边界附近切，找不到就硬切。"""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    chunks: List[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + size, n)
        if end < n:
            # 在 [start+size*0.6, end] 里找最后一个自然断点，断得好看些
            window = text[start:end]
            cut = max(window.rfind("\n"), window.rfind("。"), window.rfind(". "))
            if cut >= int(size * 0.6):
                end = start + cut + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= n:
            break
        start = max(end - overlap, start + 1)  # 重叠回退，且保证前进
    return chunks


def ingest_document(
    session: Session,
    *,
    scope: str = SCOPE_ROOM,
    scope_id: str = "",
    title: str = "",
    source: str = "",
    text: str = "",
    embedder: Optional[Embedder] = None,
) -> KnowledgeDoc:
    """把一篇文档切块 + 嵌入 + 落库，返回建好的 KnowledgeDoc（含 chunks）。"""
    emb = embedder or get_embedder()
    pieces = chunk_text(text)
    vectors = emb.embed(pieces) if pieces else []
    doc = KnowledgeDoc(scope=scope, scope_id=scope_id, title=title, source=source)
    session.add(doc)
    session.flush()  # 拿到 doc.id
    for i, (piece, vec) in enumerate(zip(pieces, vectors)):
        session.add(
            KnowledgeChunk(
                doc_id=doc.id,
                scope=scope,
                scope_id=scope_id,
                ordinal=i,
                text=piece,
                embedding=vec,
                embed_tag=emb.tag,  # 记下用哪个 embedder 嵌的，检索时据此只比同空间
            )
        )
    session.flush()
    return doc


def search(
    session: Session,
    *,
    query: str,
    scope: str = SCOPE_ROOM,
    scope_id: str = "",
    k: int = 4,
    embedder: Optional[Embedder] = None,
    min_score: float = 0.0,
    qvec: Optional[List[float]] = None,
) -> List[Tuple[KnowledgeChunk, float]]:
    """在某作用域的分块里按语义相似度取 top-K，返回 [(chunk, score), ...] 降序。

    v1：把该作用域、**且向量空间(embed_tag)与当前 embedder 一致**的分块 load 进来在
    Python 里算余弦。规模大了再上 pgvector。``min_score`` 过滤太不相关的。

    - #2 正确性：只比 ``embed_tag == emb.tag`` 的分块——换了 embedder（如从哈希兜底切到
      真嵌入）后，旧向量不会再混进来产生乱序/失真。旧数据需重新入库才会被检索到。
    - #3 性能：``qvec`` 可传入**已算好的查询向量**，避免一次回复对群库/个人库各 embed 一遍。
    """
    q = (query or "").strip()
    if not q:
        return []
    emb = embedder or get_embedder()
    qv = qvec if qvec is not None else emb.embed_one(q)
    stmt = select(KnowledgeChunk).where(
        KnowledgeChunk.scope == scope,
        KnowledgeChunk.scope_id == scope_id,
        KnowledgeChunk.embed_tag == emb.tag,  # 只比同一向量空间
    )
    scored: List[Tuple[KnowledgeChunk, float]] = []
    for ch in session.scalars(stmt).all():
        score = cosine(qv, ch.embedding or [])
        if score >= min_score:
            scored.append((ch, score))
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored[:k]


def list_docs(
    session: Session, *, scope: str = SCOPE_ROOM, scope_id: str = ""
) -> List[KnowledgeDoc]:
    """列出某作用域的文档（按入库时间倒序）。"""
    stmt = (
        select(KnowledgeDoc)
        .where(KnowledgeDoc.scope == scope, KnowledgeDoc.scope_id == scope_id)
        .order_by(KnowledgeDoc.id.desc())
    )
    return list(session.scalars(stmt).all())


def delete_docs_by_title(
    session: Session, *, scope: str, scope_id: str, title: str
) -> int:
    """删除某作用域下**同名**文档，返回删除篇数。

    上传入口用它实现「同名=覆盖更新」语义（负责人实报：同一份文件反复上传，
    既不去重也不覆盖，列表堆出好几条一模一样的记录）。按 title 精确匹配。
    """
    t = (title or "").strip()
    if not t:
        return 0
    stmt = select(KnowledgeDoc).where(
        KnowledgeDoc.scope == scope,
        KnowledgeDoc.scope_id == scope_id,
        KnowledgeDoc.title == t,
    )
    docs = list(session.scalars(stmt).all())
    for d in docs:
        session.delete(d)
    session.flush()
    return len(docs)


def delete_doc(session: Session, doc_id: int) -> bool:
    """删除一篇文档（连带其分块，cascade）。删掉返回 True。"""
    doc = session.get(KnowledgeDoc, doc_id)
    if doc is None:
        return False
    session.delete(doc)
    session.flush()
    return True


def delete_by_source(
    session: Session, *, scope: str, scope_id: str, source: str
) -> int:
    """按 source 删该作用域下的文档（连带分块）。返回删了几篇。

    给「文档页 ↔ 知识库」同步用：每个文档页入库时 source=``docpage:<id>``，页面更新/删除时
    先按这个 source 清掉旧的再重灌，避免知识库里残留过期内容。
    """
    docs = list(
        session.scalars(
            select(KnowledgeDoc).where(
                KnowledgeDoc.scope == scope,
                KnowledgeDoc.scope_id == scope_id,
                KnowledgeDoc.source == source,
            )
        ).all()
    )
    for d in docs:
        session.delete(d)
    session.flush()
    return len(docs)
