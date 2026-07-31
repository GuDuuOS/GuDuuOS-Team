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
    Float,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
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


class NexusOem(Base):
    """OEM 客户账号（模块6 P1：邮箱+密码独立账号，可拥有多个 KEY/实例）。

    与「平台超管」正交——超管走 NEXUS_ADMIN_TOKEN（看全部、签发 KEY、充值）；
    OEM 登录后只能看/操作自己认领的 KEY 及其实例（服务端强制分权，见 oem.py）。
    密码只存 pbkdf2 派生串（``pbkdf2$迭代$salt$hash``），绝不存明文。
    """

    __tablename__ = "nexus_oem"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)
    name = Column(String(120), nullable=False, default="")
    # active=正常 / disabled=被平台停用（停用后不能登录）
    status = Column(String(16), nullable=False, default="active")
    created_ts = Column(BigInteger, nullable=False, default=_now_ms)


class NexusSession(Base):
    """OEM 登录会话（可撤销）。库里只存 token 的 sha256，明文只在登录响应里给一次。"""

    __tablename__ = "nexus_session"

    # sha256(token) 作主键：查会话/登出都拿哈希比对
    token_hash = Column(String(64), primary_key=True)
    oem_id = Column(Integer, nullable=False, index=True)
    created_ts = Column(BigInteger, nullable=False, default=_now_ms)
    expires_ts = Column(BigInteger, nullable=False)


class NexusSetting(Base):
    """母舰级键值配置（首个用户：商品定价 pricing）。

    为什么不用 env：定价要超管在控制台随时改、改了立即生效，env 改一次要
    登服务器重启——运营动作必须进 DB。v 存 JSON 文本。
    """

    __tablename__ = "nexus_setting"

    k = Column(String(64), primary_key=True)
    v = Column(Text, nullable=False, default="{}")
    updated_ts = Column(BigInteger, nullable=False, default=_now_ms)


class NexusOrder(Base):
    """支付订单（模块6 P3：KEY 在线购买 / token 在线充值）。

    渠道范围包括国内支付宝/微信，以及海外 Stripe/PayPal/USDT；真实渠道 API
    未联调前只保留渠道骨架与总览状态，先用 mock 通道验证订单履约闭环。
    现阶段已落地订单金额仍为人民币**分**（整数，杜绝浮点）；海外真实收款开工时
    必须先补 currency/原币金额/结算金额字段，禁止把 USD 或 USDT 冒充人民币汇总。
    """

    __tablename__ = "nexus_order"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 商户订单号（我们生成，传给支付渠道；回调按它定位订单）
    order_no = Column(String(40), nullable=False, unique=True, index=True)
    oem_id = Column(Integer, nullable=False, index=True)
    # key=买断授权码 / topup=token 充值
    kind = Column(String(16), nullable=False)
    # 充值目标实例（kind=topup 时必填；kind=key 为空）
    instance_id = Column(Integer, nullable=True, default=None)
    # alipay / wechat / stripe / paypal / usdt / mock；mock 仅开发环境可用
    channel = Column(String(16), nullable=False)
    amount_cents = Column(BigInteger, nullable=False)
    # 本单对应的 token 量（key=附赠额度；topup=充值额度）
    tokens = Column(BigInteger, nullable=False, default=0)
    # pending=待支付 / paid=已支付（业务已履约）/ closed=关闭
    status = Column(String(16), nullable=False, default="pending")
    # kind=key 履约后：签发的 KEY 与交付明文（与申请单同策略：装机兑换后清空）
    key_id = Column(Integer, nullable=True, default=None)
    key_plain = Column(String(64), nullable=False, default="")
    # 渠道流水号（支付回调带回，对账用）
    provider_txn = Column(String(128), nullable=False, default="")
    created_ts = Column(BigInteger, nullable=False, default=_now_ms)
    paid_ts = Column(BigInteger, nullable=True, default=None)


class NexusManualTransfer(Base):
    """超级管理员登记的企业银行转账收款单。

    企业转账不是微信/支付宝回调，也不能复用仅供开发联调的 ``manual`` 渠道。
    它有自己稳定的 ``BT`` 单号、必传凭证和人工确认语义。金额保留明文整数用于财务
    聚合；付款企业、银行账号、AI 识别结果及凭证图片都用 ``NEXUS_SECRET_KEY``
    加密，避免数据库备份或只读查询意外暴露银行信息。
    """

    __tablename__ = "nexus_manual_transfer"

    id = Column(Integer, primary_key=True, autoincrement=True)
    transfer_no = Column(String(40), nullable=False, unique=True, index=True)
    # 可选关联 OEM；线下商务款可能先到账、后建客户，因此允许为空。
    oem_id = Column(Integer, nullable=True, default=None, index=True)
    # 当前人工企业转账只收人民币；和现有在线订单一致，以分为单位杜绝浮点误差。
    currency = Column(String(8), nullable=False, default="CNY")
    amount_cents = Column(BigInteger, nullable=False)
    # confirmed=超管已核实银行到账。未来若开放 OEM 自助上传，再增加 pending_review。
    status = Column(String(24), nullable=False, default="confirmed", index=True)
    purpose = Column(String(255), nullable=False, default="企业转账收款")
    # 结构化详情（付款/收款企业、账号、银行、流水号、时间、备注、AI 结果）加密保存。
    encrypted_details = Column(LargeBinary, nullable=False)
    voucher_filename = Column(String(255), nullable=False)
    voucher_content_type = Column(String(64), nullable=False)
    voucher_size = Column(BigInteger, nullable=False)
    voucher_sha256 = Column(String(64), nullable=False, index=True)
    encrypted_voucher = Column(LargeBinary, nullable=False)
    # not_run / recognized / failed；状态不含银行信息，可以明文用于运营筛选。
    recognition_status = Column(String(24), nullable=False, default="not_run")
    created_ts = Column(BigInteger, nullable=False, default=_now_ms, index=True)
    confirmed_ts = Column(BigInteger, nullable=False, default=_now_ms)


class NexusPaymentConfig(Base):
    """支付渠道的服务端加密配置与最近验证状态。

    为什么单开表：项目目前用 ``create_all`` 管理结构，新表能在现有 PostgreSQL 上
    无损创建；给旧表加列则不会自动 ALTER。``encrypted_config`` 只保存由
    ``NEXUS_SECRET_KEY`` 加密后的 JSON，管理员 API 永远不能把它原样返回浏览器。

    ``verify_status`` 只描述凭据检查结果，不代表渠道已经完成下单、回调、退款和对账
    联调。真实交易是否开放由支付 adapter 独立控制，避免“填过 Key”被误当成可收款。
    """

    __tablename__ = "nexus_payment_config"

    # alipay / wechat / stripe / paypal / usdt；一渠道只保留一份当前配置。
    provider = Column(String(24), primary_key=True)
    encrypted_config = Column(LargeBinary, nullable=False)
    # not_checked / remote_verified / local_valid / verification_failed
    verify_status = Column(String(32), nullable=False, default="not_checked")
    # 只保存经过我们归一化的安全摘要，不能落上游原始响应或密钥内容。
    verify_message = Column(String(255), nullable=False, default="")
    last_checked_ts = Column(BigInteger, nullable=True, default=None)
    updated_ts = Column(BigInteger, nullable=False, default=_now_ms)


class NexusOemProfile(Base):
    """OEM 客户档案（注册强制采集：企业/联系人/联系方式；超管详情页数据源）。

    单开表而非给 nexus_oem 加列（无迁移框架，同 NexusKeyClaim 的理由）。
    历史账号可能没有档案行——超管界面显示"未补录"。
    """

    __tablename__ = "nexus_oem_profile"

    oem_id = Column(Integer, primary_key=True)  # = NexusOem.id
    company = Column(String(160), nullable=False, default="")
    contact_name = Column(String(80), nullable=False, default="")
    # 联系方式：手机号/微信号/邮箱都接受，字符串不做强格式（跨国客户格式各异）
    phone = Column(String(60), nullable=False, default="")
    # 超管备注（谈判进展/特殊约定等，客户不可见）
    admin_note = Column(Text, nullable=False, default="")
    updated_ts = Column(BigInteger, nullable=False, default=_now_ms)


class NexusOemFile(Base):
    """OEM 客户附件（合同等）。二进制直接进 DB——量级小（上百客户×几份 PDF），
    换来单一 DB 备份即全量、零磁盘路径/权限运维。单文件上限见 service 层(20MB)。"""

    __tablename__ = "nexus_oem_file"

    id = Column(Integer, primary_key=True, autoincrement=True)
    oem_id = Column(Integer, nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    content_type = Column(String(120), nullable=False, default="application/octet-stream")
    size = Column(BigInteger, nullable=False, default=0)
    data = Column(LargeBinary, nullable=False)
    uploaded_ts = Column(BigInteger, nullable=False, default=_now_ms)


class NexusOemInvite(Base):
    """OEM 邀请关系边（分销层级树，大屏"星球图"的数据源）。

    一个 OEM 恰有一条入边（注册时强制填邀请人，填错不给注册）：
      - inviter_id = 某 OEM 账号 id → 该 OEM 是其"下线"；
      - inviter_id = NULL → 平台直属（注册时填官方邀请码 GUDUU），树根挂平台。
    单开一张表而非在 nexus_oem 上加列：无迁移框架，新表 create_all 自动建，
    旧表加列不会自动 ALTER（与 NexusKeyClaim 同理）。
    """

    __tablename__ = "nexus_oem_invite"

    oem_id = Column(Integer, primary_key=True)  # = NexusOem.id
    inviter_id = Column(Integer, nullable=True, default=None, index=True)
    created_ts = Column(BigInteger, nullable=False, default=_now_ms)


class NexusOemShare(Base):
    """OEM 稳定分享码（一家一个，普通用户与下级 OEM 邀请共用）。

    分享码不是登录凭证，只承担“这次注册由谁邀请”的不可猜测标识。使用随机码而非
    OEM id/邮箱，避免公开链接暴露内部编号或客户邮箱；码生成后保持稳定，已印刷的二维码
    不会因门户刷新而失效。
    """

    __tablename__ = "nexus_oem_share"

    oem_id = Column(Integer, primary_key=True)  # = NexusOem.id
    code = Column(String(32), nullable=False, unique=True, index=True)
    created_ts = Column(BigInteger, nullable=False, default=_now_ms)


class NexusUserAttribution(Base):
    """普通用户到直属 OEM 的归属边（母舰只存关系，不存密码、验证码或聊天内容）。

    ``instance_id + user_id`` 唯一，保证一个具体 Matrix 账号只会首次挂靠一次；
    ``oem_id`` 保存直属 OEM，完整祖先链通过 ``NexusOemInvite`` 动态计算。这样 OEM
    层级以后扩展到任意深度也不用复制/改写每个用户的祖先数组。
    """

    __tablename__ = "nexus_user_attribution"
    __table_args__ = (
        UniqueConstraint("instance_id", "user_id", name="uq_nexus_user_instance"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    instance_id = Column(Integer, nullable=False, index=True)
    oem_id = Column(Integer, nullable=False, index=True)
    user_id = Column(String(255), nullable=False)
    referral_code = Column(String(32), nullable=False, default="")
    created_ts = Column(BigInteger, nullable=False, default=_now_ms)


class NexusKeyRequest(Base):
    """OEM 的授权码申请单（P1 手动闭环：申请→超管签发→门户交付明文）。

    明文交付策略（负责人"够用即止"原则下的务实解）：
      - 批准时把新 KEY 的明文存进 ``key_plain``，申请人登录门户即可看到并复制
        （这就是交付通道，替代邮件/微信人肉传码）；
      - 实例**兑换成功后自动清空** key_plain（装机后明文再无保存价值）；
      - 拖库风险窗口 = 「已签发未装机」的码，且每码只绑定一个 OEM，可接受。
    """

    __tablename__ = "nexus_key_request"

    id = Column(Integer, primary_key=True, autoincrement=True)
    oem_id = Column(Integer, nullable=False, index=True)
    # 申请留言（用途/域名计划），给超管审batch时看
    note = Column(Text, nullable=False, default="")
    # pending=待处理 / approved=已签发 / rejected=已拒绝
    status = Column(String(16), nullable=False, default="pending")
    created_ts = Column(BigInteger, nullable=False, default=_now_ms)
    decided_ts = Column(BigInteger, nullable=True, default=None)
    # 批准后关联的 KEY 与其明文（兑换后清空）；拒绝时可留拒绝理由
    key_id = Column(Integer, nullable=True, default=None)
    key_plain = Column(String(64), nullable=False, default="")
    decide_note = Column(Text, nullable=False, default="")


class NexusKeyClaim(Base):
    """OEM 认领 KEY 的归属边：一把 KEY 只归一个 OEM。

    为什么单开一张表而不在 nexus_key 上加列：本项目没有迁移框架、建表靠
    ``create_all``——新表能自动建，给**现存**表加列却不会自动 ALTER。归属做成
    独立表，既零迁移风险，又把「KEY 签发（超管）」与「KEY 认领（OEM）」解耦。
    实例归属 = 实例 → 其 key_id → 本表 → oem_id。
    """

    __tablename__ = "nexus_key_claim"

    key_id = Column(Integer, primary_key=True)  # = NexusKey.id
    oem_id = Column(Integer, nullable=False, index=True)
    claimed_ts = Column(BigInteger, nullable=False, default=_now_ms)


class NexusRequestStat(Base):
    """网关请求的**分钟级聚合**（大屏的成功率 / 平均延迟 / 峰值 req 的数据源）。

    为什么按分钟聚合而不是逐请求存一行：大屏要的是聚合值,不需要逐条明细;分钟桶把存储
    压掉三个数量级(每实例每天最多 1440 行),还天然给出"峰值 req/min"。
    为什么必须单独记而不能复用 ledger：**ledger 只在扣费成功时写**(上游 4xx/5xx、
    上游不可达都不写),失败请求根本没留痕 → 成功率无从算起。这张表**成败都记**。

    同样是独立表(本项目无迁移框架,加列不会自动 ALTER,见 NexusKeyClaim 说明)。
    """

    __tablename__ = "nexus_request_stat"

    # 复合主键：一个实例在一分钟内只有一行，并发写靠"先 UPDATE 不中再 INSERT"收敛
    instance_id = Column(Integer, primary_key=True)
    minute_ts = Column(BigInteger, primary_key=True)   # 对齐到整分钟的 epoch ms
    ok_count = Column(Integer, nullable=False, default=0)
    fail_count = Column(Integer, nullable=False, default=0)
    # 延迟只累计**成功**请求（失败往往是秒回的 4xx，混进来会把均值拉得虚低）
    latency_sum_ms = Column(BigInteger, nullable=False, default=0)
    latency_max_ms = Column(Integer, nullable=False, default=0)


class NexusInstanceGeo(Base):
    """实例地域（大屏地图打点用）。**独立表**，理由同 NexusKeyClaim——本项目没有迁移
    框架，给现存的 nexus_instance 加列不会自动 ALTER，新开一张表零迁移风险。

    地域**由 OEM 兑码时选定**（他自己最清楚机房在哪），console 可改；不做 IP 自动定位
    （云 IP 归属常是服务商注册地而非机房，反而更不准，详见 geo.py 模块注释）。
    ``last_ip`` 是心跳来源 IP 的**脱敏网段**，只作人工核对参考，不参与定位。
    """

    __tablename__ = "nexus_instance_geo"

    instance_id = Column(Integer, primary_key=True)   # = NexusInstance.id
    # 地域代码（见 nexus/geo.py REGIONS，如 CN-ZJ / SG）；空=未填，大屏不打点
    region_code = Column(String(16), nullable=False, default="")
    # 冗余存下当时的中文名与经纬度：字典将来微调坐标也不影响历史展示，大屏直接读免查表
    region_label = Column(String(64), nullable=False, default="")
    lat = Column(Float, nullable=True, default=None)
    lon = Column(Float, nullable=True, default=None)
    # 心跳来源 IP 的脱敏网段（如 1.2.3.0/24），仅供核对 OEM 填的地域是否离谱
    last_ip = Column(String(64), nullable=False, default="")
    updated_ts = Column(BigInteger, nullable=False, default=_now_ms)


class NexusRelease(Base):
    """超级管理员创建的 GuDuu OS 发行版本。

    版本记录与 Git tag 一一对应。状态机刻意保持很小：``draft`` 仅保存草稿，
    ``canary`` 只推给一个灰度节点，``published`` 推给全部在线授权实例，
    ``rollback`` 表示全节点精确回撤到该历史版本，``paused`` 暂停尚未领取的任务。
    发布说明存 Nexus DB，OEM 节点不需要访问 GitHub API 就能取得统一说明。
    """

    __tablename__ = "nexus_release"

    id = Column(Integer, primary_key=True, autoincrement=True)
    version = Column(String(32), nullable=False, unique=True, index=True)
    title = Column(String(255), nullable=False, default="")
    notes = Column(Text, nullable=False, default="")
    # 自动更新只接受 vX.Y.Z 形式的 tag，避免后台内容变成任意 git 参数。
    git_ref = Column(String(40), nullable=False, unique=True)
    # draft / canary / published / rollback / paused
    status = Column(String(16), nullable=False, default="draft", index=True)
    canary_instance_id = Column(Integer, nullable=True, default=None)
    created_ts = Column(BigInteger, nullable=False, default=_now_ms)
    updated_ts = Column(BigInteger, nullable=False, default=_now_ms)
    published_ts = Column(BigInteger, nullable=True, default=None)


class NexusReleaseTrack(Base):
    """版本所属发布轨道的一对一扩展记录。

    这个信息故意放在新表而不是给 ``nexus_release`` 直接加列：生产已经有历史版本表，
    SQLAlchemy ``create_all`` 不会替旧表执行 ``ALTER TABLE``。独立表能在服务重启时
    安全创建；没有对应记录的历史版本一律解释为 ``node``，保持原来的节点投放语义。
    """

    __tablename__ = "nexus_release_track"

    release_id = Column(Integer, primary_key=True)
    # nexus=集中式平台公告；node=OEM 实例真实安装任务。
    target = Column(String(16), nullable=False, default="node", index=True)
    created_ts = Column(BigInteger, nullable=False, default=_now_ms)


class NexusReleaseDeployment(Base):
    """一个发行版本在一个 OEM 实例上的投放与安装状态。

    复合主键保证同一版本对同一实例只生成一个任务。失败任务不会被节点无限重试，
    必须由超级管理员在控制台明确重置为 ``pending``，避免坏版本形成重启风暴。
    """

    __tablename__ = "nexus_release_deployment"

    release_id = Column(Integer, primary_key=True)
    instance_id = Column(Integer, primary_key=True)
    # pending / downloading / installing / success / failed / skipped
    status = Column(String(16), nullable=False, default="pending", index=True)
    from_version = Column(String(32), nullable=False, default="")
    to_version = Column(String(32), nullable=False, default="")
    # 节点只上报末尾错误摘要；服务端仍截断，防止日志灌库。
    detail = Column(Text, nullable=False, default="")
    attempts = Column(Integer, nullable=False, default=0)
    created_ts = Column(BigInteger, nullable=False, default=_now_ms)
    updated_ts = Column(BigInteger, nullable=False, default=_now_ms)
    finished_ts = Column(BigInteger, nullable=True, default=None)


# 组合索引：按实例翻流水/心跳是最高频查询
Index("ix_nexus_ledger_inst_ts", NexusLedger.instance_id, NexusLedger.ts)
Index("ix_nexus_hb_inst_ts", NexusHeartbeat.instance_id, NexusHeartbeat.ts)
Index(
    "ix_nexus_release_deploy_inst_status",
    NexusReleaseDeployment.instance_id,
    NexusReleaseDeployment.status,
)

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
