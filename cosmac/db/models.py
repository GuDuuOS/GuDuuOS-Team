"""数据层 ORM 模型（SQLAlchemy 2.0 typed declarative）。

第一批表：**Skill**（技能定义）与 **Agent**（智能体定义）——模块2「群级 记忆/知识库/
Rule/Skill」最先要的两类结构化数据。知识库（pgvector）、群级记忆、Rule 是后续切片。

**作用域（scope）模型**：每条 Skill/Agent 都挂在一个作用域上，覆盖你提到的
「每账号配置 + 群级智能」两种需求：
    - ``user``   ：属于某个账号，scope_id = 用户 id（如 ``@alice:cosmac.cc``）
    - ``room``   ：属于某个群/频道，scope_id = room_id（群级技能/智能体）
    - ``global`` ：全平台共享，scope_id = ``""``
(scope, scope_id, slug) 三元组唯一——同一作用域内 slug 不重复，不同作用域可重名。
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# —— 作用域取值（别散落字符串字面量，统一引用这几个常量）——
SCOPE_USER = "user"
SCOPE_ROOM = "room"
SCOPE_GLOBAL = "global"


class Base(DeclarativeBase):
    """所有 cosmac 数据表的声明基类。"""


class TimestampMixin:
    """统一的「创建时间 / 更新时间」两列，给所有业务表复用。"""

    # 用 Python 端 default/onupdate（跨 SQLite/PG 行为一致），存 UTC。
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class Skill(Base, TimestampMixin):
    """技能定义：一段可复用的能力/提示，挂在某账号或某群下，供主 AID 调度时启用。

    字段：
        scope/scope_id: 作用域（见模块 docstring）。
        slug:           作用域内唯一的短标识（如 ``weekly-report``），程序按它引用。
        name:           展示名（给人看）。
        description:    一句话说明这个技能干嘛。
        instructions:   技能正文——喂给大模型的提示/步骤说明，可以较长。
        enabled:        是否启用（停用而不删除，保留历史）。
    """

    __tablename__ = "cosmac_skill"
    __table_args__ = (
        UniqueConstraint("scope", "scope_id", "slug", name="uq_skill_scope_slug"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default=SCOPE_GLOBAL)
    scope_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    instructions: Mapped[str] = mapped_column(Text, nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:  # 方便日志/调试
        return f"<Skill {self.scope}:{self.scope_id or '*'}/{self.slug}>"


class Agent(Base, TimestampMixin):
    """智能体定义：一个带人设的 AI 角色，可绑定若干技能，挂在某账号或某群下。

    字段：
        scope/scope_id: 作用域（见模块 docstring）。
        slug:           作用域内唯一短标识。
        name:           展示名。
        description:    一句话说明。
        system_prompt:  人设/系统提示。
        model:          模型覆盖（空 = 跟随全局 AI 配置；非空 = 这个 Agent 单独用某模型）。
        skill_slugs:    绑定的技能 slug 列表（JSON）。先用列表简化，避免一上来就建多对多
                        关联表；以后真有「跨作用域共享技能」需求再升级成关联表。
        enabled:        是否启用。
    """

    __tablename__ = "cosmac_agent"
    __table_args__ = (
        UniqueConstraint("scope", "scope_id", "slug", name="uq_agent_scope_slug"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default=SCOPE_GLOBAL)
    scope_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    skill_slugs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:
        return f"<Agent {self.scope}:{self.scope_id or '*'}/{self.slug}>"


class KnowledgeDoc(Base, TimestampMixin):
    """知识库里的一篇文档（入库后被切成若干 KnowledgeChunk 做向量检索）。

    挂在作用域上（room=本群知识库 / user=个人 / global=全平台）。
    source 记来源（文件名/URL/"chat"等），便于回溯与去重。
    """

    __tablename__ = "cosmac_kb_doc"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default=SCOPE_ROOM)
    scope_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    source: Mapped[str] = mapped_column(String(512), nullable=False, default="")

    chunks: Mapped[List["KnowledgeChunk"]] = relationship(
        "KnowledgeChunk",
        back_populates="doc",
        cascade="all, delete-orphan",  # 删文档连带删它的分块
        order_by="KnowledgeChunk.ordinal",
    )

    def __repr__(self) -> str:
        return f"<KnowledgeDoc {self.scope}:{self.scope_id or '*'} #{self.id} {self.title!r}>"


class KnowledgeChunk(Base):
    """文档分块 + 它的向量表示。

    embedding 存成 JSON 浮点数组——**跨 SQLite/PG 通用**；v1 检索在 Python 里算余弦
    相似度（两种后端都能跑）。规模化后可在 Postgres 上换成 pgvector 列 + 近邻索引
    （见 CLAUDE.md §3：pgvector 是 Postgres 专属，缺它时优雅降级）。
    冗余存 scope/scope_id：检索时可直接按作用域过滤分块，不必每次 join 文档。
    """

    __tablename__ = "cosmac_kb_chunk"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_id: Mapped[int] = mapped_column(
        ForeignKey("cosmac_kb_doc.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default=SCOPE_ROOM)
    scope_id: Mapped[str] = mapped_column(String(255), nullable=False, default="", index=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 在文档内的次序
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    embedding: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # 向量空间标识（embedder.tag，如 "hash:256"/"oai:openai:text-embedding-3-small"）。
    # 检索只比**同 tag** 的分块——换 embedder 后旧向量不会再混进来产生乱序/失真结果。
    embed_tag: Mapped[str] = mapped_column(
        String(64), nullable=False, default="", index=True
    )

    doc: Mapped["KnowledgeDoc"] = relationship("KnowledgeDoc", back_populates="chunks")

    def __repr__(self) -> str:
        return f"<KnowledgeChunk doc={self.doc_id} #{self.ordinal}>"


class WorkflowRun(Base, TimestampMixin):
    """一次外部工作流连接器的运行记录（模块3）。

    连接器**定义**走控制室 state event（后台编排，浏览器够不到 DB）；这里只存**运行记录**
    （派生/关系型数据，可追溯）。room_id/sender 记触发来源；status=ok/error。
    """

    __tablename__ = "cosmac_workflow_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False, default="webhook")
    room_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    sender: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    input: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # status: ok / error / queued（等待本机worker）/ pending（已开始外呼）/ processing（处理回调）
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")
    output: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 异步回调的一次性令牌：平台带它回调，bot 据此校验；queued/pending/processing 期间保留。
    token: Mapped[str] = mapped_column(String(64), nullable=False, default="", index=True)
    # 来源事件幂等键：Matrix 同一 event/命令重放时复用同一运行记录，避免外部平台重复接单。
    # 旧的同步运行记录没有这个键，所以允许 NULL；有值时由代码按它查重。
    source_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)

    def __repr__(self) -> str:
        return f"<WorkflowRun {self.slug} {self.status} #{self.id}>"


class SeenTxn(Base, TimestampMixin):
    """appservice 事务的**处理状态**，用于原子去重 + 崩溃恢复（#2/#3）。

    内存去重重启即丢、且无界增长；这里持久化处理状态，重启后 Synapse 重放也能识别。
    两阶段抢占（见 db/dedup.py）：
      - 新事务：原子 INSERT 一行（``done=False``、``claimed_at=now``）占住处理权；
        主键冲突 = 已有人在处理/已处理，绝不重复触发付费工作流。
      - ``done=True``：已处理完，重放直接跳过。
      - ``done=False`` 且 ``claimed_at`` 过期：上次处理中途崩了的残留，可被原子重新抢占
        （at-least-once，避免"先标记后处理"在崩溃时永久丢一整批事务）。
    旧记录按时间清理控制表大小。
    """

    __tablename__ = "cosmac_seen_txn"

    txn_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    # 是否处理完成。False=抢占中(processing)；True=已完成(done)
    done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 最近一次抢占时间——判断 processing 是否为"崩溃残留"(过期可重抢)的依据
    claimed_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )


class Order(Base, TimestampMixin):
    """一笔会员购买订单（模块4 交易系统）。

    会员**套餐定义**走控制室 state event（`cosmac.plans`，后台配）；这里只存**订单**这种
    关系型、要对账、要审计的交易数据。下单即建一行(status=created)，支付平台 webhook 验签
    成功后置 paid 并据 ``period_days`` 给用户开/续会员（写 ``cosmac.member`` state event）。

    幂等：``order_no`` 唯一；webhook 可能重复回调，靠 status 的原子 CAS(created→paid)保证
    只开通一次会员（见 db/order_repo.mark_paid）。金额用**最小货币单位整数**(分/cent)，不用浮点。
    """

    __tablename__ = "cosmac_order"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 对外订单号（唯一）；也用作支付平台回调里定位订单的业务标识
    order_no: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # 下单时对套餐的快照（套餐定义以后可能改，订单要记下"当时买的是什么"）
    plan_slug: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    tier: Mapped[str] = mapped_column(String(16), nullable=False, default="paid")
    period_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="usd")
    # 支付渠道（manual/stripe/paypal/usdt/alipay/wechat）+ 渠道侧引用 id（session/intent/txhash）
    provider: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    provider_ref: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # created（已下单待支付）/ paid（已支付已开通）/ failed / canceled / refunded
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="created", index=True)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # 支付成功后实际给会员开到的到期 unix 秒（审计：这笔订单把会员续到了哪天）
    granted_expires_ts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<Order {self.order_no} {self.status} {self.user_id} {self.tier}>"


class Task(Base, TimestampMixin):
    """AI 任务编排的一条子任务（任务看板用）。

    主 AI 把一个目标拆成若干子任务、每条指定负责人，写进这张表；任务看板读它做看板展示。
    后续(P2)再加"派发执行"(发频道/交AI/跑工作流)与"结果回填"，那时会用到 dispatch/result 字段。
    """

    __tablename__ = "cosmac_task"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 这批子任务所属的总目标原文（便于分组/溯源"这是哪次下达拆出来的"）
    goal: Mapped[str] = mapped_column(Text, nullable=False, default="")
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 负责人（人类可读标签，给看板展示）：人名/角色/@某人/某智能体，AI 拆解时填。
    assignee: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # 类型化执行者（模块3.5 档2：让任务真的能"派"出去）——主AI 读能力名册后填：
    #   executor_kind: human(派给真人) / agent(交 AI Agent) / workflow(跑工作流) / none(暂不指派)
    #   executor_ref:  对应的 @user_id / agent-slug / workflow-slug（none 时为空）
    # 档3 的"建专班/派发"与档4 的"回填"据这两列把活路由到正确的执行者。
    executor_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="none")
    executor_ref: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # todo（待办）/ doing（进行中）/ done（已完成）；进度 0-100
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="todo", index=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 执行结果/进展说明（P2 由 AI/工作流回填；P1 可人工备注）
    result: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 上下文：拆解发生的房间（bot DM / 频道）与下达人，便于以后派发回到正确地方
    room_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    sender: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<Task #{self.id} {self.status} {self.title[:20]!r}>"


class ConversationMemory(Base, TimestampMixin):
    """群级长期记忆：一份**滚动摘要**，让主 AI 记得超出短期窗口（最近 N 条）的对话要点。

    为什么要它：短期记忆只读房间最近 ~12 条，跨多轮/跨天的事 AI 就"忘了"。这里存一份
    定期由 LLM 重写的摘要——每轮回复读它注入 system（AI 就"记得"），每 K 轮后台重摘要一次。
    **派生数据**：原始聊天记录在 Synapse（不重存，见 CLAUDE.md §3），这里只存摘要。
    作用域：room=本群/DM 的长期记忆（scope_id=room_id）；一个房间一条（唯一）。
    """

    __tablename__ = "cosmac_conversation_memory"
    __table_args__ = (
        UniqueConstraint("scope", "scope_id", name="uq_convmem_scope"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default=SCOPE_ROOM)
    scope_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # 当前生效的长期记忆摘要文本（每轮注入 system；空=还没攒够内容）
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 自上次摘要以来累计的回复轮数；达到阈值就触发后台重摘要并清零
    turns_since_summary: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 累计回复轮数（单调递增，仅调试/审计用）
    total_turns: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<ConversationMemory {self.scope}:{self.scope_id} turns={self.total_turns}>"


class PersonProfile(Base, TimestampMixin):
    """个人维护的「协作人能力名册」（模块3.5：普通用户给 TA 认识的人加能力备注）。

    与 admin 的**全局**名册（控制室 `cosmac.people` state event）互补：普通用户够不到控制室，
    所以存 cosmac DB，按 ``owner``（谁加的 = 下达目标的用户）隔离。主AI 给某用户拆任务时，
    把全局名册 + 该用户的这份个人名册**合并**，据此匹配执行者。
    (owner, person_id) 唯一——同一用户对同一个人只一条画像。
    """

    __tablename__ = "cosmac_person"
    __table_args__ = (
        UniqueConstraint("owner", "person_id", name="uq_person_owner_pid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    person_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    role: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    expertise: Mapped[str] = mapped_column(Text, nullable=False, default="")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:
        return f"<PersonProfile {self.owner}→{self.person_id}>"


class ProjectArchive(Base, TimestampMixin):
    """专班归档记录（模块3.5 收尾）：专班所有任务完成后，把成果存成一条记录。

    存下来后就能**清掉该频道的 AI 长期记忆**（不浪费 Agent 记忆）、提示用户关闭频道——
    项目复盘/审计仍可查这条归档。goal=总目标，summary=收尾摘要，tasks=任务快照(JSON)。
    """

    __tablename__ = "cosmac_project_archive"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    room_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    goal: Mapped[str] = mapped_column(Text, nullable=False, default="")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tasks: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    done_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    archived_by: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<ProjectArchive {self.room_id} {self.done_count}/{self.total_count}>"


class UsageCounter(Base, TimestampMixin):
    """用量计数（模块4 变现第二步）：按 用户 + 计量项 + 周期键 累计用量。

    rate 类指标（如每天 AI 对话）周期键 = 日期/月份字符串，每次动作 +1；配额满则拦并提示升级。
    total 类指标（如知识库文档数）不走这张表——直接数现有实体行（见各处 count）。
    (user_id, metric, period_key) 唯一。
    """

    __tablename__ = "cosmac_usage"
    __table_args__ = (
        UniqueConstraint("user_id", "metric", "period_key", name="uq_usage"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    metric: Mapped[str] = mapped_column(String(64), nullable=False)
    period_key: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<UsageCounter {self.user_id} {self.metric}@{self.period_key}={self.count}>"


class RegisteredEmail(Base, TimestampMixin):
    """注册时把「邮箱 ↔ 用户名」存一份，给「找回密码」按邮箱定位账号用。

    为什么单独存：我们用自建验证码注册，建号时没把邮箱绑成 Matrix 3pid；找回密码要
    「邮箱 → 用户名」反查，故在 cosmac DB 留这份映射。一个邮箱对一个账号（唯一）。
    （老账号注册时没存这条 → 暂不能用邮箱找回；目前账号极少，可接受。）
    """

    __tablename__ = "cosmac_registered_email"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 邮箱（小写存），唯一——一个邮箱只绑一个账号
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    # Matrix 用户名 localpart（如 alice，不含 @域名）
    username: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<RegisteredEmail {self.email} -> {self.username}>"


class AuthEvent(Base, TimestampMixin):
    """认证审计事件（登录/注册/找回密码的每次尝试）——安全增强阶段0 的地基。

    为什么要它：登录一旦收口到后端，我们就能记下"谁 / 何时 / 什么 IP / 成功还是失败"，
    这是后续"异地登录检测 / 可疑登录二次验证 / 防批量注册"的数据来源。派生审计数据、
    与 Synapse 原始账号数据分开存（符合 CLAUDE.md 存储分层：AI/安全层自己的结构化数据进 cosmac DB）。
    只存**判定所需**的最小字段，绝不存密码/验证码/token。
    """

    __tablename__ = "cosmac_auth_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 事件类型：login（登录）/ register（注册）/ reset（找回密码）。
    kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    # 主体：登录/注册用 username localpart；邮箱相关用邮箱（小写）。仅用于按主体聚合，不含敏感。
    subject: Mapped[str] = mapped_column(String(320), nullable=False, default="", index=True)
    # 客户端 IP（经收口后由后端可信取得；异地检测的关键维度）。
    ip: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # 是否成功。失败也要记——爆破/异常尝试正是要看的。
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 简短事由（如 "bad_password" / "rate_limited" / "ok"）——排查用，不含明文凭据。
    detail: Mapped[str] = mapped_column(String(128), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<AuthEvent {self.kind} {self.subject} ok={self.ok}>"


class DocPage(Base, TimestampMixin):
    """文档教学频道（类云文档）的一个**页面**。

    一个「文档频道」= 一个 Matrix 房间(room_id)，里面是一棵可多层嵌套的页面树（类 Notion）。
    页面正文是 Markdown，存这里（cosmac DB）——state event 存不下大文档也搜不了，且要喂给
    知识库做 AI 答疑（见 CLAUDE.md 数据分层表「派生/结构化数据进 cosmac DB」）。

    作用域/权限不在这层判：读=房间成员、写=房间 power≥50，由 bot HTTP 端点服务端强制
    （复用任务看板那套 is_joined_member / 房间 power 校验）。频道"是不是文档频道"的类型标记
    放 Matrix 的 cosmac.channel_config.kind='doc'（前端不查 DB 就知道怎么渲染）。
    """

    __tablename__ = "cosmac_doc_page"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 所属文档频道（Matrix room_id）。一个房间一棵页面树。
    room_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # 父页面 id；None/0 = 顶层页面。靠它+sort 组成多层嵌套树。
    parent_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 封面图（类公众号文章封面）：存 mxc://(上传到 Matrix 媒体库)或 http(s) URL；空=无封面。
    cover: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 是否已发布：新建默认草稿(False)，发布后才在前台展示、才进 AI 知识库。
    # （旧库补列时 DEFAULT 1，让历史页面保持可见——见 engine._heal_business_schema。）
    published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 正文（Markdown）。可较长，故用 Text。
    content_md: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 同层排序（小在前）；移动/拖拽时重排。
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 最后修改人（@user_id），便于展示/审计。
    updated_by: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<DocPage #{self.id} room={self.room_id} {self.title[:20]!r}>"


class UserProfile(Base, TimestampMixin):
    """用户给主 AI 的「个人偏好画像」（About me / Outputs）—— 每个用户自己设置。

    解决的问题：主 AI 的「人设」是 AI 端的设定（控制室/群级 Agent），而这张表是**人端**的
    设定——「我是谁、我希望 AI 怎么回答我」。主 AI 在每次对话拼 system prompt 时，把当前
    发起人的这份画像注入进去（放在平台规则/人设/任务RULE **之后**，优先级最低、只影响表达
    方式，不得违反上述任何硬约束，见 appservice_bot._user_profile_text）。

    为什么进 cosmac DB 而不是 per-user account data：bot 需要**读到别人的**画像才能注入，而
    Matrix per-user account data 是用户私有、appservice 读不到他人的；故走「浏览器够不到 DB →
    经 bot HTTP 端点(/cosmac/profile/me) 写、bot 直接读 DB」这套（与个人协作人名册同套路）。
    跟人走（全局生效、在哪个群都带），与群级 Agent（跟群走）正交互补。
    user_id 唯一——一个账号一条画像。
    """

    __tablename__ = "cosmac_user_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 账号（@user:domain），唯一——一个用户一条
    user_id: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )
    # About me：我是谁（背景/职业/正在做的事），给 AI 当对话上下文
    about: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Outputs：希望 AI 怎么回答（语气/长度/语言/格式偏好）
    style: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 自由补充
    extra: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 总开关：关掉就不注入（保留内容、临时停用），默认开
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:
        return f"<UserProfile {self.user_id}>"


class UserTemplate(Base, TimestampMixin):
    """「用户 ↔ 入驻模板」映射:注册引导选了哪个模板(cosmac.onboarding_templates 的 slug)。

    资源级权限(技能/智能体的「可用范围」)据此判定"指定模板可用"的资源对谁开放。
    引导完成时由 bot 端点写入(前端对控制室无写权限,account data bot 又读不到,故落 DB)。
    一个用户一条;换模板(将来支持的话)就地覆盖。
    """

    __tablename__ = "cosmac_user_template"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 账号（@user:domain），唯一——一个用户一条
    user_id: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )
    # 入驻模板 slug（cosmac.onboarding_templates 里的 key）
    template_slug: Mapped[str] = mapped_column(String(128), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<UserTemplate {self.user_id} -> {self.template_slug}>"


class Employee(Base, TimestampMixin):
    """员工花名册（人事 / HR 数据）：企业「数据智能」演示与人事问答的底表。

    背景：主 AI 需要能回答「谁在哪个部门」「本月入职几人」「哪个部门薪资最高」
    「谁绩效最好」「谁本月请假最多」这类**人事问题**。这些是结构化的派生业务数据，
    Matrix / Synapse 存不下也搜不了，按 §3 数据分层落到 cosmac 自己的 DB（本表）。

    设计取舍（面向演示，够用即止）：
    - **一张宽表**装下花名册 + 部门 + 薪酬 + 绩效 + 考勤，AI 一次查询即可综合分析，
      不拆多表连接（演示规模 ~50 人，宽表最省事、SQL 聚合也直观）。
    - **日期用字符串 ``YYYY-MM-DD``**：跨 SQLite（本地）/ Postgres（生产）行为一致，
      按月聚合取前 7 位前缀即可（``hire_date[:7]``），免去 Date 类型与解析的跨库差异。
    - **薪资用整数（月薪·元）**：避免 Float/Numeric 的跨库精度问题；聚合直接求和/均值。
    - ``emp_no`` 工号全局唯一——seed 重跑时按工号 upsert，不产生重复人。
    """

    __tablename__ = "cosmac_employee"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 工号（如 ``C1024``）——业务主键，唯一；seed/导入按它去重
    emp_no: Mapped[str] = mapped_column(
        String(32), nullable=False, unique=True, index=True
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False, default="")  # 姓名
    gender: Mapped[str] = mapped_column(String(8), nullable=False, default="")  # 性别 男/女
    # 部门（如「研发部」）——查询/统计最常用的分组维度，建索引
    department: Mapped[str] = mapped_column(
        String(64), nullable=False, default="", index=True
    )
    title: Mapped[str] = mapped_column(String(64), nullable=False, default="")  # 职位（如「后端工程师」）
    level: Mapped[str] = mapped_column(String(16), nullable=False, default="")  # 职级（P4~P8 / M1~M3）
    manager: Mapped[str] = mapped_column(String(64), nullable=False, default="")  # 汇报对象（上级姓名）
    # 入职日期 YYYY-MM-DD；按月统计入职趋势取前缀
    hire_date: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    # 在职状态：active 在职 / probation 试用期 / resigned 离职
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", index=True
    )
    resign_date: Mapped[str] = mapped_column(String(10), nullable=False, default="")  # 离职日期（在职为空）
    city: Mapped[str] = mapped_column(String(32), nullable=False, default="")  # 工作城市
    salary: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 月薪（元）
    # 最近一次绩效评级：S（卓越）/ A（优秀）/ B（合格）/ C（待改进）
    perf_rating: Mapped[str] = mapped_column(String(4), nullable=False, default="")
    annual_leave_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 年假总额（天）
    annual_leave_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 已用年假（天）
    leave_days_month: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 本月请假（天）
    overtime_hours_month: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 本月加班（小时）
    education: Mapped[str] = mapped_column(String(16), nullable=False, default="")  # 学历
    birth_date: Mapped[str] = mapped_column(String(10), nullable=False, default="")  # 生日 YYYY-MM-DD
    email: Mapped[str] = mapped_column(String(128), nullable=False, default="")  # 企业邮箱
    phone: Mapped[str] = mapped_column(String(32), nullable=False, default="")  # 手机（脱敏）

    def __repr__(self) -> str:
        return f"<Employee {self.emp_no} {self.name}@{self.department}>"
