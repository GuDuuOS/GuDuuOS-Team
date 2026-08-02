# GuDuu OS — 项目规范 (Project Rules)

> 这是项目的"宪法"。每次开新会话，AI（Codex）必须先读这份文件，再动手。
> 任何架构决定、目录约定、开发流程都以本文件为准；本文件过时了要先更新它，再写代码。

---

## 1. 这是什么项目

**GuDuu OS** —— 基于 [Synapse](https://github.com/element-hq/synapse)（Matrix 同构服务器）改造的**海外版 IM**。
- **源码参考**：`synapse/` 目录是 matrix.org 归档版 **v1.98.0**（只读参考）。
- **本地运行**：venv 里 pip 装的 **v1.141.0**（这是兼容 macOS arm64 + Python 3.9 的最新预编译版；1.98.0 在本机无预编译 wheel、需 Rust 编译，故运行用 1.141.0）。appservice / Module API 在两版本间稳定，不影响开发。

目标：在标准 IM（聊天 / 群组 / 联邦）之上，叠加一个**主 AI 控制层**，让 AI 能感知并操作 IM 的所有功能，并逐步加入群级智能、Bot/插件/工作流、交易、个人主页等模块。

**开发模式**：单人开发者（项目负责人）+ Codex（AI 结对）。
**节奏铁律**：**一次只推进一个模块**。不并行铺开多条战线。每块做到能跑通、能验证，再开下一块。

---

## 2. 最重要的架构原则（不可违背）

> **不改 Synapse 核心代码。所有 GuDuu OS Star 的业务逻辑写在独立扩展层里。**

原因：Synapse 是个成熟的大型项目，改核心会导致以后无法跟上游更新、难以维护。Synapse 已经提供了足够强的扩展点，足以实现"主 AI 控制一切"。

允许的接入方式（按优先级）：
1. **Synapse Module API**（`synapse/module_api/__init__.py`）—— 用回调插进事件管线，调用 IM 能力。**首选**。
2. **Application Service（appservice）** —— Matrix 标准的 Bot/机器人接入协议。用于独立 AI 进程、Bot。
3. **新增独立服务 / 新 REST 端点** —— 交易、个人主页等需要新 API 时。
4. ⚠️ **改 Synapse 核心** —— 仅在前三种都做不到时，且必须在本文件 §8「核心改动记录」里登记，说明为什么、改了哪里。

### Module API 已暴露的关键能力（实现"AI 控制 IM"用这些）
| 能力 | 方法 |
|---|---|
| 创建群/房间 | `create_room()` |
| 改成员（邀请/踢/加入） | `update_room_membership()` |
| 查房间状态/成员 | `get_room_state()` / `get_state_events_in_room()` |
| AI 发消息进群 | `create_and_send_event_into_room()` |
| 感知每条消息（AI 的"眼睛"） | `register_third_party_rules_callbacks()` / `register_spam_checker_callbacks()` |
| 群级独立数据存储 | account data manager（房间级 account data） |
| 注册用户/Bot | `register_user()` |

回调文档见 `synapse/docs/modules/`。

---

## 3. 目标架构

```
┌─────────────────────────────────────────────────────┐
│  客户端 (先用 Element 验证；个人主页/交易/工作流 UI 后做)  │
└────────────────────────┬────────────────────────────┘
                         │ Matrix C-S API + GuDuu OS Star 自定义 API
┌────────────────────────▼────────────────────────────┐
│  Synapse 核心 (v1.98.0, 尽量不动)  →  synapse/         │
│  ┌──────────────────────────────────────────────┐   │
│  │ GuDuu OS Star Module (插进事件管线)                       │   │  ← 主要在这写
│  └──────────────────────────────────────────────┘   │
└────────────────────────┬────────────────────────────┘
                         │ Appservice 协议
┌────────────────────────▼────────────────────────────┐
│  GuDuu OS Star AI 服务 (独立进程)  →  cosmac/                   │
│  • 主AI Agent  • 多模型抽象层  • 群级记忆/知识库/Rule/Skill │
│  • Bot/插件/工作流引擎                                  │
└──────────────────────────────────────────────────────┘
```

### 目录约定（新代码放哪）
- `synapse/` —— 上游 Synapse 仓库，**只读为主**。改动需登记（§8）。
- `cosmac/` —— **新建**，GuDuu OS Star 自己的代码（AI 服务、Module、工作流引擎等）全部放这。与 `synapse/` 同级，独立 Python 包。
  - `cosmac/module/` —— Synapse Module（薄薄一层，转发到 AI 服务）
  - `cosmac/ai/` —— 主 AI Agent + 多模型抽象层
  - `cosmac/memory/` —— 群级记忆 / 知识库 / Rule / Skill
  - `cosmac/bots/`、`cosmac/workflows/`、`cosmac/trading/`、`cosmac/profile/` —— 后续模块
  - `cosmac/tests/` —— GuDuu OS Star 自己的测试

> 注：`cosmac/` 目录在对应模块开工时再创建，不提前建空壳。

### 多模型抽象层（AI 后端可配置）
主 AI 背后的大模型**必须做成可插拔**：统一接口，支持 Claude / OpenAI / 本地模型等多后端，通过配置切换。不要把任何一家厂商的 SDK 调用散落在业务逻辑里——全部走 `cosmac/ai/` 的统一抽象。

### 数据存储分层（写持久化代码前先对照这张表）

> 铁律：**Synapse 已经存的东西绝不在 GuDuu OS Star 这边重存一份**（否则数据双写、必然不一致）。
> 只有 Synapse 存不下/搜不了的「AI 层自己的结构化/派生数据」，才进 GuDuu OS Star 自己的数据库。

| 数据 | 存哪 | 说明 |
|---|---|---|
| **聊天记录 / 消息 / 已读位** | 🚫 Synapse 的 PG | Matrix 本职，前端走 sync 拿。**不要**在 cosmac 再存一份。 |
| 账号、群组/成员、房间状态 | 🚫 Synapse 的 PG | 同上。 |
| **全局 AI 配置**（人设/模型/工具开关） | Matrix state event | 已实现：写在控制室 `cosmac.ai.config`（见 §9 / memory `ai-config-control-room`）。 |
| **每账号轻量配置** | Matrix per-user **account data** | 优先用它：每用户键值、自动同步到客户端、零新基建。撑不住结构化关联时再迁 DB。 |
| **Skill / Agent 定义** | ✅ GuDuu OS Star DB | 结构化、要版本、要按账号/群查询关联。 |
| **知识库** | ✅ GuDuu OS Star DB + **pgvector** | 文档分块 + 向量检索(RAG)，state event 存不下也搜不了。**这是上 DB 的最硬理由**。 |
| **群级 / Agent 记忆**（摘要、长期记忆） | ✅ GuDuu OS Star DB | 派生数据，与原始聊天记录分开存。 |
| 工作流定义与运行记录（模块3）、交易（模块4）、个人主页（模块5） | ✅ GuDuu OS Star DB | 关系型。 |
| **OEM/Nexus 数据**（OEM 层级、用户归属、KEY、实例、钱包/订单、心跳、版本发布） | ✅ Nexus 独立 PostgreSQL | 母舰侧独立保存，与各 OEM 的 Synapse/cosmac 数据库隔离；只存 Matrix 用户 ID 与归属边，不收集客户密码/聊天；节点应用发布下发经 CI 登记的不可变 Docker 镜像摘要，严格 Git tag 仅保留为宿主更新器引导/救援通道，不保存客户 SSH 凭据。 |

**基建决策**：GuDuu OS Star 的 DB **复用生产现成的 PostgreSQL**，给 cosmac 服务**单开一个 database/schema**，按需装 **pgvector**。走 §2 的第 3 条路径，与 Synapse 核心解耦、不碰它。

**实现约定**（`cosmac/db/`）：用 **SQLAlchemy（同步）**（bot 是同步的，别引入 async）；连接由 `COSMAC_DATABASE_URL`（旧 `GUDUU_DATABASE_URL` 仍兼容） 配置，生产指向 Postgres、本地默认回退 SQLite（`run/cosmac.db`）；pgvector 是 Postgres 专属，本地缺它时相关功能要优雅降级。

**Nexus 基建决策（2026-08）**：生产 Nexus 使用自己 VM 上的独立 PostgreSQL
数据库 `nexus` 和最小权限角色 `nexus_app`，连接只监听本机；`NEXUS_DATABASE_URL`
从 `/etc/nexus.env` 注入。SQLite 仅保留为本地开发回退，不能再作为生产主库。生产每天
生成 custom-format `pg_dump`，保留 30 天；迁移前 SQLite 停机快照长期保留用于灾备。

**Nexus 超管安全边界（2026-08）**：OEM 门户继续使用
`dev-nexus.guduu.co`；平台超级管理员迁到独立的 `admin-nexus.guduu.co`，两个入口
不共享前端登录页面与浏览器 Cookie。管理域名外层必须由 Cloudflare Access 保护，只
允许平台主管明确加入白名单的邮箱，并启用独立 MFA；应用层仍保留自己的具名管理员
鉴权，不能把 Access 当成唯一权限边界。日常首选 WebAuthn / Passkey，密码只作为
备用方式；RP ID 与 Origin 由服务端环境变量锁定为正式管理域名，禁止信任请求 Host
动态生成。Passkey 完成真实设备注册和恢复演练后，网页不得再接收长期
`NEXUS_ADMIN_TOKEN`；灾难恢复改为从服务器 SSH 生成短期、单次使用的恢复码，数据库
只保存恢复码哈希，使用或过期后立即作废并写审计。

---

## 4. 功能路线图（一次只推一个）

| # | 模块 | 状态 | 说明 |
|---|------|------|------|
| 0 | 项目规范 (本文件) | ✅ 进行中 | — |
| 1 | **主 AI 控制层** | ✅ 完成 | 地基齐活：appservice bot 看到每条消息+自动进群+回消息（`cosmac/bots/`）；多模型可配置（echo/claude/openai/deepseek/gemini，无 key 自动降级 echo，`cosmac/ai/`）；AI 工具调用（建群/发消息/查成员/读记录）；后台 AI 配置经控制室热下发 + 服务器管理员↔控制室成员联动。后续增量工具按需补，不再算"开工中"。 |
| 2 | 群级 记忆/知识库/Rule/Skill | ✅ 完成 | 全套上线：Skill(数据/注入/命令/后台UI)、Agent(后台UI/群绑定/人设+模型+技能)、知识库(引擎/入库命令/RAG·线上实测)、Rule(平台硬约束)、记忆(短期对话 + 文档KB)。cosmac DB 已接生产 Postgres。增强项(长期记忆摘要/pgvector/知识库上传UI)按需再补 |
| 3 | Bot / 插件 / 工作流引擎 | ✅ 完成 | **定调：不自建引擎，对接外部平台**(n8n/Make/Coze/ComfyUI/Dify)。全套上线：通用连接器引擎(`cosmac/wf.py`，含 webhook/Dify/Coze/ComfyUI)+ 聊天命令 `工作流 列表/跑` + 主 AI 工具 `run_workflow` + 异步回调协议 + 运行记录入库 + **后台编排 UI**(`AdminView.vue` 工作流面板：4 平台连接器增删改查、凭据只填名)；定义走控制室 `cosmac.workflows`、密钥走服务端 env。任务治理增加**真人审核人 + 待审核状态**：执行者/AI 只能提交待审，仅指定真人审核人（缺省频道管理员/任务下达人）可通过为已完成；AI 不得自审自批。**安全/健壮性"够用即止"**(负责人 2026-06 拍板)：单实例下真实风险(SSRF/密钥/鉴权/DoS/重复触发/崩溃可见性)全堵；**durable 任务队列 + 多实例 fencing + per-event 精确一次**记为**已知架构边界·本期不做**(单 bot 小规模属过度设计)。增强项(更多平台适配器/graph 上传 UI)按需再补 |
| 4 | 交易系统（会员订阅） | 🟡 进行中 | **主线=会员订阅/充值**，多渠道支付(Stripe/PayPal/USDT/支付宝/微信)按 IP 地理路由，范围"较完整"。**P1 地基已落地+单测**(`cosmac/trading/`)：套餐定义(控制室 `cosmac.plans`)+ 订单(DB `cosmac_order`)+ **可插拔支付抽象** `PaymentProvider`(密钥只进 env)+ 订单服务(下单/支付成功**幂等**开通/**续费按原到期日顺延**)+ 会员**到期**(扩 `members.py`：grant 带 expires_ts、查等级自动判过期)+ 手动/mock 支付(HMAC 验签)。**分期**：P2 Stripe 全链路+webhook+前端套餐页；P3 PayPal/USDT+地理路由；P4 支付宝/微信+对账/退款。 |
| 5 | 个人主页 | ⬜ | 需要客户端 UI 配合 |
| 6 | **OEM 体系（GuDuu Nexus + 发行版）** | 🟡 进行中 | 当前增量：完善 Nexus 超级管理员工作台。后台采用左侧功能导航，把舰队总览、版本管理、节点实例、授权申请、OEM 客户、支付订单和只读数据大屏分区呈现；舰队总览加入资金经营视角，展示累计实收、近 30 天实收、待支付、授权码/Token 充值收入构成与支付渠道接入状态，金额只以服务端已确认 `paid` 的订单计入收入，支付宝/微信 API 未接入前明确显示“待接 API”，绝不伪造流水；**OEM 归属体系采用无限层级树**：每个 OEM 只有一个直属上级但可有任意深度下级，不设层数、佣金或分账规则；每个 OEM 获得稳定的随机分享码，门户生成“邀请普通用户”与“邀请下级 OEM”链接及二维码。普通用户通过带分享码的 OEM 实例注册链接建号后，实例本地先持久化归属再通过授权 KEY 幂等同步到 Nexus，Nexus 记录 `用户→直属 OEM→完整祖先链`，母舰暂时只做关系与人数统计，不参与用户密码、聊天数据或收益分配；新版本表单根据当前产品版本与 `DEVLOG.md` 自动生成版本号、Git tag、标题和面向 OEM 的更新说明，仍默认“未发布”；节点版本还必须匹配 CI 登记的 bot/web 不可变 Docker 摘要。超级管理员维护永久历史版本列表，发布流程为“未发布→灰度监测→全量发布→暂停”，并可选择已发布过的旧版本发起全节点回撤。节点升级成功后，同一份版本说明由成功投放记录自动呈现在对应 OEM 门户，作为更新公告（不向客户业务群自动发消息）。节点更新仍由宿主代理按 KEY 主动拉取，禁止 Nexus 主动 SSH OEM 服务器，也禁止给 bot 容器宿主机控制权。 |
| R | **品牌化 Matrix→GuDuu OS Star** | ⬜ 持续 | 贯穿全程的横切任务，按 §7 三层红线分层改，每碰到呈现层字样就顺手改 |

> **Nexus 支付渠道更新（2026-08）**：舰队总览同时覆盖国内支付宝/微信与海外
> Stripe/PayPal/USDT。真实 API 未联调前统一显示“待接 API”，不生成或暗示虚假
> 收入；海外正式收款前必须先给 Nexus 订单补齐 currency、原币金额和结算金额，
> 按原币分别统计，禁止把 USD/USDT 混入当前人民币分汇总。

> **Nexus 支付配置中心（2026-08）**：超级管理员可从舰队总览点击支付渠道填写
> 官方凭据。密钥使用独立 ``NEXUS_SECRET_KEY`` 在服务端加密后写入 Nexus PostgreSQL，
> API 和前端只返回“字段已配置”标记，绝不回传密钥原文；空白提交保留旧密钥。
> Stripe/PayPal/NOWPayments 只向官方固定域名发起无扣款的远程认证检查，禁止管理员
> 自填 API Base 以免引入 SSRF。支付宝/微信在没有安全的只读探测接口时只验证 RSA
> 密钥、证书字段和 APIv3 密钥格式，并明确标为“本地校验通过、待沙箱交易联调”。
> “凭据已验证”不等于“真实支付已上线”：订单币种、下单、回调验签、幂等履约和沙箱
> 验收全部完成后，渠道才可对 OEM 开放。USDT 首个服务商固定采用 NOWPayments，
> 使用 API key + IPN secret 自动对账，不支持只填钱包地址后人工猜单。

> **Nexus 企业转账（2026-08）**：微信支付下方提供独立“企业转账”人工入账入口，
> 不复用测试用 `manual` 支付渠道。每笔生成 `BT` 单号、必须上传 JPG/PNG/WebP 凭证，
> 金额与笔数计入舰队总营收但在统计和订单列表中用专色单独标识。银行详情、AI 候选结果
> 与凭证原图均使用 `NEXUS_SECRET_KEY` 加密保存在 Nexus PostgreSQL；同一凭证哈希禁止
> 重复入账。视觉 AI 只能在超管明确点击后提取金额、企业、账号、银行、流水号和时间并
> 预填表单，不能自动确认收入；必须由超管核对银行真实到账并勾选确认后才生成记录。

> **Nexus 双发布轨道（2026-08）**：Nexus 是平台集中托管的多租户控制面，OEM 客户
> 直接使用同一套后台，禁止为每个 OEM 再部署一份 Nexus。版本中心创建记录时必须明确
> 选择更新对象：`nexus` 表示平台后台更新，发布动作只把公告展示到全部 OEM 门户，
> 不创建节点安装任务，也不提供节点灰度/回撤；`node` 表示 OEM 实例发行版更新，继续
> 通过 Git tag、灰度、全量、暂停、回撤和宿主更新代理完成真实安装，并仅在所属节点
> 上报成功后向对应 OEM 展示公告。既有未标记版本兼容解释为 `node`，避免升级 Nexus
> 数据库后改变历史投放语义；两条轨道互不暂停、互不覆盖。

> **Nexus Docker 镜像发布（2026-08）**：OEM 节点应用采用两阶段发布。
> 第一阶段由 GitHub Actions 在严格 ``vX.Y.Z`` tag 上构建 bot/web 镜像并推送 GHCR，
> Nexus 只接受带独立 HMAC 签名、五分钟时效的构建清单；发布记录冻结
> ``仓库@sha256:digest``、源码 commit 与平台信息，禁止只下发可移动 tag。
> 第二阶段由 OEM 宿主机更新代理主动拉取精确摘要，在切换前备份 PostgreSQL、保留当前
> 容器镜像为本机回撤点，校验 Caddy 配置后仅重建 bot/web；体检失败必须自动切回原镜像
> 并上报失败，成功后才持久化新摘要。数据库、Synapse、Caddy 证书与 OEM ``.env``
> 继续留在宿主机持久化目录，镜像不得包含客户配置或数据。私有 GHCR 凭据只能保存在
> 宿主机 root 权限文件并以 ``read:packages`` 最小权限登录，Nexus、bot 容器和版本清单
> 均不得保存凭据。既有版本与更新器/Compose 自身升级继续兼容严格 Git tag；这是明确的
> bootstrap/灾备路径，不是日常应用发布方式，也不得给 bot 容器 Docker socket。

> **Nexus 授权中心 V2（2026-08）**：OEM 授权申请保存企业联系快照、
> 计划域名、用途、期望日期和 Token 需求，并保留全量历史。申请状态为
> `pending / needs_info / approved / rejected / cancelled`，只有待处理状态
> 可批准；审批使用数据库行锁，一份申请最多签发一把 KEY。KEY 明文
> 使用 `NEXUS_SECRET_KEY` 加密，不向超管或列表返回；仅允许所属 OEM 主动
> 限时领取，节点兑换后立即清除密文。申请、审批、领取、兑换以及 KEY
> 暂停/恢复/永久吊销都写入只追加的审计事件。当前超管仍是单一平台
> 令牌，审计人暂记“平台超级管理员”和来源 IP；升级具名管理员账号后
> 直接写入真实操作人，不改审计表结构。

> **Nexus 授权购买 V3（2026-08）**：OEM 门户统一从“购买节点授权”创建申请，
> 一张申请只关联一种履约方式。在线支付按服务端价格生成订单，只有渠道验签且金额、
> 币种与订单一致后才自动签发一把 KEY；企业转账按服务端价格生成待审凭证，必须上传
> JPG/PNG/WebP 并填写付款企业，只有超管核对银行真实到账后才在同一事务中计入营收并
> 签发 KEY；合同/免费授权保留人工审批。三条路径共用加密交付和审计逻辑，支付回调与
> 管理员确认均幂等，订单接口不返回新流程的 KEY 明文。OEM 可在七天内从授权申请主动
> 领取，任何凭证或 AI 识别结果本身都不能触发自动发码。

> **Nexus KEY 部署绑定（2026-08）**：OEM 申请节点授权时必须填写计划部署域名，
> 审批或支付履约签发 KEY 时把规范化域名冻结为授权边界；节点在线兑换时必须提交完全
> 一致的域名，禁止“先领码、任意服务器先到先得”。申请可选填写静态公网 IP：默认仅作
> 风险核验，来源 IP 不一致时允许激活但返回警告并留痕；只有 OEM 明确启用“严格 IP
> 绑定”时才拒绝不一致来源。来源 IP 必须由 Nexus 从可信反向代理请求读取，不能相信
> 节点自报；数据库只保存使用 ``NEXUS_SECRET_KEY`` 计算的 HMAC 和脱敏网段，不保存
> 完整公网 IP。历史 KEY 保持兼容：没有预绑定记录时首次兑换冻结实际域名，已绑定实例
> 的同域重装保持幂等。后续改域名或严格 IP 必须走平台审核，不能由客户端自行覆盖。

> **Nexus OEM 企业控制台（2026-08）**：OEM 登录后与平台超管使用同一套左侧
> 工作台导航语言，功能拆为我的首页、邀请与层级、版本公告、购买与充值、授权申请、
> 我的 KEY 六页；页面状态使用 `#oem-*` hash，支持刷新、深链和前进/后退。角标只能
> 统计当前登录 OEM 经服务端过滤后的资源，不能混入其他企业或平台总量；窄屏时侧栏
> 转换为顶部横向滚动导航，不挤压业务表格。

> **Nexus OEM 邮箱身份（2026-08）**：Nexus OEM 企业账号与各节点 Matrix 用户账号
> 是两套独立身份。新 OEM 注册必须先验证邮箱；门户同时保留密码登录并提供邮箱验证码
> 登录，找回密码使用独立用途验证码，成功后立即撤销该 OEM 的全部旧会话。注册、登录、
> 重置验证码必须互相隔离、十分钟过期、单次消费并限频限错；数据库只保存以
> ``NEXUS_SECRET_KEY`` 计算的 HMAC，不保存明文验证码。SMTP 凭据只允许从
> ``NEXUS_SMTP_*`` 服务端环境变量读取，配置不完整时服务必须安全关闭发码能力，不能把
> 验证码写日志或返回浏览器。既有 OEM 账号继续兼容密码登录，首次完成验证码登录或
> 找回密码后补记已验证邮箱，避免上线时锁死存量客户。

> **Nexus OEM 下属目录（2026-08）**：“邀请与层级”页必须同时提供下级 OEM
> 和归属普通用户清单。目录直接从 `NexusOemInvite` 与
> `NexusUserAttribution` 的真实边动态计算，不复制统计数据；当前 OEM
> 可看自己的直属和间接下级，以及自己整个后代网络的 Matrix 用户 ID、
> 直属企业和注册实例。服务端必须阻断上级、旁支与其他网络，且不向上级返回
> 下级企业邮箱、联系人、电话、密码或聊天内容。

> **Nexus OEM 自有节点详情（2026-08）**：OEM“我的首页”中的实例卡可点击，
> 详情与超管节点快照使用同一真实数据口径：节点心跳提供账号分类、房间/频道、
> 会员、知识库、Skill、AI Agent 与工作流，Nexus 账本提供 Token 余额/消耗
> 和 AI 请求数。OEM 详情必须使用独立会话端点，在返回快照前沿
> `实例 → KEY 认领 → OEM` 强制校验；不属于当前 OEM 与不存在的编号统一
> 返回 403，禁止从前端传入或缓存其他企业节点详情。超管节点详情继续使用弹窗；
> OEM 节点详情在实例卡片列表下方行内展开，同一时间只展示一个选中节点。

> **Nexus OEM 网络数据开关（2026-08）**：OEM 的分享页、普通用户/OEM 注册链接
> 与二维码始终保留；超管“舰队总览”的全局开关只控制层级统计、下属 OEM 清单和
> 归属普通用户清单，缺省必须关闭。关闭时 `/oem/me` 只返回分享码与链接，不返回
> 层级或人数汇总，`/oem/network` 必须在服务端返回 403，但 `/oem/share_qr` 继续
> 可用，禁止把整个邀请页面一起隐藏。关闭不删除既有归属边，超管仍可管理真实数据，
> 重新开启后原有关系立即恢复。节点运行账号数等实例健康指标继续正常展示。

> **Nexus OEM 销售收益与提现（2026-08）**：平台统一作为收款方，不把第三方支付
> 密钥或资金账户下放给 OEM。已登录 OEM 购买节点授权或给自有节点充值时，订单买家
> 的直属上级 OEM 作为唯一销售归属；平台直属买家不产生 OEM 收益，不做多级返佣。
> 超管分别设置客户零售价与 OEM 结算价，支付成功后价差进入直属销售 OEM 的内部
> 收益账本，默认 T+7 转为可提现；退款、拒付和人工调整必须以反向流水处理，禁止
> 直接覆盖历史金额。提现先采用 OEM 提交加密收款账户、超管人工审核与线下打款，
> 支付代付 API 接通前不得伪装成自动到账。KEY 仍走授权申请与安全领取，Token 仍只
> 能充值到买家自己拥有的节点；订单履约、收益入账与幂等校验共用现有支付事务。

> **Nexus 具名超级管理员（2026-08）**：平台主管日常登录必须使用数据库中的具名
> 管理员账号和可撤销短期会话，审计事件写入真实显示名；原有
> ``NEXUS_ADMIN_TOKEN`` 仅保留为服务器侧应急入口和首个管理员引导凭据，控制台
> 必须明确标注“应急令牌”，不得继续伪装成普通账号。管理员账号支持创建、停用、
> 重置密码与会话整体失效；禁止停用当前账号或最后一个有效管理员。所有管理端写操作
> 还要追加一条全局操作审计，授权/KEY 等业务对象原有的细粒度时间线继续保留。
> 超管登录固定使用独立地址 ``/portal/admin/``，普通 ``/portal/`` 只显示 OEM
> 登录/注册，不提供超管切换入口。独立 URL 只负责产品入口隔离，不得被当成鉴权手段；
> 服务端仍必须逐请求校验具名管理员会话。浏览器会话必须使用
> ``HttpOnly + Secure + SameSite=Strict`` 的非持久化 Cookie，管理写操作另验
> ``X-Nexus-CSRF``；不得把管理员会话放在 local/sessionStorage。应急静态令牌不得
> 作为日常长期会话，浏览器验证后只换取 30 分钟恢复 Cookie，且不返回令牌原文。

> 状态符号：⬜未开始 / 🟡进行中 / ✅完成。开工/完成时更新这张表。

---

## 5. 开发约定（来自本仓库真实配置，写代码必须遵守）

- **语言**：Python（`^3.8`），热点路径有 Rust 扩展（`rust/`，PyO3）。
- **Lint / 格式**：`ruff`，行宽 **88**。提交前跑 `poetry run ruff check synapse/ cosmac/`。
- **类型检查**：`mypy`（配置见 `synapse/mypy.ini`）。新代码要带类型注解。
- **测试**：Synapse 用 trial。运行：`poetry run trial tests`（GuDuu OS Star 测试放 `cosmac/tests/`）。
- **Changelog（重要）**：Synapse 仓库每个改动都要在 `synapse/changelog.d/` 加一个文件，命名 `<PR号>.<类型>`，内容一句话（句号结尾）。类型：
  - `feature` 新功能 / `bugfix` 修复 / `doc` 文档 / `removal` 移除 / `misc` 内部改动 / `docker`
  - GuDuu OS Star 自己的代码（`cosmac/`）是否沿用 towncrier 待定；定下来之前先在 commit message 写清。
- **依赖**：用 Poetry 管理（`pyproject.toml` + `poetry.lock`）。
- **中文注释（强制）**：写代码时必须加**详细的中文注释**，越细越好。
  - GuDuu OS Star 新代码（`cosmac/`）：每个模块/类/函数都要有中文 docstring 说明"这是干嘛的、参数啥意思、返回啥"；关键逻辑行内也要中文注释解释"为什么这么写"。
  - 改/调用 `synapse/` 时：在改动处加中文注释说明意图（方便以后定位 GuDuu OS Star 的改动）。
  - 注释解释**意图和原因**，不要只复述代码字面意思。专有名词（如 appservice、event）可保留英文。

### 客户端路由约定（URL routing，写前端必守）

> 背景：真实客户端的根组件是 `client/src/views/LiveView.vue`（`main.ts` 直接挂它，**不走 `<router-view>`**）。导航靠 LiveView 内的**集中式 URL 双向同步**，不是常规 router-view 路由。

- **每个"页面级"视图必须有独立地址**，支持浏览器后退/前进、刷新留在原页、深链直达。已接：数据看板 `/s/:space/board`、任务看板 `…/tasks`、频道 `…/c/:roomId`、管理后台 `/admin`、个人主页 `/me`。
- **哪些接路由**：占据主区/全屏、用户会想刷新留存或分享的"页面"才接。**临时态不接**——菜单、各种设置/新建/成员弹窗、侧栏折叠、AI 侧栏、专注模式、工具弹窗（市场/插件商城/资产/CLI）。判断不准就先**不接**，问负责人。
- **怎么接新视图**（三步，别改既有点击 handler）：① 导航状态收敛到 setter（`selectSpace/openBoard/openTasks/openRoom + adminOpen/profileVisible` 那套）；② 在 LiveView 的 `computePath()`（状态→地址）和 `applyFromRoute()`（地址→状态）各加一条分支，并把新状态加进那个 `watch([...])` 数组；③ `router/index.ts` 补一条指向 `Blank` 的路由（仅为让 hash 合法、不被 catch-all 弹回 `/`；component 永不渲染）。
- **用 hash history**（`/#/...`），不要切 history 模式——否则线上要改 nginx try_files 回退。
- 详见 memory `client-root-is-liveview`。

---

## 6. 给 AI（Codex）的工作守则

1. **开工前先读本文件**，对齐架构和路线图。
2. **动 `synapse/` 核心前先停下来确认**——优先找 Module/Appservice 方案；真要改核心，先问负责人，再登记 §8。
3. **一次只做路线图里的一个模块**，不主动扩散到别的模块。
4. 改动后：跑 lint + 相关测试；动了 `synapse/` 就补 changelog。
5. **保持本文件最新**：架构/路线图/核心改动一旦变化，先更新 AGENTS.md。
6. 不确定的产品决策，问负责人，不要自己拍板大方向。
7. **每完成一个可用版本就自动「提交 → 推送 → 给部署命令」，不用等催。** 客户端（`client/`）功能做好且本地 preview 验证通过后，依次：
   - ⓪ **按版本规则升号并写笔记**（详见 `docs/VERSIONING.md`、`.cursor/rules/versioning.mdc`）：SemVer 语义——**PATCH** 有交付就勤涨、**MINOR** 本周有可对外增量再涨（争取每周打包一次）、**MAJOR** 仅破坏性/代际（不强制每月涨）；对齐 `cosmac.__version__` 与 `client/package.json`；`DEVLOG.md` 顶条必须为 `## YYYY-MM-DD — GuDuu OS X.Y.Z (patch|minor|major)`，正文用「新增/修复/优化/变更」分类；不记敏感信息（key/IP 进 `DEPLOY.md`）。
   - ① 重建产物：`cd client && npm run build`（`client/dist` 被 .gitignore，提交用 `git add -f client/dist`）；
   - ② `git commit` + `git push origin main`：发版 commit 第一行必须为 `release: GuDuu OS X.Y.Z (patch|minor|major)`，正文与 DEVLOG 用户可见条目对齐；推荐打 tag `vX.Y.Z`。
   - ③ **直接 SSH 部署 Google Cloud 生产实例**（负责人 2026-08-01 拍板：停止维护旧云环境，只维护当前 Google Cloud 实例）：中央 Nexus 与 OEM 节点分别按本机 `DEPLOY.md` 中已确认的主机、用户和目录执行更新；先验证 Nexus 管理/API，再按版本范围更新 OEM 节点，最后运行各自体检。AI 直接执行，不再给负责人贴命令。IP、密钥、数据库连接和服务器路径只保留在被忽略的 `DEPLOY.md`，不得写进提交或更新说明。
   - 纯后端操作（真建 / 整理 Matrix 频道等，只改服务器数据、不动 `client/` 代码）不必走部署，但要说明"无需部署"。
7.5 **「拉取本周/本月变更说明」**：从区间内 `release:` commit + `DEVLOG.md` 归并，按新增/修复/优化/变更输出可直接对外用的更新文案并标明版本跨度（见 `docs/VERSIONING.md` §7）。**维护感靠勤 PATCH + 周报/月报**，月报不要求伴随 MAJOR。
7.6 **发布类型与版本真值源（强制）**：BUG 修复只发 **PATCH**，功能开发发 **MINOR**（破坏性才 MAJOR），不得再把新功能混进 PATCH。每个发布除 `DEVLOG.md` 外必须同步登记 `docs/RELEASE_LEDGER.md`，写明 `bugfix|feature|maintenance`。任何会话升号前必须先 `git fetch origin main --tags`，再重读 `origin/main` 的 `cosmac.__version__` / `client/package.json` / `DEVLOG.md` / 发布总账；**禁止使用当前会话记忆里的版本号直接升号**。如果发现其他会话已抢先发版，必须基于最新 `origin/main` 重算版本，不得覆盖、跳过或重用已存在版本。
8. **生产基础设施只认当前 Google Cloud 架构**：现役主机、域名、账号和目录以本机被忽略的
   `DEPLOY.md` 为唯一依据。项目规范、待办、架构和用户文档不得保留已退役云厂商、旧服务器
   IP、旧域名、旧面板或旧登录别名；历史经验只保留可复用的技术结论，并改写成不带旧基础
   设施标识的通用说明。安全回归测试中用于拦截云元数据地址的规则不属于部署信息，必须保留。

---

## 7. 品牌化规则：Matrix/Synapse → GuDuu OS Star（三层红线）

> 把"给人看的品牌"换成 GuDuu OS Star，但**绝不动机器之间的协议**。改之前先判断属于哪一层。

| 层 | 包含什么 | 规则 |
|---|---|---|
| **① 协议层 🚫 绝对不改** | `/_matrix/...` API 路径、`m.*` 事件类型（如 `m.room.message`）、联邦协议格式、`.well-known` 里的协议字段、状态事件 type | **一个字都不能改**。改了客户端连不上、联邦崩、Element 不可用 |
| **② 呈现/品牌层 ✅ 改成 GuDuu OS Star** | 产品名、欢迎页"Synapse is running"、系统通知(server notices)、邮件/通知模板、面向用户的文档、日志中的品牌字样、默认 `server_name`/`user_agent`、管理后台标题 | 放心改 |
| **③ 内部标识符 ⚠️ 默认不改** | `SynapseHomeServer` 等类名、内部变量名、Python 包名 `synapse` | 默认保留——改了无用户价值且会让跟上游更新疯狂冲突。仅在有充分理由时改，并登记 §8 |

执行方式：这是**横切/持续任务**，不单开一个大 PR 一次性全改（风险高）。**每当在做其他模块时碰到 ② 类呈现层字样，就顺手改掉**。拿不准属于哪层时——先当作"不能改"，问负责人。

---

## 9. 本地开发环境 (How to run)

- **Python venv**：`.venv/`（Python 3.9.6）。装了 `matrix-synapse==1.141.0`，并把 `prometheus-client` 降到 `0.20.0`（否则 py3.9 上 `Generic+Collector` MRO 冲突，服务器起不来）。
- **Synapse 运行目录**：`run/synapse/`（与源码 `synapse/` 分开）。
  - 配置：`run/synapse/homeserver.yaml`（server_name=`guduu.local`，监听 `127.0.0.1:8008`，SQLite）
  - 启动：`cd run/synapse && ../../.venv/bin/synapse_homeserver --config-path homeserver.yaml`
  - 探活：`curl http://127.0.0.1:8008/_matrix/client/versions`
- **测试账号**：`@alice:guduu.local` / 密码 `Test1234!`（管理员）。建新账号：`run/synapse` 下 `../../.venv/bin/register_new_matrix_user -c homeserver.yaml http://127.0.0.1:8008`
- ⚠️ `run/`、`.venv/` 是本地运行产物，不要提交进 git（应加进 `.gitignore`）。

### 启用真实 AI 模型（多模型可配置）
默认 `echo`（占位）。要用真模型，设环境变量再启动 bot（**key 绝不写进代码**，SDK 从环境变量读）。
> 环境变量前缀统一用 **`COSMAC_*`**；为不破存量部署，旧前缀 **`GUDUU_*`** 仍兼容（代码 `_env` 先查 `COSMAC_` 再回退 `GUDUU_`），迁移到 `COSMAC_*` 后可删旧的。
```bash
# Claude（默认 claude-opus-4-8）
export COSMAC_LLM_PROVIDER=claude
export ANTHROPIC_API_KEY=sk-ant-...
# 或 OpenAI（默认 gpt-4o）
# export COSMAC_LLM_PROVIDER=openai ; export OPENAI_API_KEY=sk-...
# 或 DeepSeek（走火山引擎方舟，OpenAI 兼容）：
# export COSMAC_LLM_PROVIDER=deepseek    # 等价 ark
# export ARK_API_KEY=方舟APIKey
# export COSMAC_LLM_MODEL=deepseek-v3.2  # 填你方舟账号的 Model ID 或 Endpoint ID(ep-...)
# 可选换区域：export ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
.venv/bin/python -m cosmac
```
没配 key 时会自动降级回 echo（bot 照常能跑）。可选：`COSMAC_LLM_MODEL` 换模型、`COSMAC_SYSTEM_PROMPT` 改人设。
部署到 Google Cloud 时，把 `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/`ARK_API_KEY` 配进服务的环境变量/Secret Manager 即可。
> 方舟(DeepSeek)复用 `openai` SDK，只是 base_url 指向方舟。模型 id 以你方舟控制台实际开通/创建的接入点为准。
GuDuu OS Star 服务依赖见 `cosmac/requirements.txt`。

异步工作流回调默认最多等待 **7 天**；可用 `COSMAC_WF_CALLBACK_TIMEOUT` 配置秒数（最低
3600）。网络超时/5xx 属“提交结果未知”，系统会保留回调 token，管理员应先去外部平台
确认状态，不要立即重试；到期后运行记录自动标记 error 并在原群提示。

---

## 8. 核心改动记录 (Synapse core modifications log)

> 任何对 `synapse/` 核心的改动登记在此：日期、文件、原因、是否可改成 Module 方案。

（暂无）
