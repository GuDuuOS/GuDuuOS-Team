"""数据库连接 / 会话管理（同步 SQLAlchemy）。

为什么这么设计：
- **同步**：主 AI bot 是同步的（``ThreadingHTTPServer`` + ``requests``），数据层也保持
  同步，不引入 async 的复杂度。
- **连接来源**：``COSMAC_DATABASE_URL`` 环境变量优先（旧 ``GUDUU_DATABASE_URL`` 仍兼容；生产用它指向独立 PostgreSQL）；
  没设就回退到本地 SQLite 文件 ``run/cosmac.db``——本地开发/跑测试零基建即可。
- **懒初始化**：第一次用到时才建 engine（``get_session`` 会自动 ``init_engine``），
  测试可以先用内存库显式 ``init_engine("sqlite://")`` 覆盖默认。

注意：知识库的 pgvector 是 Postgres 专属能力，本地 SQLite 跑不了向量检索——
相关功能要能在缺 pgvector 时优雅降级（见 CLAUDE.md §3）。
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from cosmac.db.models import (
    Agent,
    Skill,
    Base,
    DocPage,
    KnowledgeChunk,
    Order,
    SeenTxn,
    Task,
    WorkflowRun,
)

logger = logging.getLogger("cosmac.db.engine")

# —— 模块级单例：进程内共享一个 engine / sessionmaker ——
# bot 多线程（每个 HTTP 请求一个线程），engine 的连接池本身线程安全；
# session 不跨线程共享——每次用 get_session()/session_scope() 现取现用。
_engine: Optional[Engine] = None
_Session: Optional[sessionmaker] = None


def database_url() -> str:
    """解析要连的数据库 URL。

    优先级：环境变量 COSMAC_DATABASE_URL（旧 GUDUU_DATABASE_URL 仍兼容）> 本地默认
    SQLite（run/cosmac.db）。本地默认用绝对路径，避免「从不同工作目录启动」时 SQLite
    落在不同文件。
    """
    url = os.environ.get("COSMAC_DATABASE_URL") or os.environ.get("GUDUU_DATABASE_URL")
    if url:
        return url
    # 仓库根：cosmac/db/engine.py → 上三级。本地产物统一放 run/（已 gitignore）。
    repo_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    run_dir = os.path.join(repo_root, "run")
    os.makedirs(run_dir, exist_ok=True)
    return f"sqlite:///{os.path.join(run_dir, 'cosmac.db')}"


def init_engine(url: Optional[str] = None, *, create_all: bool = True) -> Engine:
    """（重新）初始化进程内的 engine 与 sessionmaker。

    参数：
        url:        要连的数据库；不传则用 ``database_url()`` 解析。
        create_all: 是否顺手按 models 建表（greenfield 阶段够用；以后上 alembic 迁移再关掉）。

    返回建好的 engine。测试里可传 ``"sqlite://"`` 用纯内存库。
    """
    global _engine, _Session
    resolved = url or database_url()
    # SQLite 内存库（"sqlite://"）必须用 StaticPool 才能在同一连接里保留建好的表，
    # 否则每次取连接都是新的空库；文件库则正常用默认池。
    connect_args = {}
    engine_kwargs = {"future": True}
    if resolved.startswith("sqlite"):
        # 允许跨线程使用同一连接（bot 多线程）。
        connect_args["check_same_thread"] = False
        if ":memory:" in resolved or resolved in ("sqlite://", "sqlite:///:memory:"):
            from sqlalchemy.pool import StaticPool

            engine_kwargs["poolclass"] = StaticPool
    _engine = create_engine(resolved, connect_args=connect_args, **engine_kwargs)
    _Session = sessionmaker(bind=_engine, future=True, expire_on_commit=False)
    if create_all:
        Base.metadata.create_all(_engine)
        _heal_ephemeral_schema(_engine)
        _heal_business_schema(_engine)
    return _engine


def _heal_ephemeral_schema(engine: Engine) -> None:
    """对**纯缓存/派生**表做轻量"自愈"——目前仅事务去重表 SeenTxn。

    没上 alembic，``create_all`` 只建缺失的表、不会给已存在的表补列。早期版本的
    ``cosmac_seen_txn`` 只有 ``txn_id``；新增了 ``done``/``claimed_at`` 后，老库上
    INSERT 会因缺列失败 → 去重静默退回内存。这类表是 7 天 TTL 的一次性缓存、丢了可
    重新生成，故直接 DROP+重建最省事（**仅限这类缓存表，业务数据表绝不在此自动 DROP**）。
    任何失败都不致命：退回内存去重，不阻断启动。
    """
    try:
        insp = inspect(engine)
        if not insp.has_table(SeenTxn.__tablename__):
            return  # create_all 已按新模型建好
        have = {c["name"] for c in insp.get_columns(SeenTxn.__tablename__)}
        need = {c.name for c in SeenTxn.__table__.columns}
        if not need.issubset(have):  # 老库缺列 → 重建为新模式
            logger.info("去重缓存表列过时，DROP 重建 %s", SeenTxn.__tablename__)
            SeenTxn.__table__.drop(engine, checkfirst=True)
            SeenTxn.__table__.create(engine, checkfirst=True)
    except Exception:
        logger.warning("自愈去重缓存表失败（不致命，退回内存去重）", exc_info=True)


def _heal_business_schema(engine: Engine) -> None:
    """对已有业务表做**非破坏性**补列。

    greenfield 阶段还没引入 alembic，``create_all`` 只能建新表，不能给旧表补新增列。业务表
    不能像缓存表那样 DROP 重建，否则会丢运行记录/订单等审计数据；所以这里仅做兼容性补列：
    旧生产库缺哪些新增列，就 ``ALTER TABLE ... ADD COLUMN`` 补上，已有行保留。
    """
    try:
        insp = inspect(engine)
        # 工作流运行表补列
        if insp.has_table(WorkflowRun.__tablename__):
            have = {c["name"] for c in insp.get_columns(WorkflowRun.__tablename__)}
            with engine.begin() as conn:
                if "status" not in have:
                    conn.execute(text(
                        "ALTER TABLE cosmac_workflow_run "
                        "ADD COLUMN status VARCHAR(16) NOT NULL DEFAULT 'ok'"
                    ))
                if "token" not in have:
                    conn.execute(text(
                        "ALTER TABLE cosmac_workflow_run "
                        "ADD COLUMN token VARCHAR(64) NOT NULL DEFAULT ''"
                    ))
                if "source_key" not in have:
                    conn.execute(text(
                        "ALTER TABLE cosmac_workflow_run "
                        "ADD COLUMN source_key VARCHAR(255)"
                    ))
        # 知识库分块表补列：旧生产库建表时还没 embed_tag（向量空间标识），补上否则入库报
        # UndefinedColumn、整个 RAG/知识库写入失效。
        if insp.has_table(KnowledgeChunk.__tablename__):
            have = {c["name"] for c in insp.get_columns(KnowledgeChunk.__tablename__)}
            if "embed_tag" not in have:
                with engine.begin() as conn:
                    conn.execute(text(
                        "ALTER TABLE cosmac_kb_chunk "
                        "ADD COLUMN embed_tag VARCHAR(64) NOT NULL DEFAULT ''"
                    ))
        # 智能体表补列：旧库的 cosmac_agent 还没有 workflow_slugs（智能体绑工作流），
        # 补上否则读写个人智能体时报 UndefinedColumn。JSON 列给 '[]' 默认值，
        # 已有行自动变成"没绑任何工作流"，语义正确。
        if insp.has_table(Agent.__tablename__):
            have = {c["name"] for c in insp.get_columns(Agent.__tablename__)}
            if "workflow_slugs" not in have:
                with engine.begin() as conn:
                    conn.execute(text(
                        "ALTER TABLE cosmac_agent "
                        "ADD COLUMN workflow_slugs JSON NOT NULL DEFAULT '[]'"
                    ))
        # 技能/智能体补列：source_url（从 GitHub 导入的来源，空=自建）。
        # 与上面 workflow_slugs 同理——没上 alembic，旧库得靠这里补。
        for _model in (Skill, Agent):
            if insp.has_table(_model.__tablename__):
                have = {c["name"] for c in insp.get_columns(_model.__tablename__)}
                if "source_url" not in have:
                    with engine.begin() as conn:
                        conn.execute(text(
                            f"ALTER TABLE {_model.__tablename__} "
                            "ADD COLUMN source_url VARCHAR(500) NOT NULL DEFAULT ''"
                        ))
        # 任务表补列：旧库的 cosmac_task 还没有类型化执行者两列（模块3.5 档2），补上
        # 否则拆任务带 executor_kind/ref 写入时报 UndefinedColumn。
        if insp.has_table(Task.__tablename__):
            have = {c["name"] for c in insp.get_columns(Task.__tablename__)}
            with engine.begin() as conn:
                if "executor_kind" not in have:
                    conn.execute(text(
                        "ALTER TABLE cosmac_task "
                        "ADD COLUMN executor_kind VARCHAR(16) NOT NULL DEFAULT 'none'"
                    ))
                if "executor_ref" not in have:
                    conn.execute(text(
                        "ALTER TABLE cosmac_task "
                        "ADD COLUMN executor_ref VARCHAR(255) NOT NULL DEFAULT ''"
                    ))
                # 真人审核流程：旧任务不能被突然卡住，因此 reviewer_ref 空串 +
                # review_status=none 保留历史语义；新任务由应用层填入真人审核人。
                if "reviewer_ref" not in have:
                    conn.execute(text(
                        "ALTER TABLE cosmac_task "
                        "ADD COLUMN reviewer_ref VARCHAR(255) NOT NULL DEFAULT ''"
                    ))
                if "review_status" not in have:
                    conn.execute(text(
                        "ALTER TABLE cosmac_task "
                        "ADD COLUMN review_status VARCHAR(16) NOT NULL DEFAULT 'none'"
                    ))
                # 任务时效（快到期/逾期提醒）新增两列：截止时间 + 提醒去重位。
                if "due_ts" not in have:
                    conn.execute(text(
                        "ALTER TABLE cosmac_task ADD COLUMN due_ts BIGINT"
                    ))
                if "reminded" not in have:
                    conn.execute(text(
                        "ALTER TABLE cosmac_task "
                        "ADD COLUMN reminded INTEGER NOT NULL DEFAULT 0"
                    ))
                # 所属工作区(Space)列：与上面几列同批自愈——旧库(建于 space_id 引入之前)若没手动
                # 跑 ALTER，主 AI 每次拆任务/建专班的 INSERT 都写 space_id → UndefinedColumn、任务
                # 编排整块瘫痪。补列 + 补索引(与模型 index=True 对齐)。
                if "space_id" not in have:
                    conn.execute(text(
                        "ALTER TABLE cosmac_task "
                        "ADD COLUMN space_id VARCHAR(255) NOT NULL DEFAULT ''"
                    ))
                    conn.execute(text(
                        "CREATE INDEX IF NOT EXISTS ix_cosmac_task_space_id "
                        "ON cosmac_task (space_id)"
                    ))
        # 订单表补列：旧生产库的 cosmac_order 建于 Token 经济之前，没 kind/tokens 两列——
        # 不补的话 token 充值下单 INSERT 直接 UndefinedColumn；历史会员单按默认 kind='member' 归类。
        if insp.has_table(Order.__tablename__):
            have = {c["name"] for c in insp.get_columns(Order.__tablename__)}
            with engine.begin() as conn:
                if "kind" not in have:
                    conn.execute(text(
                        "ALTER TABLE cosmac_order "
                        "ADD COLUMN kind VARCHAR(16) NOT NULL DEFAULT 'member'"
                    ))
                if "tokens" not in have:
                    conn.execute(text(
                        "ALTER TABLE cosmac_order "
                        "ADD COLUMN tokens BIGINT NOT NULL DEFAULT 0"
                    ))
        # 创作者上架表补列：1.6.1 建的生产库还没 review_reason（P3 上架审核的拒绝原因），
        # 不补的话审核拒绝写入报 UndefinedColumn。
        from cosmac.db.models import MarketListing as _ML
        if insp.has_table(_ML.__tablename__):
            have = {c["name"] for c in insp.get_columns(_ML.__tablename__)}
            with engine.begin() as conn:
                if "review_reason" not in have:
                    conn.execute(text(
                        "ALTER TABLE cosmac_market_listing "
                        "ADD COLUMN review_reason VARCHAR(500) NOT NULL DEFAULT ''"
                    ))
                # P4：Skill 也能上架（买断制）→ 需要 kind 区分；历史行都是 Agent 上架。
                if "kind" not in have:
                    conn.execute(text(
                        "ALTER TABLE cosmac_market_listing "
                        "ADD COLUMN kind VARCHAR(16) NOT NULL DEFAULT 'agent'"
                    ))
                    conn.execute(text(
                        "CREATE INDEX IF NOT EXISTS ix_cosmac_market_listing_kind "
                        "ON cosmac_market_listing (kind)"
                    ))
        # 图文页表补列：旧库的 cosmac_doc_page 还没 cover（封面图），补上否则带封面写入报
        # UndefinedColumn。
        if insp.has_table(DocPage.__tablename__):
            have = {c["name"] for c in insp.get_columns(DocPage.__tablename__)}
            with engine.begin() as conn:
                if "cover" not in have:
                    conn.execute(text(
                        "ALTER TABLE cosmac_doc_page "
                        "ADD COLUMN cover TEXT NOT NULL DEFAULT ''"
                    ))
                if "published" not in have:
                    # 旧库已有页面默认已发布，保持历史内容可见；新建页面由 ORM 默认草稿。
                    # 用 DEFAULT TRUE（Postgres 不接受 boolean 列用整数 1 作默认；SQLite 也支持 TRUE）。
                    conn.execute(text(
                        "ALTER TABLE cosmac_doc_page "
                        "ADD COLUMN published BOOLEAN NOT NULL DEFAULT TRUE"
                    ))
    except Exception:
        logger.warning("补齐业务表列失败（不致命，相关新功能可能降级）", exc_info=True)


def get_engine() -> Engine:
    """拿到当前 engine（没初始化就用默认配置懒初始化）。"""
    if _engine is None:
        init_engine()
    assert _engine is not None  # 给类型检查器看：init_engine 必然已赋值
    return _engine


def get_session() -> Session:
    """开一个新的 ORM 会话（用完记得 close；推荐用 ``session_scope()`` 自动管理）。"""
    if _Session is None:
        init_engine()
    assert _Session is not None
    return _Session()


@contextmanager
def session_scope() -> Iterator[Session]:
    """事务作用域：正常结束自动 commit，出异常自动 rollback，最后一定 close。

    用法：
        with session_scope() as s:
            s.add(obj)
        # 离开 with 块时已提交
    """
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
