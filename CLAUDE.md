# GuDuu OS — 项目规范 (Project Rules)

> 这是项目的"宪法"。每次开新会话，AI（Claude）必须先读这份文件，再动手。
> 任何架构决定、目录约定、开发流程都以本文件为准；本文件过时了要先更新它，再写代码。

---

## 1. 这是什么项目

**GuDuu OS** —— 基于 [Synapse](https://github.com/element-hq/synapse)（Matrix 同构服务器）改造的**海外版 IM**。
- **源码参考**：`synapse/` 目录是 matrix.org 归档版 **v1.98.0**（只读参考）。
- **本地运行**：venv 里 pip 装的 **v1.141.0**（这是兼容 macOS arm64 + Python 3.9 的最新预编译版；1.98.0 在本机无预编译 wheel、需 Rust 编译，故运行用 1.141.0）。appservice / Module API 在两版本间稳定，不影响开发。

目标：在标准 IM（聊天 / 群组 / 联邦）之上，叠加一个**主 AI 控制层**，让 AI 能感知并操作 IM 的所有功能，并逐步加入群级智能、Bot/插件/工作流、交易、个人主页等模块。

**开发模式**：单人开发者（项目负责人）+ Claude（AI 结对）。
**节奏铁律**：**一次只推进一个模块**。不并行铺开多条战线。每块做到能跑通、能验证，再开下一块。

---

## 2. 最重要的架构原则（不可违背）

> **不改 Synapse 核心代码。所有 GuDuu OS 的业务逻辑写在独立扩展层里。**

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
                         │ Matrix C-S API + GuDuu OS 自定义 API
┌────────────────────────▼────────────────────────────┐
│  Synapse 核心 (v1.98.0, 尽量不动)  →  synapse/         │
│  ┌──────────────────────────────────────────────┐   │
│  │ GuDuu OS Module (插进事件管线)                       │   │  ← 主要在这写
│  └──────────────────────────────────────────────┘   │
└────────────────────────┬────────────────────────────┘
                         │ Appservice 协议
┌────────────────────────▼────────────────────────────┐
│  GuDuu OS AI 服务 (独立进程)  →  cosmac/                   │
│  • 主AI Agent  • 多模型抽象层  • 群级记忆/知识库/Rule/Skill │
│  • Bot/插件/工作流引擎                                  │
└──────────────────────────────────────────────────────┘
```

### 目录约定（新代码放哪）
- `synapse/` —— 上游 Synapse 仓库，**只读为主**。改动需登记（§8）。
- `cosmac/` —— **新建**，GuDuu OS 自己的代码（AI 服务、Module、工作流引擎等）全部放这。与 `synapse/` 同级，独立 Python 包。
  - `cosmac/module/` —— Synapse Module（薄薄一层，转发到 AI 服务）
  - `cosmac/ai/` —— 主 AI Agent + 多模型抽象层
  - `cosmac/memory/` —— 群级记忆 / 知识库 / Rule / Skill
  - `cosmac/bots/`、`cosmac/workflows/`、`cosmac/trading/`、`cosmac/profile/` —— 后续模块
  - `cosmac/tests/` —— GuDuu OS 自己的测试

> 注：`cosmac/` 目录在对应模块开工时再创建，不提前建空壳。

#### ⚠️ 独立仓库（不在本仓库里，改完要单独推）
- `GuDuu首页/` —— **官网 + 行业演示版**，独立仓库 **`GuDuuOS/guduu-website`（public，服务器免凭据拉取）**，本仓库已 gitignore 它。
  ⚠️ 公开仓库：往这里提交前确认**不含内部主机名/子域/机器代号/凭据**（2026-07-26 转公开前已清理过一轮 `config/app.ts` 注释）。
  纯静态站（Vue3+Vite，hash 路由），部署方式见该仓库自带的 `DEPLOY.md`（同事从 GitHub 拉取部署）。
  ⚠️ **在这个目录下改完代码，必须 `cd GuDuu首页 && git push`——它不会跟着主仓库一起推**。
  历史教训：官网曾长期只有本地 commit、从未配远程，产物直接 rsync 上服务器，代码只存在于本机硬盘（2026-07-26 补救）。

### 多模型抽象层（AI 后端可配置）
主 AI 背后的大模型**必须做成可插拔**：统一接口，支持 Claude / OpenAI / 本地模型等多后端，通过配置切换。不要把任何一家厂商的 SDK 调用散落在业务逻辑里——全部走 `cosmac/ai/` 的统一抽象。

### 数据存储分层（写持久化代码前先对照这张表）

> 铁律：**Synapse 已经存的东西绝不在 GuDuu OS 这边重存一份**（否则数据双写、必然不一致）。
> 只有 Synapse 存不下/搜不了的「AI 层自己的结构化/派生数据」，才进 GuDuu OS 自己的数据库。

| 数据 | 存哪 | 说明 |
|---|---|---|
| **聊天记录 / 消息 / 已读位** | 🚫 Synapse 的 PG | Matrix 本职，前端走 sync 拿。**不要**在 cosmac 再存一份。 |
| 账号、群组/成员、房间状态 | 🚫 Synapse 的 PG | 同上。 |
| **全局 AI 配置**（人设/模型/工具开关） | Matrix state event | 已实现：写在控制室 `cosmac.ai.config`（见 §9 / memory `ai-config-control-room`）。 |
| **每账号轻量配置** | Matrix per-user **account data** | 优先用它：每用户键值、自动同步到客户端、零新基建。撑不住结构化关联时再迁 DB。 |
| **全局 Skill / Agent 定义**（后台管理） | Matrix state event | 判断规则:有身份能接活→Agent;可复用套路/格式→Skill 绑 Agent(绝不全局注入)。 已定（负责人拍板）：存控制室 `cosmac.skills` / `cosmac.agents`，浏览器(管理后台)写、bot 读——**因为浏览器只能走 Matrix、够不到 DB**，与「全局 AI 配置」同套路。 |
| **群级 / 个人 Skill 与用户自建 Agent** | GuDuu OS DB | 聊天命令或前台「我的AI工坊」建的（scope=room/user，owner 隔离）；注入/名册时与全局合并、个人覆盖全局；**计入账号存储空间配额**。 |
| **知识库** | ✅ GuDuu OS DB + **pgvector** | 文档分块 + 向量检索(RAG)，state event 存不下也搜不了。**这是上 DB 的最硬理由**。 |
| **群级 / Agent 记忆**（摘要、长期记忆） | ✅ GuDuu OS DB | 派生数据，与原始聊天记录分开存。 |
| **工作流连接器定义**（模块3，后台编排） | Matrix state event | 已定：存控制室 `cosmac.workflows`（浏览器够不到 DB，同 Skill/Agent）。外部平台 key 只进服务端 env（`COSMAC_WF_<CRED>`），定义里只放凭据名。 |
| **社媒数据源定义**（数据看板真实取数：平台/账号/模式/凭据名/间隔） | Matrix state event | 进行中：按工作区存 `cosmac.social_sources`（同工作流连接器套路）。两种取数模式 api(官方平台 API)/crawl(AI Agent 走工作流爬)。API key/token/cookie 只进服务端 env `COSMAC_SOCIAL_<平台>_<字段>`，定义里只放凭据名。**P1 已落前端配置 UI**(看板「接入数据源」按钮)；采集器/写 DB/回看板是 P2~P4。取回的指标时序进 cosmac DB `cosmac_social_metric`。 |
| **入驻模板定义**（注册引导可选的「方案」：模型/人设/RULE/技能/知识库/频道/工作流/所需会员等级） | Matrix state event | 进行中：存控制室 `cosmac.onboarding_templates`（管理员后台「入驻模板」页写、首次引导读，同 skills/agents/workflows 套路）。**P1 已落后台管理 UI + 存储**；P2 引导接入(选模板→建工作区+绑 per-group Agent 让人设真生效+关联知识库)；P3 看板按模板渲染。付费模板靠 tier 字段 + 现有会员/门控体系。 |
| **资源可用范围**（技能/智能体的账号级权限） | 资源定义内 `access` 字段 + GuDuu OS DB | 已实现：每个全局技能/智能体带 `access`（''=所有人 / paid/creator=等级及以上 / admin / `tpl:模板key`=指定入驻模板用户），后台「技能库/智能体」页配，bot **服务端强制**（对话注入+能力名册按发起人过滤；群绑定=管理员显式授权不过滤）。「用户→模板」映射存 cosmac DB `cosmac_user_template`（引导完成经 `/cosmac/onboarding/select` 写入）。 |
| **会员等级**（账号权限分层：免费/付费/创作者） | Matrix state event | 已实现：存控制室 `cosmac.members`（同 admins 套路，管理员/bot 写、用户不可自改——付费门槛靠它）。**与「服务器管理员」正交**：管理员仍走 Synapse admin 标志。授予入口 `cosmac.members.MembersStore.grant`（**预留给模块4支付**）。枚举/校验见 `cosmac/members.py`。普通用户查自己等级走「DM 问 bot」命令`会员`（控制室只管理员可读）。 |
| **功能门控策略**（能力→最低会员等级） | Matrix state event | 已实现：存控制室 `cosmac.gating`，后台「会员权限」页逐项配，bot **服务端强制**（客户端只配置）。门槛阶梯 免费<付费<创作者<仅管理员；平台管理员永远不受会员门控。能力目录 `cosmac/members.py` GATE_CATALOG（ai_chat/knowledge/create_room/workflow_run；**新增功能往这加一条**，前后端各一份）。工具层经 `Toolbox.gate_check` 同样受控（防自然语言绕过命令）。 |
| 工作流运行记录（模块3）、交易（模块4）、个人主页（模块5） | ✅ GuDuu OS DB | 关系型。 |
| **OEM/Nexus 数据**（KEY·license、实例注册、token 钱包、用量计量、心跳遥测） | ✅ Nexus 独立 DB | 模块6：存**母舰侧**（GuDuu Nexus fleet 服务自己的 Postgres），与各 OEM 自部实例完全隔离；原厂 LLM key 只进网关 env，永不进发行版。 |

**基建决策**：GuDuu OS 的 DB **复用生产现成的 PostgreSQL**（Synapse 已在跑，见 `DEPLOY.md`），给 cosmac 服务**单开一个 database/schema**，按需装 **pgvector**。这走 §2 的第 3 条路径（新增独立服务/数据），与 Synapse 核心解耦、不碰它。

**实现约定**（`cosmac/db/`）：
- 用 **SQLAlchemy（同步）**——bot 是同步的（`ThreadingHTTPServer` + `requests`），DB 层也保持同步，别引入 async 复杂度。
- 连接由 `COSMAC_DATABASE_URL`（旧 `GUDUU_DATABASE_URL` 仍兼容） 配置：**生产**指向 Postgres（独立 db）；**本地开发**默认回退 SQLite 文件（`run/cosmac.db`），零基建即可跑测试。
- 知识库的 pgvector 是「Postgres 专属」能力：本地 SQLite 跑不了向量检索，相关功能要能在缺 pgvector 时优雅降级（或本地用 Postgres 容器）。

---

## 4. 功能路线图（一次只推一个）

| # | 模块 | 状态 | 说明 |
|---|------|------|------|
| 0 | 项目规范 (本文件) | ✅ 进行中 | — |
| 1 | **主 AI 控制层** | ✅ 完成 | 地基齐活：appservice bot 看到每条消息+自动进群+回消息（`cosmac/bots/`）；多模型可配置（echo/claude/openai/deepseek/gemini，无 key 自动降级 echo，`cosmac/ai/`）；AI 工具调用（建群/发消息/查成员/读记录）；后台 AI 配置经控制室热下发 + 服务器管理员↔控制室成员联动。后续增量工具按需补，不再算"开工中"。 |
| 2 | 群级 记忆/知识库/Rule/Skill | ✅ 完成 | 全套上线：Skill(数据/注入/命令/后台UI)、Agent(后台UI/群绑定/人设+模型+技能)、知识库(引擎/入库命令/RAG·线上实测)、Rule(平台硬约束)、记忆(短期对话 + 文档KB)。cosmac DB 已接生产 Postgres。增强项(长期记忆摘要/pgvector/知识库上传UI)按需再补 |
| 3 | Bot / 插件 / 工作流引擎 | ✅ 完成 | **定调：不自建引擎，对接外部平台**(n8n/Make/Coze/ComfyUI/Dify)。全套上线：通用连接器引擎(`cosmac/wf.py`，含 webhook/Dify/Coze/ComfyUI)+ 聊天命令 `工作流 列表/跑` + 主 AI 工具 `run_workflow` + 异步回调协议 + 运行记录入库 + **后台编排 UI**(`AdminView.vue` 工作流面板：4 平台连接器增删改查、凭据只填名)；定义走控制室 `cosmac.workflows`、密钥走服务端 env。**安全/健壮性"够用即止"**(负责人 2026-06 拍板)：单实例下真实风险(SSRF/密钥/鉴权/DoS/重复触发/崩溃可见性)全堵；**durable 任务队列 + 多实例 fencing + per-event 精确一次**记为**已知架构边界·本期不做**(单 bot 小规模属过度设计)。增强项(更多平台适配器/graph 上传 UI)按需再补 |
| 4 | 交易系统（会员订阅 + Token 经济） | 🟡 进行中 | **主线=会员订阅/充值 + Token 经济**（2026-07-23 定调：国内市场，渠道=支付宝+微信，Stripe/PayPal 不做）。**会员 P1 地基已落地+单测**(`cosmac/trading/`)：套餐(控制室 `cosmac.plans`)+订单(DB `cosmac_order`)+可插拔 `PaymentProvider`+幂等开通/顺延续费/会员到期+手动 mock 支付。**Token 经济 P1 ✅ 上线**(1.6.0，2026-07-26 负责人定稿口径：创作者 Agent 固定价/次+平台 AI 按真实用量×倍率、售价固定汇率+倍率后台可调吸收成本、**中心商城供货+各 OEM 实例销售**、本期只做收益账本不出金、token=单用途消费积分不可退现)：用户钱包+流水账(`cosmac_token_wallet/ledger`，原子守卫扣费)+真实计量(SDK `ResultMessage.usage`/openai/claude usage → `TurnResult.usage_tokens`)+每日免费额度(当天清零，两级扣减：免费→钱包)+充值包(控制室 `cosmac.token_config`，订单 kind=token 复用交易骨架)+前端(会员弹窗双页签「会员套餐/Token 充值」+后台「Token 经济」页)。**总开关默认关**(cosmac.token_config.enabled)，管理员豁免，计费异常 fail-open。**P2 创作者商城 ✅ 上线**(1.6.1)：创作者会员在工坊「上架·收益」把自建 Agent 上架定价(token/次,0=免费;`cosmac_market_listing`,引用制·人设不进橱窗·管理员可 banned)→商城「创作者 Agent」分类免费获取→频道 @它按次**硬前拦+回复后扣款**(与平台真实用量计费**二选一**;本人/管理员免)→**分成 90/10**(抽成 `platform_fee_pct` 后台可调,净得实时充创作者钱包,逐笔进 `cosmac_creator_earning` 收益账本,工坊可见;本期不出金)。**P3 认证+审核 ✅ 上线**(1.6.2，类公众号流程)：创作者须先**申请认证**(提交资料→付认证费 `creator_cert_fee_cents` 后台可配默认300元→管理员审核通过=授 creator 会员；**拒绝不退费、可免费重提**)；**任何上架/修改一律进待审**(status=pending，审核通过 on 才在售，拒绝带原因可重提，管理员审核可见人设全文)；后台「创作者审核」页双审核。数据：`cosmac_creator_application`(cert_repo)。**P4 Skill 上架 ✅ 上线**(1.6.3)：创作者技能按**一次性买断**卖(技能每轮自动注入、按次不可预期→获取时付清永久用；`MarketListing.kind='skill'`)，**先付后得**(余额不足明确失败不给货,与 Agent 后付语义不同)、买断即永久(移除重获取不重复扣,用收益流水反查)、买断技能进买家每轮 system 注入(创作者下架即失效)、分成与审核同 Agent。**剩余**：真实支付宝/微信接入(等商户号)；创作者提现出金(合规评估后单独接)。 |
| 5 | 个人主页 | ⬜ | 需要客户端 UI 配合 |
| 6 | **OEM 体系（GuDuu Nexus + GuDuu OS 发行版 + LLM 网关）** | 🟡 进行中 | **P0 发行版 ✅ 完成**（2026-07-19 干净 VM 端到端实测通过：样板间实例 `oem1.cosmac.cc` = 一键安装→自动 HTTPS→登录→引导建工作区→AI 回复全链路；`distro/` 四容器 compose + install/doctor/update + bootstrap 引导 + 客户端同源补丁）。下一步 **P1：GuDuu Nexus 母舰 + LLM 网关 + 皮肤系统**。**方案已定稿（2026-07-18，负责人逐项拍板）**：每 OEM **独立部署一套**（自己的服务器/域名/邮箱，docker 整栈发行版一键装，`server_name`=OEM 域名）；**完全白牌**（运行时皮肤，界面零平台标识）；KEY **买断（永久含升级）+ token 另充值**（钱包余额耗尽断 AI = 唯一续费抓手）；**原厂 LLM key 永不下发**，全部 AI 调用必经母舰 **LLM 网关**（平台 key 鉴权/逐请求计量/扣钱包/限流——对自部实例唯一的技术缰绳，也是全系统唯一单点，需高可用）；联邦 = **GuDuu 生态内互通**（Nexus 下发 federation whitelist，不接公网 Matrix）；大后台 **GuDuu Nexus** = 独立 console 前端 + fleet 服务（KEY 签发/实例注册/心跳遥测/token 钱包/数据大屏·实时树状图）。规模预期**上百家** → 兑码/下载/安装/激活**全自助**必须进 P1。分期：P0 整栈容器化 + install/doctor 脚本 → P1 Nexus + 网关 + 皮肤 + 自助闭环 → P2 大屏 + 联邦白名单 + 告警 + 最低兼容版本强制 → P3 接钱（硬依赖模块4 Stripe）。 |
| R | **品牌化 Matrix→GuDuu OS** | ⬜ 持续 | 贯穿全程的横切任务，按 §7 三层红线分层改，每碰到呈现层字样就顺手改 |

> 状态符号：⬜未开始 / 🟡进行中 / ✅完成。开工/完成时更新这张表。
> 已上线功能全貌见 **docs/FEATURES.md**(对外介绍/新人了解用;功能增减顺手更新)。

---

## 5. 开发约定（来自本仓库真实配置，写代码必须遵守）

- **语言**：Python（`^3.8`），热点路径有 Rust 扩展（`rust/`，PyO3）。
- **Lint / 格式**：`ruff`，行宽 **88**。提交前跑 `poetry run ruff check synapse/ cosmac/`。
- **类型检查**：`mypy`（配置见 `synapse/mypy.ini`）。新代码要带类型注解。
- **测试**：Synapse 用 trial。运行：`poetry run trial tests`（GuDuu OS 测试放 `cosmac/tests/`）。
- **Changelog（重要）**：Synapse 仓库每个改动都要在 `synapse/changelog.d/` 加一个文件，命名 `<PR号>.<类型>`，内容一句话（句号结尾）。类型：
  - `feature` 新功能 / `bugfix` 修复 / `doc` 文档 / `removal` 移除 / `misc` 内部改动 / `docker`
  - GuDuu OS 自己的代码（`cosmac/`）是否沿用 towncrier 待定；定下来之前先在 commit message 写清。
- **依赖**：用 Poetry 管理（`pyproject.toml` + `poetry.lock`）。
- **中文注释（强制）**：写代码时必须加**详细的中文注释**，越细越好。
  - GuDuu OS 新代码（`cosmac/`）：每个模块/类/函数都要有中文 docstring 说明"这是干嘛的、参数啥意思、返回啥"；关键逻辑行内也要中文注释解释"为什么这么写"。
  - 改/调用 `synapse/` 时：在改动处加中文注释说明意图（方便以后定位 GuDuu OS 的改动）。
  - 注释解释**意图和原因**，不要只复述代码字面意思。专有名词（如 appservice、event）可保留英文。

### 客户端路由约定（URL routing，写前端必守）

> 背景：真实客户端的根组件是 `client/src/views/LiveView.vue`（`main.ts` 直接挂它，**不走 `<router-view>`**）。导航靠 LiveView 内的**集中式 URL 双向同步**，不是常规 router-view 路由。

- **每个"页面级"视图必须有独立地址**，支持浏览器后退/前进、刷新留在原页、深链直达。已接：数据看板 `/s/:space/board`、任务看板 `…/tasks`、频道 `…/c/:roomId`、管理后台 `/admin`、个人主页 `/me`。
- **哪些接路由**：占据主区/全屏、用户会想刷新留存或分享的"页面"才接。**临时态不接**——菜单、各种设置/新建/成员弹窗、侧栏折叠、AI 侧栏、专注模式、工具弹窗（市场/插件商城/资产/CLI）。判断不准就先**不接**，问负责人。
- **怎么接新视图**（三步，别改既有点击 handler）：① 导航状态收敛到 setter（`selectSpace/openBoard/openTasks/openRoom + adminOpen/profileVisible` 那套）；② 在 LiveView 的 `computePath()`（状态→地址）和 `applyFromRoute()`（地址→状态）各加一条分支，并把新状态加进那个 `watch([...])` 数组；③ `router/index.ts` 补一条指向 `Blank` 的路由（仅为让 hash 合法、不被 catch-all 弹回 `/`；component 永不渲染）。
- **用 hash history**（`/#/...`），不要切 history 模式——否则线上要改 nginx try_files 回退。
- 详见 memory `client-root-is-liveview`。

---

## 6. 给 AI（Claude）的工作守则

0. **全程用中文沟通（强制）**：所有跟负责人的对话、思考过程说明、进度汇报、结论、报错解读、部署说明——**一律用中文**。不要用英文/日文等其他语言写给负责人看的内容（含"过程叙述"）。专有名词（appservice、event、nginx、systemctl 等）可保留英文原词，但包裹它们的句子必须是中文。代码里的注释另有规定（见 §5「中文注释」）。
1. **开工前先读本文件**，对齐架构和路线图。
2. **动 `synapse/` 核心前先停下来确认**——优先找 Module/Appservice 方案；真要改核心，先问负责人，再登记 §8。
3. **一次只做路线图里的一个模块**，不主动扩散到别的模块。
4. 改动后：跑 lint + 相关测试；动了 `synapse/` 就补 changelog。
5. **保持本文件最新**：架构/路线图/核心改动一旦变化，先更新 CLAUDE.md。
6. 不确定的产品决策，问负责人，不要自己拍板大方向。
6.5 **修 Bug 先排查配置层（负责人定的规矩）**：收到"AI 行为不对"类报告时，不要直接当代码 bug 修。先依次排查：① 该频道的 RULE（条目规则 + 规则文档）是否本身就导致了这个行为；② 频道绑定的知识库/技能/Agent 内容是否是问题来源；③ 是否是"频道 AI ↔ 主 AI（中枢）"的边界问题（该频道回答用了不该用的作用域，或反之）。排查手段：后台频道详情页 / 控制室 state event / `cosmac.channel_config`。确认配置无辜后，再动代码；若是配置问题，改配置并告知负责人，不写代码。
7. **每完成一个可用版本就自动「提交 → 推送 → 给部署命令」，不用等催。** 客户端（`client/`）功能做好且本地 preview 验证通过后，依次：
   - ⓪ **按版本规则升号并写笔记**（详见 `docs/VERSIONING.md`、`.cursor/rules/versioning.mdc`）：SemVer 语义——**PATCH** 有交付就勤涨、**MINOR** 本周有可对外增量再涨（争取每周打包一次）、**MAJOR** 仅破坏性/代际（不强制每月涨）；对齐 `cosmac.__version__` 与 `client/package.json`；`DEVLOG.md` 顶条必须为 `## YYYY-MM-DD — GuDuu OS X.Y.Z (patch|minor|major)`，正文用「新增/修复/优化/变更」分类；不记敏感信息（key/IP 进 `DEPLOY.md`）。
   - ① 重建产物：`cd client && npm run build`（`client/dist` 被 .gitignore，提交用 `git add -f client/dist`）；
   - ② `git commit` + `git push origin main`：发版 commit 第一行必须为 `release: GuDuu OS X.Y.Z (patch|minor|major)`，正文与 DEVLOG 用户可见条目对齐；推荐打 tag `vX.Y.Z`。
   - ③ **直接 SSH 部署阿里云生产**（负责人 2026-07-22 拍板：只维护阿里新站，GCP 老站已废弃）：`ssh guduu-cn` → `/root/cosmac` 拉代码（GitHub 间歇性 TLS 失败要带重试判真实退出码）→ `/opt/cosmac/distro/update.sh`（自动同步 /opt + docker 重建 + 滚动重启）→ `doctor.sh` 体检。Claude 直接执行，不再给负责人贴命令。细节见本机 `DEPLOY.md` 与 memory `cn-server`。
   - 纯后端操作（真建 / 整理 Matrix 频道等，只改服务器数据、不动 `client/` 代码）不必走部署，但要说明"无需部署"。
7.5 **「拉取本周/本月变更说明」**：从区间内 `release:` commit + `DEVLOG.md` 归并，按新增/修复/优化/变更输出可直接对外用的更新文案并标明版本跨度（见 `docs/VERSIONING.md` §7）。**维护感靠勤 PATCH + 周报/月报**，月报不要求伴随 MAJOR。

---

## 7. 品牌化规则：Matrix/Synapse → GuDuu OS（三层红线）

> 把"给人看的品牌"换成 GuDuu OS，但**绝不动机器之间的协议**。改之前先判断属于哪一层。

| 层 | 包含什么 | 规则 |
|---|---|---|
| **① 协议层 🚫 绝对不改** | `/_matrix/...` API 路径、`m.*` 事件类型（如 `m.room.message`）、联邦协议格式、`.well-known` 里的协议字段、状态事件 type | **一个字都不能改**。改了客户端连不上、联邦崩、Element 不可用 |
| **② 呈现/品牌层 ✅ 改成 GuDuu OS** | 产品名、欢迎页"Synapse is running"、系统通知(server notices)、邮件/通知模板、面向用户的文档、日志中的品牌字样、默认 `server_name`/`user_agent`、管理后台标题 | 放心改 |
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
GuDuu OS 服务依赖见 `cosmac/requirements.txt`。

---

## 8. 核心改动记录 (Synapse core modifications log)

> 任何对 `synapse/` 核心的改动登记在此：日期、文件、原因、是否可改成 Module 方案。

（暂无）
