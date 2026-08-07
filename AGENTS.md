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
│  共享 Vue 客户端 → Web / Electron 桌面 / Capacitor 手机   │
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
- `client/` —— GuDuu OS Star 的**唯一客户端业务源码**。后续在目录内逐步形成
  `apps/web`、`apps/desktop`、`apps/mobile` 与共享 `packages/`；桌面和手机壳不得复制
  一套业务代码另行维护。

> 注：`cosmac/` 目录在对应模块开工时再创建，不提前建空壳。

### 多模型抽象层（AI 后端可配置）
主 AI 背后的大模型**必须做成可插拔**：统一接口，支持 Claude / OpenAI / 本地模型等多后端，通过配置切换。不要把任何一家厂商的 SDK 调用散落在业务逻辑里——全部走 `cosmac/ai/` 的统一抽象。

### 多端客户端架构（2026-08 定稿；开发期）

> 目标：网页版、桌面 App、手机 App 使用同一套业务能力与同一份 Vue/TypeScript
> 源码，避免 Web、Swift、Kotlin 三套实现长期互相追赶。任何历史原生 iOS/Android
> 试验工程均不作为正式客户端地基，除非负责人以后明确重新启用。

**技术路线（强制）**：

- Web：Vue 3 + TypeScript + Vite。
- 桌面：Electron，覆盖 macOS / Windows；Linux 后续按需求补。
- 手机：Capacitor，覆盖 iOS / Android。
- Matrix 首期统一走 `matrix-js-sdk`；必须把 Matrix 能力收口到可替换的
  `MatrixPort`/adapter，未来如确有性能、后台同步或原生加密需求，可增加 Matrix Rust
  SDK 原生桥，但不得因此重写 AI、任务、知识库、会员等业务 UI。
- Electron 与 Capacitor 只负责系统壳和原生能力（安全存储、推送、文件、深链、托盘、
  生物识别等）；**业务规则、权限判断和页面数据流不得散落进 Swift/Kotlin/Electron
  main 进程**。

**桌面应用商城合规（从第一行桌面代码起执行）**：

- Electron 只使用官方仍处于支持期的稳定版，跟进 Electron 官方“最近三个稳定大版本”
  安全支持窗口；renderer 只执行随安装包签名封装的本地 Vue 代码，不把生产网站当远程
  壳加载，也不得从服务器下载 JS/CSS 来新增或显著改变功能。
- Electron 主窗口必须 `sandbox: true`、`contextIsolation: true`、`nodeIntegration: false`、
  `webSecurity: true`；禁止 `<webview>`，限制导航/新窗口/外部协议，IPC 校验 sender，
  preload 只暴露逐项命名的最小 API，并在打包时关闭不需要的 Electron fuses。
- macOS 同时维护官网直装与 Mac App Store 两个包装目标：直装版走 Developer ID +
  notarization + 自有更新；商城版必须使用 Electron `mas` 构建、Apple App Sandbox、最小
  entitlement 与商城更新，禁止在 MAS 包内启用自有 updater。摄像头、麦克风、文件等能力
  只有真实功能使用时才加权限说明和 entitlement，禁止为“以后也许用”提前索权。
- Windows 同时维护官网直装与 Microsoft Store 两个包装目标：官网版使用标准用户级安装
  且不得要求管理员权限；商城首选 MSIX，Package Identity/Publisher 在发布期从 Partner
  Center 注入，禁止写死个人证书。正式候选必须在 Windows CI/真机运行 Windows App
  Certification Kit；Store/MSIX 包走商城更新，官网包才可走自有更新。
- 直装版、MAS版、MSIX版共享同一产品版本、commit 和 Vue 产物摘要，但产物、签名、权限
  与更新通道严格分开；开发期允许生成未签名本地包，不得把测试证书或占位 Publisher
  当成正式身份。

**目标目录（按模块开工逐步迁移，不提前建空壳）**：

```text
client/
├── apps/
│   ├── web/          # 网页入口
│   ├── desktop/      # Electron main/preload/打包配置
│   └── mobile/       # Capacitor 配置及 ios/android 原生壳
└── packages/
    ├── core/         # 认证、Matrix、cosmac API、缓存
    ├── contracts/    # OpenAPI 类型、事件、权限/版本契约
    ├── features/     # 聊天、AI、任务、KB、会员、后台等业务
    ├── ui/           # 跨端设计系统与通用组件
    └── platform/     # Web/Electron/Capacitor 能力接口
```

**共享与布局边界**：

- 功能和数据契约必须一致，但不要求三端像素级相同。桌面保持工作区/频道/主内容/AI
  多栏布局；手机采用底部导航和单页推进；平板按宽度恢复分栏。
- 页面不得依赖固定桌面宽度。新功能必须同时给出 desktop / tablet / mobile 三档行为；
  大表格、看板和管理后台在手机上必须提供列表/详情模式，不能只靠横向滚动凑合。
- `client` 内禁止组件到处直接 `fetch()`；Matrix 与 cosmac 调用分别收口到共享 client，
  服务端 API 优先用 OpenAPI 生成类型，权限仍以服务端为准。
- 同一产品版本只构建一次共享 Vue 产物；未来进入发布期时，Web、Electron、Capacitor
  必须消费同一 commit、同一前端产物摘要，禁止各平台从不同分支独立重建。

**跨端安全底线**：

- 不把 Matrix access token 长期留在普通 `localStorage`：Web 使用受控会话策略；桌面用
  Electron `safeStorage`；iOS 用 Keychain；Android 用 Keystore。
- 桌面凭据必须由 Electron main 进程通过异步 `safeStorage` 加密后写入应用私有
  `userData`，renderer 只能调用逐项命名的会话仓库 API；IPC 必须校验 sender、参数形状和
  大小上限。系统加密暂不可用时登录保存要明确失败，禁止回退明文。`localStorage` 只允许
  保存当前用户 ID、账号显示名等非敏感路由元数据；首次升级应把历史 token/deviceId
  一次性迁入安全仓库并删除旧明文，迁移失败不得提前删除原会话。
- Electron 必须开启 sandbox、context isolation，renderer 禁止直接获得 Node 权限；
  preload 只暴露最小白名单桥。
- 正式聊天客户端必须明确并验证 Matrix E2EE/Rust Crypto、独立 device ID、密钥恢复、
  加密附件和多端验证，不得出现 Web 能读而 App 不能读（或反之）的房间。
- 手机推送走 APNs/FCM + Matrix push gateway；密钥只留在 CI/服务端安全配置，不能进入
  Vue 包或 OEM 配置。

**OEM 客户端原则**：

- “GuDuu OS”为平台保留品牌，只有 Nexus 激活实例 #1、#2、#3
  可作为节点产品名使用。其他 OEM 必须配置自有产品名与 Logo，后端必须根据
  服务器持久化的激活实例号强制校验，禁止只靠前端隐藏或可篡改字段判断。
- 缺省提供一个 GuDuu OS 通用 App，通过输入域名、邀请链接或二维码连接不同 OEM；
  依次读取标准 `/.well-known/matrix/client` 和 GuDuu 客户端配置端点，动态加载
  homeserver、Logo、主题、功能开关、帮助/隐私地址。
- 大型 OEM 可购买独立白标安装包，但必须由同一源码和 CI 根据受签名的 tenant manifest
  生成，禁止复制客户分支。桌面可生成独立名称/图标/更新通道；手机白标涉及独立
  Bundle ID、签名和商店条目，发布期再单独启用。
- 客户端下发的租户配置只能提供数据和样式，禁止下载并执行可改变 App 功能的远程代码。

**更新分类（开发时就要遵守）**：

1. 服务端数据/配置（Agent、Skill、工作流、套餐、规则、OEM 主题）应让已安装客户端
   直接同步，通常不要求重新打包。
2. Vue 界面或共享业务代码变化，未来发布期必须形成同一版本的 Web、Desktop、iOS、
   Android 产物；后端至少兼容当前与前两个重要客户端版本，并用按平台最低版本的
   feature flag 避免商店审核时间差导致功能断裂。
3. 推送、权限、支付、安全存储等原生桥变化只重建受影响平台，但仍登记在同一产品版本
   清单中；会员权益永远以服务端幂等订单/凭据验签后的状态为准。

**下载与发布预留（当前禁止实施）**：

- 未来官网统一入口预留为 `https://www.guduu.co/download`，稳定下载域名预留为
  `https://download.guduu.co`；桌面不可变安装包放独立对象存储 + CDN，Nexus 只保存
  版本、摘要、状态和链接，不把大文件写入 PostgreSQL、Docker Registry 或系统盘。
- 未来稳定链接按平台重定向到带版本号的不可变文件；官网同时展示 macOS/Windows、
  App Store、Google Play、网页版和 OEM 邀请二维码。通用 OEM 下载链接负责选择租户，
  不为普通 OEM 复制安装包。
- 客户端发布未来使用独立 `client` 轨道，不混入现有 `nexus`/`node` 双轨；版本状态、
  商店审核、灰度、自动更新、回滚和下载地址在负责人明确启动发布阶段后再补入 Nexus。
- **当前处于开发设计期**：在负责人明确说“开始发布/上架桌面和手机 App”之前，禁止
  创建 App Store/Google Play/Microsoft Store 等正式条目，禁止申请或写入生产签名凭据，
  禁止上传安装包、开放公开下载地址、启用桌面自动更新 feed、创建 Nexus `client`
  发布轨道或执行任何商店提交。允许本地原型、模拟器/真机调试、测试签名、内部构建和
  自动化测试；现有 Web 与 OEM 节点的正常发布规则不受此门禁影响。

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
管理或恢复凭据；灾难恢复改为从服务器 SSH 生成短期、单次使用的恢复码，数据库
只保存恢复码哈希，使用或过期后立即作废并写审计。

**Nexus平台主管分权（2026-08）**：具名管理员分为超级管理员、运营、财务、发布与
只读审计五类。运营只处理 OEM、节点、授权与 KEY；财务只处理经营数据、订单、提现与
支付配置；发布只处理不可变清单、灰度、全量和回撤；只读审计可查看各业务面板与审计
记录但不能写入。角色判断必须在服务端逐接口执行，前端菜单隐藏不构成权限边界；角色
变化立即撤销该账号旧会话，且任何时候都必须至少保留一个有效超级管理员。

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
| 7 | **多端客户端（Web / Desktop / Mobile）** | 🟡 进行中 | 当前增量：macOS/Windows Electron 安全壳和四类包装目标已建立；Matrix access token、多账号会话和 device ID 已从桌面 `localStorage` 迁入 Electron `safeStorage`，旧明文支持安全迁移；新私信已接入受校验、限流的 macOS/Windows 系统通知；工作区邀请已接入受白名单保护的 `guduu://join/<Matrix Space ID>` 深链，支持冷启动、已运行实例、renderer 重载和登录后续跳；安装包内实例品牌、节点设置与更新 API 已收口到当前 homeserver 绝对地址，并由桌面合规检查禁止相对 `/cosmac` 请求回归；通用桌面 App 已支持在登录页输入 OEM 域名，经 main 进程安全读取 Matrix `.well-known`、验证版本端点并加载受限公开品牌，未登录选择不进 `localStorage`，登录后 homeserver 随会话进 `safeStorage`。Web 继续走共享适配层，手机端后续走 Capacitor iOS/Android。当前只允许本地开发、测试与未签名构建；安装包公开发布、应用商城、下载入口、自动更新及 Nexus `client` 发布轨道必须等负责人明确启动发布阶段。 |
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

> **Nexus 历史版本基线（2026-08）**：版本中心使用 ``archived`` 保存已经结束、
> 不再允许重新发布的真实历史基线；后台默认折叠展示。只有具备 Git tag、实际部署记录、
> 已发布公告或节点当前版本证据的记录才能归档，不能把无镜像、无投放的临时草稿伪装成
> 历史版本。仍承担新安装回退职责的稳定节点版本必须保持 ``published``，候选版本在灰度
> 验收前保持 ``draft/canary``；归档不会创建节点任务，也不会向 OEM 重发旧公告。

> **Nexus 发布草稿自动化（2026-08）**：受信 CI 上传带不可变镜像 digest
> 的发行清单时，Nexus 同一事务内为该版本创建 `node + container`
> 未发布草稿，标题和说明从当前 `DEVLOG.md` 对应版本抽取，并自动给固定灰度
> 节点创建唯一安装任务。重放相同版本与清单必须幂等，不得覆盖管理员已编辑的
> 草稿或重复建任务；正式生产发布和回撤仍必须由具名管理员人工确认。

> **Nexus 节点环境与灰度门禁（2026-08）**：节点 #1 是负责人开发节点，
> 永不接收自动灰度、正式发布或回撤任务；节点 #2 是公司技术灰度节点，只有
> “节点运行代码发生变化且确实构建了新镜像”的版本，才在 CI 冻结双仓 digest
> 后自动收到候选任务；节点 #3 是官网正式节点，尚未部署时发布必须明确失败，
> 部署后也只有节点 #2 上报安装成功，超管才能人工把同一份 digest 发布给 #3。
> Nexus 集中平台的页面、审批、版本管理等控制面修改不构建节点镜像，只提交
> GitHub 并部署中央 Nexus；纯文档和不进入节点运行包的修改也不建镜像。
> 以后扩容时通过“平台设置”的持久化策略调整三类编号，任何节点不得同时属于
> 两个环境，浏览器选择器和服务端发布状态机必须同时执行该边界。
> 新服务器安装的“新装基线”与正式节点投放状态分开：只有固定节点 #2
> 已上报同一不可变摘要安装成功后，发布管理员才能明确将该版本设为
> 新装基线；该操作不会给节点 #3 创建升级任务。暂停该版本时必须同时撤销
> 新装基线，新节点回退到上一个可用正式版，禁止安装器猜测“最新版”。

> **Nexus 运营一致性与清理（2026-08）**：AI 网关在原厂请求成功后先把
> 用量写入持久化 outbox，再以同一事务“扣 Token + 标记已应用”；结算
> 短暂失败保留 `pending` 并由后续请求和定时维护安全重试，禁止因重放
> 重复扣费。每小时维护任务同时清理过期会话、验证挑战和过保心跳/统计，
> 但永不删除未结算的 outbox 任务。

> **Nexus 请求观测口径（2026-08）**：网关的成功与失败请求都写入 PostgreSQL
> 分钟桶，“今日调用”必须统计两者之和，不能再用仅含成功计量的 Token 账本代替。
> 成功请求延迟同时写入固定边界直方图，大屏 P95 从真实直方图累计计算并明确显示
> 为桶边界估值，禁止使用“平均值乘常数”等伪造算法。近 5 分钟 req/s 也只由同一
> 请求桶计算；CPU、磁盘、数据库容量、可用率等未接遥测的数据继续显示 `—`。
> 分钟桶与延迟直方图保留 180 天后由维护任务同步清理，不得影响审计、账务与流水。

> **Nexus Docker 镜像发布（2026-08）**：OEM 节点应用采用两阶段发布。
> 第一阶段由 GitHub Actions 在严格 ``vX.Y.Z`` tag 上构建 bot/web 镜像并推送 GHCR，
> Nexus 只接受带独立 HMAC 签名、五分钟时效的构建清单；发布记录冻结
> ``仓库@sha256:digest``、源码 commit 与平台信息，禁止只下发可移动 tag。
> 第二阶段由 OEM 宿主机更新代理主动拉取精确摘要，在切换前备份 PostgreSQL、保留当前
> 容器镜像为本机回撤点，校验 Caddy 配置后仅重建 bot/web；体检失败必须自动切回原镜像
> 并上报失败，成功后才持久化新摘要。数据库、Synapse、Caddy 证书与 OEM ``.env``
> 继续留在宿主机持久化目录，镜像不得包含客户配置或数据。GHCR 的 bot/web
> 发行包必须允许匿名只读拉取，禁止要求 OEM 客户注册 GitHub 账号或手工配置
> 共享 Token；可使用权仍由 OEM 授权与节点激活门禁控制。CI 写入凭据只留在 GitHub
> Actions，Nexus、安装脚本、bot 容器和版本清单均不得保存任何镜像仓凭据。
> 既有版本与更新器/Compose 自身升级继续兼容严格 Git tag；这是明确的
> bootstrap/灾备路径，不是日常应用发布方式，也不得给 bot 容器 Docker socket。
> **宿主工具与应用镜像必须分轨**：按 digest 切换 bot/web 不会也不得覆盖宿主机上的
> ``update_agent.py``、``apply_images.py``、systemd 单元或 Compose 运维文件。上述宿主
> 工具发生兼容性或安全语义变化时，必须随严格 Git tag 提供一次性、可审计的宿主迁移
> 引导，迁移前备份旧文件、持锁避开正在执行的升级、保留 OEM ``.env``/数据/反代定制，
> 且不得顺带重建或切换应用容器。新节点安装器直接安装最新宿主工具；存量节点完成该
> 一次迁移后，日常版本仍只走不可变镜像摘要。

> **Nexus 三镜像仓（2026-08）**：GHCR 继续作为 CI 构建和公开灾备主仓；
> 同一次 GitHub Actions 构建必须把完全相同的 bot/web 多架构 manifest 同时推送到
> 官方 Docker Hub 个人命名空间 `docker.io/guduu/`，并按不可变 digest 同步到平台自建的
> `registry.guduu.co`，禁止为任一副仓重新构建或只镜像可移动 tag。自建仓运行在
> Nexus 宿主机的独立容器中，数据只写入单独挂载的 Google Cloud Persistent
> Disk，不得占用 Nexus 系统盘或进入 Nexus PostgreSQL 备份。镜像同步与清理
> 由宿主 systemd 任务执行；Nexus Web 进程、bot 容器与 OEM 容器都不得获得
> Docker socket 或镜像仓写凭据。Nexus 以受信 GHCR 摘要为唯一清单事实源，并由同一
> 摘要推导 Docker Hub 与自建仓精确引用；新安装器和宿主更新代理默认优先拉 Docker
> Hub，以便国内服务器使用标准 Docker 镜像加速器，失败后整组回退自建仓，最后回退
> GHCR。三条路径都必须校验相同 manifest digest，bot/web 也不得混用不同来源。
> Docker Hub 两个仓库、自建仓与 GHCR 都必须允许匿名只读，并同时提供严格
> ``vX.Y.Z`` 与 ``X.Y.Z`` 两个版本 Tag，方便
> 人工排查和标准工具拉取；自动更新和回撤仍必须使用清单冻结的 ``@sha256:digest``，
> 禁止依赖可移动 Tag，也禁止发布 ``latest``。Docker Hub 写入 Token 只允许保存在
> GitHub Actions Secrets；自建仓同步写入账号只留在 Nexus 宿主 root 权限文件，安装器、
> Nexus API 与 OEM 节点不得保存任何仓库写凭据。任一单仓故障都不得阻断已批准发布。

> **OEM 节点首次配置向导（2026-08）**：新节点安装并由初始管理员首次进入后台时，
> 必须先完成服务器级配置向导，再进入日常管理界面。向导统一覆盖产品名称、Logo、
> 发信邮箱与主 AI 提供方/API；完成后这些项目仍可从“系统设置”重复修改。节点 `.env`
> 只保存授权、数据库、appservice 等启动基础设施，禁止再保存或透传 SMTP、主 AI
> provider/model/API Key 和支付业务凭据；官方 OEM 节点也不得因数据库缺失或读取失败
> 回退旧环境变量。非 OEM 本地开发可保留兼容回退，但不得影响发行版。
> 品牌公开字段可由同域公开配置端点提供给登录页，SMTP 密码、模型 API Key 和支付密钥
> 必须使用安装时生成的节点设置主密钥加密后写入 cosmac PostgreSQL，接口只返回“已配置”
> 标记，禁止把密钥写入 Matrix state、浏览器存储、镜像或日志。Matrix 控制室只保存主 AI
> 人设与工具开关，不得再保存 provider/model。首次向导和系统设置允许提前填写支付宝、
> 微信支付凭据，但在真实下单、回调验签、幂等履约和沙箱联调完成前必须明确标为
> “待适配器与沙箱交易验收”，不得出现测试支付、模拟成功入口，也不得因为保存过凭据就
> 标记为可收款；客户日常购买页仍须隐藏尚未上线的支付渠道。
> 主 AI 必须明确提供 Nexus 网关与 OEM 自有 API 两种模式，保存后由 bot 热读取节点数据库，
> 不要求客户 SSH 修改 `.env`。支付宝和微信支付是两套可同时启用的独立配置：支付宝保存
> APPID、RSA2 应用私钥、支付宝公钥与通知地址；微信支付 v3 保存商户号、AppID、商户证书
> 序列号、APIv3 密钥、商户私钥、平台公钥/公钥 ID 与通知地址。所有私钥、APIv3 密钥和
> 验签公钥都按敏感值加密，管理接口只返回逐字段“已配置”标记；节点支付 adapter 只能从
> 服务端运行时读取，绝不从浏览器、Matrix state 或旧环境变量拼接。

> **OEM 节点可选升级（2026-08）**：Nexus 对客户节点只发布更新信息和不可变镜像清单，
> 不把“已分配更新”解释为立即安装。宿主更新代理默认仅缓存通知，必须由节点管理员明确
> 选择“立即更新”后才拉取镜像；允许选择稍后处理或忽略当前版本。内部灰度节点 #2 可由
> 公司技术人员显式启用自动安装候选版本，其他节点缺省关闭。任何模式都保留摘要校验、
> 数据库备份、健康检查和失败自动回撤；Nexus 禁止主动 SSH，也禁止强制升级客户节点。

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

> **Nexus OEM API 与 Token 解耦（2026-08）**：节点授权默认不附赠
> 平台 Token，OEM 可自由选择自己的 AI API 接入方。超管“平台设置”
> 提供独立开关，缺省关闭；关闭时 OEM 申请表、列表和商品说明
> 不展示附赠额度，服务端在申请、审批与付款履约三个阶段都强制归零。
> 开启只恢复“可选的平台附赠”，不得将节点授权与任一模型厂商绑定；
> Token 充值作为选择平台 API 的独立服务继续保留。

> **Nexus KEY 部署绑定（2026-08）**：OEM 申请节点授权时必须填写计划部署域名，
> 审批或支付履约签发 KEY 时把规范化域名冻结为授权边界；节点在线兑换时必须提交完全
> 一致的域名，禁止“先领码、任意服务器先到先得”。申请可选填写静态公网 IP：默认仅作
> 风险核验，来源 IP 不一致时允许激活但返回警告并留痕；只有 OEM 明确启用“严格 IP
> 绑定”时才拒绝不一致来源。来源 IP 必须由 Nexus 从可信反向代理请求读取，不能相信
> 节点自报；数据库只保存使用 ``NEXUS_SECRET_KEY`` 计算的 HMAC 和脱敏网段，不保存
> 完整公网 IP。历史 KEY 保持兼容：没有预绑定记录时首次兑换冻结实际域名，已绑定实例
> 的同域重装保持幂等。后续改域名或严格 IP 必须走平台审核，不能由客户端自行覆盖。

> **OEM 节点首次激活门禁（2026-08）**：安装阶段 Nexus 兑换因网络或反代 IP
> 校验暂时失败时，节点可继续完成基础安装但必须进入 `pending_activation` 受限态；
> 仅安装时的 bootstrap 管理员可登录激活页，注册与其他账号登录均由节点服务端拒绝。
> 激活请求由节点服务器从环境读取 OEM KEY 并提交 Nexus，浏览器绝不接触 KEY；成功状态
> 以节点持久化文件保存后才开放业务。Nexus 生产仅信任本机 Caddy 覆盖写入的
> `X-Real-IP`；Caddy 必须先按 Cloudflare 官方 CIDR 严格还原来源地址，禁止应用直接信任
> `X-Forwarded-For`。

> **Nexus OEM 节点大屏接入（2026-08）**：所有已兑换并产生实例记录的 OEM
> 节点都必须进入数据大屏实例总数，不能因为地域缺失从运营视图静默消失。首次部署
> 必须由安装人选择真实机房地域，Nexus 服务端校验受支持代码后才允许兑换；受限态
> 激活重试继续携带同一地域，禁止根据云厂商 IP 自动猜测。历史缺失节点在大屏单独
> 计入“待定位”，并由超管补录；已部署节点地域允许纠正但禁止清空。

> **OEM 网页发行版强制授权（2026-08）**：暂未提供桌面/移动 App，也不提供免费
> 网页本地部署；所有网页节点必须先注册/登录 Nexus OEM、按部署域名取得独立授权，
> 再由安装器向 Nexus 获取正式发布的不可变 Docker 摘要。授权码留空、echo 独立模式和
> 客户服务器现场构建均不得作为公开安装路径；安装阶段暂时兑换失败只能进入
> `pending_activation`，不能绕过门禁开放业务。

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

> **Nexus OEM 邮箱防刷（2026-08）**：Nexus OEM 门户使用独立的 Cloudflare
> Turnstile Managed 小组件，只保护“注册验证码、验证码登录码、密码重置码”三类邮件的
> 发送入口；普通密码登录与已经通过挑战后持有单次邮箱码的最终注册/登录/重置提交不重复
> 弹出挑战。浏览器只接收公开 site key，secret 仅从 Nexus 服务端环境变量读取；服务端
> 调用 Siteverify 后必须同时校验 ``success``、预期 hostname 与按用途隔离的 action，网络
> 异常或校验不一致时安全拒绝发信。Turnstile 是现有 IP/邮箱冷却与限频之外的附加防线，
> 不能替代业务限频；Nexus 与 OEM 节点必须使用不同的小组件和密钥，配置不完整时该附加
> 防线保持关闭且前端不得显示失效挑战。

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
> 管理员账号和可撤销短期会话，审计事件写入真实显示名；网页不得再接受长期
> 管理或恢复凭据。首个管理员引导与忘记密码恢复必须先经 Google Cloud SSH 运行
> ``python -m nexus.recovery_codes``，明文单次码仅显示在当前终端，5-60 分钟过期且消费后
> 立即作废；数据库只保存哈希。管理员账号支持创建、停用、
> 重置密码与会话整体失效；禁止停用当前账号或最后一个有效管理员。所有管理端写操作
> 还要追加一条全局操作审计，授权/KEY 等业务对象原有的细粒度时间线继续保留。
> 超管登录固定使用独立地址 ``/portal/admin/``，普通 ``/portal/`` 只显示 OEM
> 登录/注册，不提供超管切换入口。独立 URL 只负责产品入口隔离，不得被当成鉴权手段；
> 服务端仍必须逐请求校验具名管理员会话。浏览器会话必须使用
> ``HttpOnly + Secure + SameSite=Strict`` 的非持久化 Cookie，管理写操作另验
> ``X-Nexus-CSRF``；不得把管理员会话放在 local/sessionStorage。单次码验证后只换取
> 30 分钟恢复 Cookie，且不返回单次码原文。

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
7.7 **节点镜像判定与三环境流转（强制）**：每次提交前先判断改动是否进入 OEM 节点
运行包。`cosmac/`、`client/`、节点安装/更新器或节点运行配置发生变化时，按版本规则
创建严格 tag，CI 构建并登记不可变镜像，登记成功后只自动推送节点 #2；节点 #2
安装与技术验证成功后，才允许人工发布节点 #3。节点 #1 始终由负责人开发调试，
不接收 Nexus 自动任务。仅修改 `nexus/`、Nexus 门户/大屏或中央平台运维配置时，
提交并推送 `main` 后直接部署中央 Nexus，**不升节点版本、不打节点 tag、不构建镜像、
不推送任何节点**。每次交付必须分别报告 GitHub、Docker Hub、GHCR、自建镜像仓与
节点任务五项真实状态。
7.8 **桌面/手机 App 发布门禁（强制，优先于本节通用自动发布规则）**：现阶段只设计、
开发和本地验证 Electron/Capacitor 客户端。除非负责人在当前任务中明确说“开始发布/上架
桌面和手机 App”，否则不得创建或操作应用商城正式条目、生产签名、公开安装包、官网
下载入口、自动更新 feed、Nexus `client` 轨道或商店提交；不得用远程下载 Vue/JS 代码
绕过应用商店审核。现有 Web、Nexus 与 OEM 节点仍按既有发布规则执行，不因本门禁停更。
负责人启动 App 发布阶段后，必须先回到本文件补齐真实商店 ID、签名边界、下载存储、
统一版本清单、审核/灰度/回滚状态机，再进行任何外部发布操作。
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
