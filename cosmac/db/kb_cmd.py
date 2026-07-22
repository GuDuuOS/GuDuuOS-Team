"""「知识」聊天命令：往本群/个人知识库加文档、列出、删除、试搜。

与 skill_cmd 同套路：纯逻辑、吃一个 Session、返回要回的文本；bot 负责前缀识别、
作用域判断（群=本群知识库 / 私聊=个人）、写权限闸、兜异常。

命令（不强制 / 开头，避免被 Element 当客户端命令拦截；也兼容 /知识）：
    知识 / 知识 帮助
    知识 列表
    知识 添加 <标题> ｜ <正文>
    知识 删除 <编号>
    知识 搜 <关键词>           —— 试检索，看本群知识库会命中什么
"""

from __future__ import annotations

import re
from typing import Callable, Optional

from sqlalchemy.orm import Session

from cosmac.db import kb
from cosmac.db.models import SCOPE_ROOM, SCOPE_USER, KnowledgeDoc

# 个人库入库前的会员配额守卫签名：(当前篇数, 本篇正文**UTF-8 字节数**) -> 超额提示 或 None(放行)。
# 由 bot 用 _quota_limit/_storage_bytes 构建注入——kb_cmd 不直接依赖 bot 内部（解耦）。
PersonalAddGuard = Callable[[int, int], Optional[str]]

PREFIXES = ("知识", "/知识", "kb", "/kb")

# 容量护栏（与技能命令同理，防滥用撑爆 DB / 上下文）
# 单篇上限 2 万→5 万(负责人 2026-07-22 反馈:产品手册/价格表轻松超 2 万;分块检索
# 架构下大文档无技术障碍,仍留上限防滥用——篇数/存储另有会员配额管控)。
MAX_DOC_CHARS = 50000          # 单篇正文上限
MAX_DOCS_PER_SCOPE = 200       # 每个作用域文档数上限


def clean_upload_text(text: str, filename: str = "") -> str:
    """上传文档入库前的内容清洗——修「空 CSV 报太长」(负责人实报)。

    Excel 把"看起来空"的工作表另存为 CSV 时,会导出成千上万行纯逗号(空单元格
    分隔符),视觉空文件实际两万多字,直接按原文计数就误报"太长"。清洗规则:
    - CSV/TSV(按文件名后缀):剔除**纯分隔符行**(去掉 ,;、制表符、引号、空白后
      什么都不剩的行)——真实数据行含内容字符,不受影响;
    - 所有文件:每行去尾部空白,3 个以上连续空行压成 1 个。
    清洗结果同时用于**计数与入库**——不清洗就入库会把分隔符噪音灌进检索。
    """
    lines = [ln.rstrip() for ln in (text or "").splitlines()]
    if filename.lower().rsplit(".", 1)[-1] in ("csv", "tsv"):
        # 纯分隔符行:去掉分隔符与引号后为空 → 是 Excel 导出的空单元格行,丢弃
        lines = [
            ln for ln in lines
            if ln.translate(str.maketrans("", "", ",;\t\"' ")).strip()
        ]
    out: list = []
    blank = 0
    for ln in lines:
        if ln == "":
            blank += 1
            if blank > 1:
                continue  # 连续空行只留 1 个
        else:
            blank = 0
        out.append(ln)
    return "\n".join(out).strip()


def looks_like_kb_command(text: str) -> bool:
    """快速判断（不连 DB）：这条是不是知识命令。"""
    t = text.strip()
    if t.startswith("知识") or t.startswith("/知识"):
        return True
    low = t.lower()
    return any(low == p or low.startswith(p + " ") for p in ("kb", "/kb"))


def handle_kb_command(
    session: Session,
    *,
    is_dm: bool,
    room_id: str,
    user_id: str,
    text: str,
    can_write: bool = True,
    personal_add_guard: Optional[PersonalAddGuard] = None,
) -> str:
    """执行一条知识命令，返回要发回聊天的文本。

    作用域：私聊→个人知识库(user)；群里→本群知识库(room)。
    写操作（添加/删除）在群里需要管理员（can_write）；私聊改自己的不受限。
    personal_add_guard：个人库「添加」时的会员配额守卫（kb_docs 篇数 + storage_mb），
      由 bot 注入；群库不走它（群库有自己的容量口径）。缺省不校验（如单测）。
    """
    scope = SCOPE_USER if is_dm else SCOPE_ROOM
    scope_id = user_id if is_dm else room_id
    where = "你的个人知识库" if is_dm else "本群知识库"
    need_admin = (not is_dm) and (not can_write)

    rest = _strip_prefix(text).strip()
    if not rest or rest in ("帮助", "help", "?", "？"):
        return _help()

    parts = rest.split(maxsplit=1)
    sub = parts[0]
    arg = parts[1].strip() if len(parts) > 1 else ""

    if sub in ("列表", "list", "ls"):
        return _list(session, scope, scope_id, where)
    if sub in ("搜", "搜索", "search", "find"):
        return _search(session, scope, scope_id, arg)
    if sub in ("添加", "新增", "add"):
        if need_admin:
            return "只有群管理员能往本群知识库添加文档。"
        guard = personal_add_guard if scope == SCOPE_USER else None
        return _add(session, scope, scope_id, where, arg, guard)
    if sub in ("删除", "删", "del", "rm", "remove"):
        if need_admin:
            return "只有群管理员能删除本群知识库的文档。"
        return _delete(session, scope, scope_id, arg)
    return f"没听懂「{sub}」。\n{_help()}"


# ───────────────────────── 子命令 ─────────────────────────

def _list(session: Session, scope: str, scope_id: str, where: str) -> str:
    docs = kb.list_docs(session, scope=scope, scope_id=scope_id)
    if not docs:
        return f"{where}还没有文档。用「知识 添加 <标题> ｜ <正文>」加一篇。"
    lines = [f"📚 {where}（共 {len(docs)} 篇）："]
    for d in docs:
        n = len(d.chunks)
        lines.append(f"  #{d.id} {d.title or '(无标题)'}（{n} 段）")
    return "\n".join(lines)


def _add(
    session: Session, scope: str, scope_id: str, where: str, arg: str,
    guard: Optional[PersonalAddGuard] = None,
) -> str:
    if not arg:
        return "用法：知识 添加 <标题> ｜ <正文>"
    segs = [s.strip() for s in re.split(r"[|｜]", arg, maxsplit=1)]
    title = segs[0]
    body = segs[1] if len(segs) > 1 else ""
    if not body:
        return "缺正文。用法：知识 添加 <标题> ｜ <正文>"
    if len(body) > MAX_DOC_CHARS:
        return f"正文太长（{len(body)} 字），上限 {MAX_DOC_CHARS} 字。请拆成多篇。"
    cur = len(kb.list_docs(session, scope=scope, scope_id=scope_id))
    if cur >= MAX_DOCS_PER_SCOPE:
        return f"{where}已达数量上限（{MAX_DOCS_PER_SCOPE} 篇），先删一些再加。"
    # 个人库会员配额（篇数 kb_docs + 存储 storage_mb）：与 UI handle_kb_add 同口径服务端强制，
    # 否则免费用户绕开 UI、走聊天命令「知识 添加」可加满 200 篇（M4）。
    if guard is not None:
        err = guard(cur, len(body.encode("utf-8")))  # L1：按字节，与存储配额口径一致
        if err:
            return err
    doc = kb.ingest_document(
        session, scope=scope, scope_id=scope_id, title=title, source="chat", text=body
    )
    n = len(doc.chunks)
    return f"✅ 已把「{title or '(无标题)'}」收进{where}（切成 {n} 段，编号 #{doc.id}）。主 AI 在此可据它作答。"


def _delete(session: Session, scope: str, scope_id: str, arg: str) -> str:
    m = re.search(r"\d+", arg)
    if not m:
        return "用法：知识 删除 <编号>（编号见「知识 列表」）"
    doc_id = int(m.group())
    # 只能删本作用域的文档（防跨群删别人的）
    doc = session.get(KnowledgeDoc, doc_id)
    if doc is None or doc.scope != scope or doc.scope_id != scope_id:
        return f"没找到编号 #{doc_id} 的文档。"
    kb.delete_doc(session, doc_id)
    return f"🗑 已删除 #{doc_id}「{doc.title or '(无标题)'}」。"


def _search(session: Session, scope: str, scope_id: str, query: str) -> str:
    if not query.strip():
        return "用法：知识 搜 <关键词>"
    hits = kb.search(session, query=query, scope=scope, scope_id=scope_id, k=3, min_score=0.01)
    if not hits:
        return "没检索到相关内容。"
    lines = ["🔎 命中（按相关度）："]
    for ch, score in hits:
        snippet = ch.text[:60].replace("\n", " ")
        lines.append(f"  · 《{ch.doc.title or '(无标题)'}》 {score:.2f}：{snippet}…")
    return "\n".join(lines)


# ───────────────────────── 工具 ─────────────────────────

def _help() -> str:
    return (
        "📚 知识库命令：\n"
        "  知识 列表\n"
        "  知识 添加 <标题> ｜ <正文>\n"
        "  知识 删除 <编号>\n"
        "  知识 搜 <关键词>\n"
        "（群里建的是本群知识库，私聊我建的是你的个人知识库。主 AI 回话时会自动检索并参考。）"
    )


def _strip_prefix(text: str) -> str:
    t = text.strip()
    low = t.lower()
    for p in PREFIXES:
        if low.startswith(p):
            return t[len(p):]
    return t


__all__ = ["handle_kb_command", "looks_like_kb_command"]
