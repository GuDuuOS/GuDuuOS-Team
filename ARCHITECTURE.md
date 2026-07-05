# CosMac OS — 系统架构总览 (Architecture)

> 本文件是**给人读的架构地图**：讲清楚"这个系统由什么组成、数据放在哪、AI 怎么工作、
> 资源怎么分层、请求怎么流转"。
> 与 `CLAUDE.md`(项目宪法/开发规范)、`DEVLOG.md`(开发流水)、`DEPLOY.md`(部署细节·gitignored)分工不同。
> 架构一旦有大变动，先更新本文件再写代码。最后更新：2026-07-05。

---

## 1. 一句话定位

**CosMac OS = 基于 Matrix(Synapse) 的海外版 IM + 一层"主 AI 控制层"。**

在标准 IM(聊天/群组/联邦)之上，叠加一个能感知并操作 IM 全部功能的 AI 系统：主 AI 能拆任务、
建专班、调配"人 / AI 同事 / 技能 / 知识库 / 规则"，并逐步接入会员变现、工作流、个人主页等模块。

**铁律**：不改 Synapse 核心，所有业务逻辑写在独立扩展层 `cosmac/` 里，通过 Synapse 的
Module API / Application Service 协议接入。这样能一直跟上游更新、易维护。

---

## 2. 三层总体架构

```
┌─────────────────────────────────────────────────────────────┐
│  ① 客户端 (client/  ·  Vue 3 + TS)                            │
│     LiveView(驾驶舱) / AuthView(登录注册) / AdminView(后台)    │
└───────────────┬─────────────────────────────────────────────┘
                │  Matrix C-S API(聊天/房间) + cosmac 自定义 HTTP 端点
┌───────────────▼─────────────────────────────────────────────┐
│  ② Synapse 核心 (v1.141 运行 / v1.98 源码参考 · 尽量不动)      │
│     账号、房间、消息、联邦、state event —— Matrix 本职         │
└───────────────┬─────────────────────────────────────────────┘
                │  Application Service 协议(bot 作为 appservice 接入)
┌───────────────▼─────────────────────────────────────────────┐
│  ③ CosMac AI 服务 (cosmac/  ·  独立 Python 进程)              │
│     appservice bot：看到每条消息、能建群/发消息/派单           │
│     多模型抽象层 · 工具箱 · 双层作用域 · 资源分层 · 变现门控    │
│     ↕ 复用生产 PostgreSQL(单独 database) + 可选 pgvector       │
└─────────────────────────────────────────────────────────────┘
```

- **客户端不直接连 bot 做聊天**：聊天走 Matrix C-S API(Synapse)；只有 AI 配置、会员、
  知识库、任务看板等"cosmac 自有能力"走 bot 的自定义 HTTP 端点(`/cosmac/*`)。
- **bot 是 appservice**：Synapse 把每条事件推给 bot，bot 是主 AI 的"眼睛和手"。

---

## 3. 目录结构

```
synapse/          上游 Synapse 仓库(只读参考，改动需登记 CLAUDE.md §8)
cosmac/           CosMac 全部后端代码(独立 Python 包)
  __main__.py       进程入口(python -m cosmac)
  config.py         配置(env 读取，COSMAC_* 前缀，兼容旧 GUDUU_*)
  bots/
    appservice_bot.py   ★核心：事件处理 + 全部 /cosmac/* HTTP 端点 + 资源分层
    matrix_client.py    对 Synapse 的 HTTP 封装(建房/发消息/state/邀请…)
  ai/
    base.py           LLMProvider 抽象接口(complete / complete_with_tools)
    claude.py / openai_compat.py / ark.py / echo.py   各模型后端
    agent.py          legacy 工具循环引擎(同步)
    engine.py         Claude Agent SDK 引擎(可插拔，env 开关，默认关)
    tools.py          ★工具箱：建群/邀人/发消息/派单/组班/工作流/知识检索…
    presets.py        预置 AI Agent(文案/策划/编辑/分析/客服/翻译/调研/社媒)
    preset_skills.py  预置技能库(9 个方法论，绑给预置 Agent)
    embeddings.py     向量嵌入(知识库 RAG)
    websearch.py      联网搜索工具
  db/
    engine.py         SQLAlchemy 引擎(同步；create_all 自动建表)
    models.py         全部 ORM 表(见 §5)
    kb.py / kb_cmd.py           知识库入库/检索/切块
    task_repo.py / person_repo.py / order_repo.py / quota_repo.py …
    user_template_repo.py       用户→入驻模板映射(资源权限用)
  members.py        会员等级 + 功能门控(GatingStore / MembersStore)
  quotas.py         用量配额引擎
  registration.py   邮箱验证码注册 / 登录收口 / 找回 / 异地二次验证 / Turnstile
  wf.py             工作流连接器引擎(对接 n8n/Dify/Coze/ComfyUI)
  trading/          模块4 交易(套餐/订单/可插拔支付 Provider)
  skills_text.py    技能→system 提示渲染(6000 字预算)
  tests/            全部单测(trial/unittest，~390 个)

client/           Vue 3 + TS 客户端
  src/views/        LiveView(根组件·驾驶舱) / AuthView / AdminView
  src/matrix/client.ts   ★所有对 Synapse + /cosmac/* 的前端调用
  src/components/    board/channel/chat/layout/membership/onboarding/doc …
  src/composables/   useKnowledge / useMyPeople / useOnboarding / useToast …
  dist/             构建产物(gitignore；提交用 git add -f)
```

---

## 4. AI 引擎架构

### 4.1 多模型可插拔

所有大模型调用走 `cosmac/ai/base.py` 的统一接口 `LLMProvider`，**不把任何厂商 SDK 散落到业务里**。
后端通过 env 切换：

| Provider | env | 说明 |
|---|---|---|
| `echo` | (默认) | 占位，无 key 时自动降级，bot 照常能跑 |
| `claude` | `ANTHROPIC_API_KEY` | Claude(默认 opus) |
| `openai` | `OPENAI_API_KEY` | GPT |
| `deepseek`/`ark` | `ARK_API_KEY` | DeepSeek(走火山方舟，OpenAI 兼容) |

**线上生产当前用 DeepSeek**。人设/模型/工具开关可在后台热下发(见 §6 控制室)。

### 4.2 两套执行引擎(可切换)

- **legacy 引擎**(`ai/agent.py`)：自写的工具循环，同步、直连 HTTP，快。默认。
- **Claude Agent SDK 引擎**(`ai/engine.py`)：Claude Code 同款 harness(成熟工具循环/重试/上下文管理)，
  经 DeepSeek 的 Anthropic 兼容端点驱动。env 开关 `COSMAC_AGENT_ENGINE=claude_sdk`，默认关；
  失败自动回退 legacy + 控制室告警。要 Python 3.10+ 和 Claude Code CLI。

两套引擎共用同一个 `Toolbox`——**门控/配额/越权检查/防呆全复用**，引擎只是换"大脑的操作系统"。

### 4.3 过程可见(Claude Code 式交互)

主 AI 执行工具时，发一条状态消息并**原地编辑更新**(m.replace)，让用户看到"正在调取名册 / 正在建频道…"，
而非死等。见 `_ProgressReporter`。

---

## 5. 数据存储分层(铁律：Synapse 已存的绝不重存)

| 数据 | 存哪 | 说明 |
|---|---|---|
| 聊天记录/消息/已读位/账号/房间 | 🚫 Synapse 的 PG | Matrix 本职，前端走 sync 拿，不在 cosmac 重存 |
| **全局 AI 配置**(人设/模型/工具开关) | Matrix state event | 控制室 `cosmac.ai.config`，后台写、bot 读、热生效 |
| **全局技能/Agent 定义** | Matrix state event | 控制室 `cosmac.skills` / `cosmac.agents`(浏览器够不到 DB，故走 state) |
| **人员能力名册/规则/门控/会员/配额/套餐** | Matrix state event | 控制室 `cosmac.people`/`.rules`/`.gating`/`.members`/`.quotas`/`.plans` |
| **入驻模板/工作流连接器/社媒数据源** | Matrix state event | 控制室 `cosmac.onboarding_templates`/`.workflows`/`cosmac.social_sources` |
| **频道级配置**(人设/绑定技能·Agent/RULE/知识库) | Matrix state event | 每频道 `cosmac.channel_config`(见 §7) |
| **每账号轻量配置** | Matrix account data | 如首次引导标记 `cosmac.onboarding` |
| **知识库**(文档分块 + 向量) | ✅ cosmac DB + pgvector | state event 存不下也搜不了——上 DB 的最硬理由 |
| **任务/订单/工作流运行/记忆摘要/审计/图文页** | ✅ cosmac DB | 关系型/派生数据 |
| **用户→入驻模板映射**(资源权限) | ✅ cosmac DB `cosmac_user_template` | |
| **邮箱↔账号映射**(一邮一号) | ✅ cosmac DB `cosmac_registered_email` | |

**cosmac DB 表**(SQLAlchemy 同步；create_all 自动建表)：
`cosmac_skill / cosmac_agent / cosmac_kb_doc / cosmac_kb_chunk / cosmac_workflow_run /
cosmac_seen_txn / cosmac_order / cosmac_task / cosmac_conversation_memory / cosmac_person /
cosmac_project_archive / cosmac_usage / cosmac_registered_email / cosmac_auth_event /
cosmac_doc_page / cosmac_user_profile / cosmac_user_template`。

- **本地开发**：`COSMAC_DATABASE_URL` 缺省回退 SQLite(`run/cosmac.db`)，零基建。
- **生产**：指向 Synapse 那台 PostgreSQL 的独立 database；知识库向量检索需 pgvector。

> **"控制室"**是一个特殊 Matrix 房间(alias `#cosmac-ctrl`)，充当**平台的配置数据库**——
> 因为浏览器(管理后台)只能走 Matrix、够不到 DB，所以平台级配置都写成它的 state event。
> 它从频道列表里隐藏，管理员成员集与"服务器管理员"联动(见 §9)。

---

## 6. 双层作用域(核心概念)

同一个主 AI，按对话场景分成两种身份，用 `ctx.is_dm` 区分：

| 身份 | 场景 | 作用域 | 数据可达范围 |
|---|---|---|---|
| **全局助理** | 右侧"私人会话"面板 | 跨频道统筹 | 以**发起人本人的成员身份**为界，可跨房间调资料/派单 |
| **频道分身** | 在某频道里 @AI | **锁死本频道** | 只读本频道记忆/知识/成员；工具层拒绝碰别的房间 |

两种模式**智能水平相同**(同一引擎、都能拆任务建专班)，区别只是"能拿到的原料"不同。
判定优先级：`cosmac.ai_session` 标记 > 房间人数兜底。实名频道即使 2 人也按群聊(只 @ 才回)。

---

## 7. 资源分层体系(平台 / 个人 / 频道)

五类可调配资源，都分三层，组班时从"库"里调取、**绑定进频道**：

| 资源 | 平台级 | 个人级 | 频道级 |
|---|---|---|---|
| **技能 Skill** | 控制室 `cosmac.skills` + 代码预置(`preset_skills.py`) | cosmac DB(个人命令建) | 绑进频道 `channel_config.skill_slugs` |
| **AI Agent** | 控制室 `cosmac.agents` + 代码预置(`presets.py`) | — | 绑进频道 lead/worker |
| **知识库** | 平台共享库(SCOPE_GLOBAL) + 图文教程 | 个人库(SCOPE_USER) | 频道库(SCOPE_ROOM) + 组班绑定来源 |
| **RULE** | 控制室 `cosmac.rules`(平台硬约束) | 用户偏好画像(user_profile) | 频道 `channel_config.taskRule`(专班宪法) |
| **人(协作人)** | 控制室 `cosmac.people` | cosmac DB `cosmac_person` | invite 进频道 |

### 7.1 技能的"生效方式"(inject)

全局技能是**每轮对话都注入 system**(总预算 6000 字)，塞太多会撑爆。故技能有 `inject` 字段：
- `global`(默认)：每轮全局注入——只适合极少数超通用技能；
- `agent`：只在绑定的 AI 同事被 @/指派时激活——方法论类技能都走这个，平时零占用。

预置技能全部 `inject=agent`、绑给对应预置 Agent；后台"技能库"页可见(顶部预置区只读、可"覆盖为自定义")。

### 7.2 资源可用范围(access·账号级权限)

每个全局技能/Agent 带 `access` 字段，bot **服务端强制**：
- `''`=所有人；`paid`/`creator`=会员等级及以上；`admin`=仅平台管理员；
- `tpl:模板key`=仅选了这些入驻模板注册的用户(映射存 `cosmac_user_template`)。

强制点：对话注入(`_skill_addendum`) + 能力名册(`list_capabilities`)按**发起人**过滤；
**群绑定的不过滤**(管理员显式配置=授权)。平台管理员永远可用。

### 7.3 知识库"调进频道"(三种来源)

组班时 `assemble_team(knowledge=[...])` 把知识库来源写进 `channel_config.kbScopes`，
频道全体成员/AI 对话时都检索这些来源：
- `owner` → 发起人个人库对全班开放；
- 某频道名 → 把那个"资料库频道"的知识挂给专班；
- `platform` → 平台共享知识库(管理员后台"平台知识库"页维护)。

---

## 8. 组班编排流程(模块 3.5)

主 AI 把一个目标变成"一支能干活的专班"，链路：

```
用户在右侧主AI下达目标
  → list_capabilities  读"能力名册"：有哪些人/AI同事/技能/知识库可调
  → assemble_team      一键建专班：
       · 建频道 + 邀请匹配到的真人(members)
       · 绑 lead Agent(作频道主AI人设) + worker Agents(@名路由)
       · 装 Skill(skill_slugs) + 知识库(kbScopes)
       · 写 RULE(taskRule，缺省自动生成基础版) —— 频道的"任务宪法"
       · 派子任务(create_tasks，executor_kind=human/agent/workflow)
  → 缺口提醒：库里没有的技能/Agent 会提示"还缺什么"
  → 频道里：多 AI 同事按 @名 路由回话，各带自己人设/技能/模型，都受 taskRule 约束
  → 任务看板：每个成员只看"派给自己"的任务(可见性服务端强制)
```

**任务 RULE(taskRule)** 是频道主 AI 的最高约束(优先级：平台规则 > 任务RULE > 人设 > 用户偏好)。

> 已知的编排哲学差异：现状是 `assemble_team` **一次性**完成建频道+RULE+派单；
> 负责人设想的"频道分身接任务后**自主**设计录入 RULE 再拆解"两段式尚未实现(记为待议)。

---

## 9. 变现与权限体系

```
账号权限两条正交线：
  · 服务器管理员(Synapse admin 标志)  ←→  控制室成员(power≥50)  [双向联动]
  · 会员等级(免费 < 付费 < 创作者)     ←  cosmac.members(管理员/支付授予)

三道服务端强制的闸(客户端只配置、bot 才是防线)：
  ① 功能门控 gating   能力→最低会员等级(ai_chat/knowledge/create_room/workflow_run…)
  ② 用量配额 quota    每计量项 已用/上限(ai_msg_daily/kb_docs/teams…)，按 tier
  ③ 资源可用范围 access  技能/Agent 按 等级/模板/管理员 过滤

平台管理员永远不受会员门控。工具层经 Toolbox.gate_check/quota_check 同样受控(防自然语言绕过命令)。
```

**模块4 交易**(`cosmac/trading/`)：套餐(控制室 `cosmac.plans`) + 订单(DB) + 可插拔支付 Provider。
当前仅 mock(manual) 通道能跑通业务链；真实支付(Stripe/PayPal/USDT/支付宝/微信)未端到端接通。

---

## 10. 认证与安全(auth)

- **登录收口**：登录走 bot `/cosmac/login/account`(不再前端直连 Synapse)，好插风控。
- **一邮一号**：注册先占位邮箱、再建号；`set_email` 拒改绑；找回只重置绑定账号。
- **邮箱验证码注册**：bot 发码/验码/共享密钥建号(Lark SMTP)；Synapse 开放注册已关。
- **防刷**：Turnstile 人机验证(env 可插拔) + 同邮箱冷却/限量 + 单 IP 限频 + 验码爆破锁。
- **异地二次验证**(阶段2，env 开关)：新地点登录密码对了也要邮箱码(step-up)。
- **审计**：`cosmac_auth_event` 记录登录/发码等事件。
- 分阶段路线：阶段0 收口(已) → 1 密码强度+Turnstile(已) → 2 异地检测(已) → 3 短信防多号(未)。

---

## 11. 前端架构(client/)

- **根组件是 `LiveView.vue`**(不是 App.vue，也基本不走 `<router-view>`)：`main.ts` 直接挂它。
  导航靠 LiveView 内的**集中式 URL 双向同步**(`computePath` 状态→地址 / `applyFromRoute` 地址→状态)，
  不是常规 router-view。独立 `AuthView`(登录) 走真路由。
- **接路由的视图**：数据看板 `/s/:space/board`、任务看板 `…/tasks`、频道 `…/c/:roomId`、
  后台 `/admin`、个人主页 `/me`。临时态(菜单/弹窗/侧栏)不接路由。用 **hash history**。
- **所有后端调用集中在 `src/matrix/client.ts`**：Matrix C-S API + 全部 `/cosmac/*` 端点。
- **UI 调试铁律**：布局 bug 用浏览器实测量 DOM 定位，不对截图猜(见 memory `ui-debug-use-browser`)。

---

## 12. 部署架构(细节见 gitignored 的 DEPLOY.md)

```
浏览器 ──https──▶ 宝塔 nginx(接管 80/443) ──▶ /var/www/cosmac-app (前端静态)
                                          └──▶ Synapse (127.0.0.1:8008)
                                          └──▶ cosmac bot (appservice, systemd: guduu-bot)
Synapse ⇄ PostgreSQL(含 cosmac 独立 db)
```

- **前端部署**：`cd client && npm run build` → `git add -f client/dist` → push →
  服务器 `git pull` + `cp dist/* /var/www/cosmac-app/`(宝塔 nginx 实时读盘，无需 reload)。
- **后端部署**：改了 `cosmac/` → 服务器 `git pull` + `systemctl restart guduu-bot`。
- 密钥只进服务器 env / systemd，绝不进代码或 git。

---

## 13. 模块路线图状态

| # | 模块 | 状态 |
|---|---|---|
| 1 | 主 AI 控制层(bot/多模型/工具/热配置) | ✅ 完成 |
| 2 | 群级 记忆/知识库/Rule/Skill | ✅ 完成 |
| 3 | Bot/插件/工作流(对接外部平台，不自建引擎) | ✅ 完成(单实例够用即止) |
| 3.5 | AI 任务编排(能力名册/组班/派单/资源分层) | ✅ 完成(两段式 RULE 待议) |
| 4 | 交易(会员订阅) | 🟡 地基+mock；真实支付未通 |
| 5 | 个人主页 | ⬜ 未开工 |
| R | 品牌化 Matrix/Synapse → CosMac(呈现层) | ⬜ 持续横切 |

**增强项(按需再补)**：pgvector 上量、长期记忆摘要、引擎冷启动提速、切/混用 Claude 大脑、
群级模型联动、入驻模板 P3、社媒数据源 P2-P4、全局助理跨频道知识库聚合、两段式组班 RULE、公告定向广播。

---

## 14. 关键设计约束速查(改代码前对照)

1. **不改 Synapse 核心**——优先 Module/Appservice，真要改先问负责人 + 登记 CLAUDE.md §8。
2. **Synapse 已存的不重存**——数据分层见 §5。
3. **浏览器够不到 DB**——平台配置走控制室 state event。
4. **全局技能每轮全注入**——受 6000 字预算约束，方法论走 `inject=agent`。
5. **权限服务端强制**——门控/配额/access/任务可见性都在 bot，客户端只配置。
6. **协议层一字不改**——`/_matrix`、`m.*` 事件、联邦格式(品牌化只碰呈现层)。
7. **密钥只进 env**——不进代码/git。
8. **全程中文沟通 + 详细中文注释**(CLAUDE.md §5/§6)。
