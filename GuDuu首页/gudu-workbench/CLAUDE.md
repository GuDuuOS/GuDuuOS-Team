# CLAUDE.md — GuDuu 工作台 × Mattermost 集成项目

> **给 Claude Code 的项目说明书。每次进入本项目，请先完整读这份文件，再读 `ROADMAP.md` 与 `docs/00-architecture.md`，最后看「当前阶段」指向的任务文档。**

---

## 1. 项目一句话

把现有的 GuDuu 工作台（Vue 3 DEMO · 行业通用版，以「示例企业」为演示数据）逐步改造成一个可商用的「行业 AI 工作台」产品，底层使用 Mattermost 作为 IM 与平台底座。

详细可行性分析见仓库外的 `GuDuu工作台×Mattermost-改造可行性评估.docx`（已经存在），结论：**不走「完全替换 Mattermost 前端」的 A 路线，走「Mattermost 后端 + 业务画布插件化」的 B+C 混合路线**。

## 2. 三阶段路线图（必读）

| 阶段 | 周期 | 目标 | 主路线 | 任务文档 |
|------|------|------|--------|----------|
| **阶段一 · POC** | 0-4 周 | Vue 工作台直接挂 Mattermost API 跑通端到端 Demo | C 路线 | `docs/phase-1-poc.md` ← **当前阶段** |
| **阶段二 · 产品化** | 5-16 周 | 业务画布以 Webapp Plugin 落地到 Mattermost React Webapp | B 路线 | `docs/phase-2-plugin.md` |
| **阶段三 · 壁垒** | 17-48 周 | 部门 AI 治理 Server Plugin + 行业插件集市 | B 深化 | `docs/phase-3-moat.md` |

**当前阶段：阶段一 · POC**。Claude Code 工作时优先从 `docs/phase-1-poc.md` 里依序拣 `status: pending` 的任务执行。

## 3. 当前仓库 = Vue DEMO 现状

- 技术栈：Vue 3 + `<script setup>` + TypeScript + Vite 6 + vue-router 4（hash 模式）+ Chart.js 4
- 现状：纯 mock 数据驱动，无后端调用，无 WebSocket
- 入口：`src/main.ts` → `src/App.vue` → `src/router/`
- 关键目录：
  - `src/views/`         — 频道视图（Dashboard / Safety / Energy / Office / Ops / Todo / DuuChat）
  - `src/components/`    — channel / canvas / layout / common
  - `src/composables/`   — Vue 组合式逻辑（useChannelAdmin、useAiAgent、useCli 等）
  - `src/data/`          — 全部为 mock 数据（channels.ts / messages/ / kpi.ts / charts.ts ...）
  - `src/types/`         — TypeScript 类型（重点：`message.ts` 定义 RichCard / DocPreview / ChartCard 协议）

## 4. 阶段一的核心改造目标

把 `src/data/` 下的 mock 数据，替换为来自 Mattermost 的实时数据；把 `Composer.vue` 的"发送"按钮，从写本地数组改成调 `POST /api/v4/posts`；把"用户在线/未读/新消息"接入 Mattermost WebSocket。

**重要约定**：阶段一**不**改造 Mattermost 自身、**不**写 Mattermost Server/Webapp Plugin、**不**修改 Mattermost 源码。我们只在 Vue 工作台这一侧做适配。Mattermost 通过 Docker Compose 跑在本地，作为外部 API 服务。

## 5. 技术约定（Claude Code 写代码时严格遵守）

### 5.1 文件组织
- Mattermost 适配层新建在 `src/mattermost/`，目录结构：
  ```
  src/mattermost/
  ├── client.ts          # 单例 MM Client（基于官方 @mattermost/client）
  ├── auth.ts            # 登录 / Token 管理 / 自动续期
  ├── ws.ts              # WebSocket 长连接与事件分发
  ├── adapters/          # 把 MM 数据结构转换为 src/types 内的 GuDuu 类型
  │   ├── channel.ts
  │   ├── message.ts
  │   └── user.ts
  ├── api/               # 业务封装（薄）
  │   ├── channels.ts
  │   ├── posts.ts
  │   └── teams.ts
  └── custom-post-types.ts  # GuDuu 自定义富卡 type 注册表（cctv / doc / chart / rich）
  ```
- 现有 `src/data/*.ts` 的 mock 数据**保留**作为「降级数据 / 演示数据」，新增 `src/stores/` 用 Pinia（或简单的 reactive 单例）作为运行时数据源。
- 现有 Vue 组件**尽量不改**，把"数据源切换"放在 composables 里完成（如 `useChannelList()` 内部判断是接 MM 还是接 mock）。

### 5.2 配置
- `.env.local`（不入库）放：
  ```
  VITE_MM_URL=http://localhost:8065
  VITE_MM_TEAM=guduu
  VITE_MM_TOKEN=...     # Personal Access Token，仅开发用
  VITE_DATA_SOURCE=mattermost   # 或 mock
  ```
- 切换 `VITE_DATA_SOURCE=mock` 时，整个 App 退回到当前 DEMO 行为，保证演示永远不挂。

### 5.3 自定义富卡协议（关键）
Mattermost 的 Message Attachments 不够富，CCTV/Doc/Chart 这种走「自定义 post type」约定：发消息时 `post.type = "custom_gd_<kind>"`，业务数据放在 `post.props.gd` 里。客户端 `src/mattermost/custom-post-types.ts` 注册解析器，把 `post` 转换为现有 `MessageData`（见 `src/types/message.ts`）。

约定的 type 列表：
- `custom_gd_rich`   → RichCardData
- `custom_gd_cctv`   → RichCardData（含 cctv 字段）
- `custom_gd_doc`    → DocPreviewData
- `custom_gd_chart`  → ChartCardData

> 这是 Slack/Mattermost 主流"非破坏性扩展"做法，不需要改 Mattermost 服务端。

### 5.4 代码风格
- TypeScript strict，禁止 any（除 Mattermost SDK 自身返回的临时类型外）。
- 组件用 `<script setup lang="ts">`，组合式逻辑放 `src/composables/use*.ts`。
- 异步逻辑统一用 `async/await`，错误用 `Result<T, Error>` 风格的 `{ ok, data, error }` 返回，UI 层只读 `error.message`。
- 不引入 axios / superagent，全部用 Mattermost 官方 client 或 `fetch`。
- 不引入新的 UI 框架（不要 Element/Antd/Naive），保持现有的"原生 CSS 变量 + 模块化样式"风格。
- 日志：开发期用 `console.debug('[mm]', ...)`，生产构建 Vite 会 tree-shake 掉（在 vite.config 配置 `define: { 'console.debug': 'undefined' }`）。

### 5.5 测试
- 阶段一不要求单测覆盖率，但每个 `src/mattermost/api/*.ts` 至少有一个 happy-path 的 vitest 集成测试（跑在 mock fetch 之上）。
- 必须保留 `npm run type-check` 通过，作为每次提交前置条件。

### 5.6 提交习惯
- 一个任务 = 一个分支 = 一份 PR。
- 分支命名：`phase-1/task-NN-短描述`（如 `phase-1/task-03-channels-real`）。
- Commit message 用 conventional commits：`feat(mm): add channel list adapter`、`fix(ws): reconnect with backoff`。
- 每完成一个任务，在 `docs/phase-1-poc.md` 把该任务的 `status: pending` 改为 `status: done`，并记录 PR 号或 commit hash。

## 6. 如何启动开发

```bash
# 1. 起 Mattermost（首次）
cd docs/env && docker compose up -d
# 等 30 秒，访问 http://localhost:8065 完成初始化（详见 docs/env-setup.md）

# 2. 跑 Vue 工作台
cd ../.. && cp .env.example .env.local   # 填上 Token
npm install
npm run dev    # http://localhost:5173

# 3. 类型检查与构建
npm run type-check
npm run build
```

## 7. Claude Code 怎么使用本仓库

进入项目后建议的第一句话：

```
请读 CLAUDE.md、ROADMAP.md、docs/00-architecture.md，
然后打开 docs/phase-1-poc.md，找到第一个 status: pending 的任务执行。
执行前先简述你的方案，得到我确认后再开干。
```

每个任务完成的标志（见任务卡的「验收」段）：
1. 代码改动落到对应文件，类型检查通过。
2. 如果任务涉及运行行为，提供一段 README 风格的"如何手动验证"步骤。
3. 更新 `docs/phase-1-poc.md` 里该任务的状态。

## 8. 不要做的事

- ❌ 不要 fork Mattermost 源码（阶段一不涉及）。
- ❌ 不要把现有 Vue 组件大改造，组件保持稳定；改造发生在 composables 与 src/mattermost/ 适配层。
- ❌ 不要引入新的 UI 库或 CSS 框架。
- ❌ 不要把 `.env.local` / Token 提交进 git。
- ❌ 不要为了"漂亮"重排现有目录结构。

## 9. 词汇表

- **MM**：Mattermost 缩写
- **PAT**：Personal Access Token（Mattermost 管理后台可生成）
- **Post**：Mattermost 里的消息单元（≈ GuDuu 的 MessageData）
- **Channel**：MM 频道（≈ GuDuu 的 ChannelItem）
- **Team**：MM 团队（≈ GuDuu 的"工作区/部门"，但弱于 GuDuu 的 DeptLimits）
- **Custom Post Type**：MM 允许 `post.type` 自定义命名空间（`custom_*`），客户端可注册渲染器
- **Webapp Plugin**：MM React Webapp 的注入式插件（阶段二才用到）
- **Server Plugin**：MM Go 服务端插件（阶段三才用到）
