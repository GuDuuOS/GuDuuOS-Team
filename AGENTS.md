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
| **OEM/Nexus 数据**（KEY、实例、钱包、心跳、版本发布与逐节点升级状态） | ✅ Nexus 独立 DB | 母舰侧独立保存，与各 OEM 的 Synapse/cosmac 数据库隔离；版本发布只下发严格 Git tag，不保存客户 SSH 凭据。 |

**基建决策**：GuDuu OS Star 的 DB **复用生产现成的 PostgreSQL**，给 cosmac 服务**单开一个 database/schema**，按需装 **pgvector**。走 §2 的第 3 条路径，与 Synapse 核心解耦、不碰它。

**实现约定**（`cosmac/db/`）：用 **SQLAlchemy（同步）**（bot 是同步的，别引入 async）；连接由 `COSMAC_DATABASE_URL`（旧 `GUDUU_DATABASE_URL` 仍兼容） 配置，生产指向 Postgres、本地默认回退 SQLite（`run/cosmac.db`）；pgvector 是 Postgres 专属，本地缺它时相关功能要优雅降级。

---

## 4. 功能路线图（一次只推一个）

| # | 模块 | 状态 | 说明 |
|---|------|------|------|
| 0 | 项目规范 (本文件) | ✅ 进行中 | — |
| 1 | **主 AI 控制层** | ✅ 完成 | 地基齐活：appservice bot 看到每条消息+自动进群+回消息（`cosmac/bots/`）；多模型可配置（echo/claude/openai/deepseek/gemini，无 key 自动降级 echo，`cosmac/ai/`）；AI 工具调用（建群/发消息/查成员/读记录）；后台 AI 配置经控制室热下发 + 服务器管理员↔控制室成员联动。后续增量工具按需补，不再算"开工中"。 |
| 2 | 群级 记忆/知识库/Rule/Skill | ✅ 完成 | 全套上线：Skill(数据/注入/命令/后台UI)、Agent(后台UI/群绑定/人设+模型+技能)、知识库(引擎/入库命令/RAG·线上实测)、Rule(平台硬约束)、记忆(短期对话 + 文档KB)。cosmac DB 已接生产 Postgres。增强项(长期记忆摘要/pgvector/知识库上传UI)按需再补 |
| 3 | Bot / 插件 / 工作流引擎 | ✅ 完成 | **定调：不自建引擎，对接外部平台**(n8n/Make/Coze/ComfyUI/Dify)。全套上线：通用连接器引擎(`cosmac/wf.py`，含 webhook/Dify/Coze/ComfyUI)+ 聊天命令 `工作流 列表/跑` + 主 AI 工具 `run_workflow` + 异步回调协议 + 运行记录入库 + **后台编排 UI**(`AdminView.vue` 工作流面板：4 平台连接器增删改查、凭据只填名)；定义走控制室 `cosmac.workflows`、密钥走服务端 env。**安全/健壮性"够用即止"**(负责人 2026-06 拍板)：单实例下真实风险(SSRF/密钥/鉴权/DoS/重复触发/崩溃可见性)全堵；**durable 任务队列 + 多实例 fencing + per-event 精确一次**记为**已知架构边界·本期不做**(单 bot 小规模属过度设计)。增强项(更多平台适配器/graph 上传 UI)按需再补 |
| 4 | 交易系统（会员订阅） | 🟡 进行中 | **主线=会员订阅/充值**，多渠道支付(Stripe/PayPal/USDT/支付宝/微信)按 IP 地理路由，范围"较完整"。**P1 地基已落地+单测**(`cosmac/trading/`)：套餐定义(控制室 `cosmac.plans`)+ 订单(DB `cosmac_order`)+ **可插拔支付抽象** `PaymentProvider`(密钥只进 env)+ 订单服务(下单/支付成功**幂等**开通/**续费按原到期日顺延**)+ 会员**到期**(扩 `members.py`：grant 带 expires_ts、查等级自动判过期)+ 手动/mock 支付(HMAC 验签)。**分期**：P2 Stripe 全链路+webhook+前端套餐页；P3 PayPal/USDT+地理路由；P4 支付宝/微信+对账/退款。 |
| 5 | 个人主页 | ⬜ | 需要客户端 UI 配合 |
| 6 | **OEM 体系（GuDuu Nexus + 发行版）** | 🟡 进行中 | 当前增量：完善 Nexus 超级管理员工作台。后台采用左侧功能导航，把舰队总览、版本管理、节点实例、授权申请、OEM 客户、支付订单和只读数据大屏分区呈现；舰队总览加入资金经营视角，展示累计实收、近 30 天实收、待支付、授权码/Token 充值收入构成与支付渠道接入状态，金额只以服务端已确认 `paid` 的订单计入收入，支付宝/微信 API 未接入前明确显示“待接 API”，绝不伪造流水；新版本表单根据当前产品版本与 `DEVLOG.md` 自动生成版本号、Git tag、标题和面向 OEM 的更新说明，仍默认“未发布”；超级管理员维护永久历史版本列表，发布流程为“未发布→灰度监测→全量发布→暂停”，并可选择已发布过的旧版本发起全节点回撤。节点升级成功后，同一份版本说明由成功投放记录自动呈现在对应 OEM 门户，作为更新公告（不向客户业务群自动发消息）。节点更新仍由宿主代理按 KEY 主动拉取，禁止 Nexus 主动 SSH OEM 服务器，也禁止给 bot 容器宿主机控制权。 |
| R | **品牌化 Matrix→GuDuu OS Star** | ⬜ 持续 | 贯穿全程的横切任务，按 §7 三层红线分层改，每碰到呈现层字样就顺手改 |

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
   - ③ **直接 SSH 部署 Google Cloud 生产实例**（负责人 2026-07-31 拍板：停止向已退役云环境部署，只维护新建的 Google Cloud 实例）：通过负责人提供的固定外部 IP、SSH 用户与密钥登录 → 在确认后的生产仓库目录拉取 `main` → 执行部署更新脚本 → 运行体检脚本并核对公网服务。AI 直接执行，不再给负责人贴命令。**新实例连接信息、部署路径和域名确认前，不得沿用 `DEPLOY.md` 中旧 GCP 实例的 IP 或路径。** 信息确认后同步更新 `DEPLOY.md`。
   - 纯后端操作（真建 / 整理 Matrix 频道等，只改服务器数据、不动 `client/` 代码）不必走部署，但要说明"无需部署"。
7.5 **「拉取本周/本月变更说明」**：从区间内 `release:` commit + `DEVLOG.md` 归并，按新增/修复/优化/变更输出可直接对外用的更新文案并标明版本跨度（见 `docs/VERSIONING.md` §7）。**维护感靠勤 PATCH + 周报/月报**，月报不要求伴随 MAJOR。

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
