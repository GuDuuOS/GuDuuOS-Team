"""GuDuu Nexus 的独立数据库层。

⚠️ 与 cosmac 实例的 DB **完全隔离**（见 CLAUDE.md §3 存储表「OEM/Nexus 数据」行）：
Nexus 存的是母舰视角的舰队数据（KEY/实例/钱包/用量/心跳），部署在母舰侧自己的
Postgres；本地开发零基建回退 SQLite（与 cosmac/db 同一套路、同步 SQLAlchemy）。

连接配置：环境变量 ``NEXUS_DATABASE_URL``；未设置时回退 ``run/nexus.db``（SQLite）。
"""

from __future__ import annotations

import os
import time
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Column,
    Index,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


def _now_ms() -> int:
    """当前毫秒时间戳（全库统一用毫秒整数，避免时区/精度歧义）。"""
    return int(time.time() * 1000)


class NexusKey(Base):
    """OEM 授权码（KEY）。

    商业语义（模块6 拍板）：买断制、永久含升级；token 是另一本账（见钱包）。
    ``key_hash`` 是唯一存储形态——明文只在签发那一刻返回给管理员一次。
    """

    __tablename__ = "nexus_key"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # sha256 哈希（唯一索引：兑换/心跳/网关鉴权都拿哈希查这里）
    key_hash = Column(String(64), nullable=False, unique=True, index=True)
    # 明文的展示尾号（如 "G8H9"）：列表页辨认用，不构成安全风险
    key_tail = Column(String(8), nullable=False, default="")
    # active=可用 / revoked=已吊销（吊销后兑换与网关鉴权立即失效）
    status = Column(String(16), nullable=False, default="active")
    # 商务备注（卖给了谁、订单号等，管理员自己填）
    note = Column(Text, nullable=False, default="")
    # 随 KEY 附赠的初始 token 额度（兑换建实例时注入钱包）
    token_grant = Column(BigInteger, nullable=False, default=0)
    created_ts = Column(BigInteger, nullable=False, default=_now_ms)
    # 兑换信息：绑定的实例 id（一把 KEY 只对应一个实例；重装同域名幂等）
    instance_id = Column(Integer, nullable=True, default=None)
    redeemed_ts = Column(BigInteger, nullable=True, default=None)


class NexusInstance(Base):
    """一个已兑换开通的 OEM 实例（= 一套自部的 GuDuu OS 发行版）。"""

    __tablename__ = "nexus_instance"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 实例域名（server_name，即 OEM 品牌身份）。唯一：一个域名只能被兑换一次
    domain = Column(String(255), nullable=False, unique=True, index=True)
    admin_email = Column(String(255), nullable=False, default="")
    key_id = Column(Integer, nullable=False, index=True)
    created_ts = Column(BigInteger, nullable=False, default=_now_ms)
    # 心跳快照：最近一次上报时间/版本/统计（原样 JSON 文本，大屏直接读）
    last_seen_ts = Column(BigInteger, nullable=True, default=None)
    version = Column(String(64), nullable=False, default="")
    stats_json = Column(Text, nullable=False, default="{}")
    # active=正常 / suspended=停用（P2 起网关据此断供）
    status = Column(String(16), nullable=False, default="active")


class NexusWallet(Base):
    """实例的 token 钱包——唯一续费抓手（余额耗尽 → 网关断 AI）。

    余额单位：token（与网关计量同单位）。所有加减必须走 fleet.topup/debit，
    禁止业务代码直接改 balance（保证有流水可对账）。
    """

    __tablename__ = "nexus_wallet"

    instance_id = Column(Integer, primary_key=True)
    balance_tokens = Column(BigInteger, nullable=False, default=0)
    updated_ts = Column(BigInteger, nullable=False, default=_now_ms)


class NexusLedger(Base):
    """钱包流水（充值/扣费都记一行，对账与大屏消耗曲线的数据源）。"""

    __tablename__ = "nexus_ledger"

    id = Column(Integer, primary_key=True, autoincrement=True)
    instance_id = Column(Integer, nullable=False, index=True)
    ts = Column(BigInteger, nullable=False, default=_now_ms, index=True)
    # 正数=充值(topup)，负数=消耗(usage)
    delta_tokens = Column(BigInteger, nullable=False)
    # topup / usage / grant(兑换初始额度) / adjust(人工调整)
    kind = Column(String(16), nullable=False)
    # 备注：充值订单号 / 网关请求摘要(provider+model)等
    note = Column(Text, nullable=False, default="")


class NexusHeartbeat(Base):
    """心跳历史（每次上报存一行；大屏增长曲线/在线判定的数据源）。

    量级估算：上百实例 × 每 10 分钟一跳 ≈ 每天 1.5 万行，量小；先不做保留期
    清理，P2 大屏落地时按需加（与 cosmac AuthEvent 90 天保留的欠账同批）。
    """

    __tablename__ = "nexus_heartbeat"

    id = Column(Integer, primary_key=True, autoincrement=True)
    instance_id = Column(Integer, nullable=False, index=True)
    ts = Column(BigInteger, nullable=False, default=_now_ms, index=True)
    version = Column(String(64), nullable=False, default="")
    stats_json = Column(Text, nullable=False, default="{}")


# 组合索引：按实例翻流水/心跳是最高频查询
Index("ix_nexus_ledger_inst_ts", NexusLedger.instance_id, NexusLedger.ts)
Index("ix_nexus_hb_inst_ts", NexusHeartbeat.instance_id, NexusHeartbeat.ts)

# —— 引擎/会话（模块级单例；init_engine 幂等，测试可传显式 URL 拿独立库）——
_engine = None
_Session: Optional[sessionmaker] = None


def default_url() -> str:
    """解析数据库连接串：env NEXUS_DATABASE_URL → 本地 SQLite 兜底。"""
    url = os.environ.get("NEXUS_DATABASE_URL", "").strip()
    if url:
        return url
    # 本地开发：项目根 run/nexus.db（与 cosmac 的 run/cosmac.db 并排，互不相干）
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    run_dir = os.path.join(root, "run")
    os.makedirs(run_dir, exist_ok=True)
    return "sqlite:///" + os.path.join(run_dir, "nexus.db")


def init_engine(url: str = ""):
    """初始化（或复用）引擎并建表。测试传入独立 URL（如 sqlite:///:memory:）。"""
    global _engine, _Session
    if _engine is not None and not url:
        return _engine
    resolved = url or default_url()
    _engine = create_engine(resolved, future=True)
    Base.metadata.create_all(_engine)
    _Session = sessionmaker(bind=_engine, future=True)
    return _engine


def session():
    """开一个新 Session（调用方负责 with 收尾）。须先 init_engine。"""
    if _Session is None:
        init_engine()
    assert _Session is not None
    return _Session()
