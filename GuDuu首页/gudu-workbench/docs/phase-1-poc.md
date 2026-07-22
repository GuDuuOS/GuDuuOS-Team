# 阶段一 · POC 任务卡（4 周）

> 这是 Claude Code 直接按顺序执行的任务清单。每张任务卡都自包含：**目标 / 输入 / 产出 / 验收 / 依赖**。
>
> **执行规则**：
> 1. 从上往下找到第一个 `status: pending` 的任务。
> 2. 先在对话里复述"我要做什么、产出哪些文件、如何验证"，等用户确认。
> 3. 执行完成后把该任务的 `status` 改为 `done`，记录 commit hash 或 PR 号。
> 4. 不要跳过任务（每张任务的依赖都已显式标出）。

## 任务列表速览

| ID | 任务 | 预估 | 状态 |
|----|------|------|------|
| T0 | 起 Mattermost 本地实例（Docker Compose） | 0.5d | pending |
| T1 | 引入 @mattermost/client，搭 src/mattermost/ 骨架 | 0.5d | pending |
| T2 | 实现 auth 与配置加载（.env.local 读 Token） | 0.5d | pending |
| T3 | adapters：MM Channel/User/Post → GuDuu 类型 | 1d | pending |
| T4 | API 层：channels / posts / teams 三个核心封装 | 1d | pending |
| T5 | Pinia / reactive store：channels / messages / users | 1d | pending |
| T6 | useChannels / useMessages 切换到真实数据源 | 1d | pending |
| T7 | WebSocket 接入：posted / typing / status_change | 1.5d | pending |
| T8 | Composer 发消息打通（含降级到 mock 模式） | 1d | pending |
| T9 | 自定义富卡协议：RichCard / Doc / Chart / CCTV | 2d | pending |
| T10 | Seed 脚本：把 mock messages 灌进 MM | 0.5d | pending |
| T11 | 验收 Demo：端到端跑通"发→收→渲染"四类富卡 | 1d | pending |

**合计**：约 12 人天 + 缓冲 → 4 周可控。

---

## T0 · 起 Mattermost 本地实例 {#t0}

- **status**: pending
- **owner**: claude-code
- **依赖**: 无
- **预估**: 0.5d

### 目标
让本地能跑起一个 Mattermost 实例，作为 Vue 工作台联调对象。

### 产出文件
- `docs/env/docker-compose.yml` — Mattermost + PostgreSQL 双服务
- `docs/env/.env.example` — Compose 自身的环境变量样例（DB 密码等）
- `docs/env/README.md` — 简单的"如何起 / 如何停"

### 实现要点
- 使用 `mattermost/mattermost-team-edition:latest`（Team Edition 即开源 AGPL 版，免费、足够 POC）
- PostgreSQL 用 `postgres:14-alpine`
- Mattermost 端口 8065 暴露到宿主机
- 卷持久化：`./volumes/mattermost-data`、`./volumes/mattermost-logs`、`./volumes/postgres-data`（加入 `.gitignore`）
- 关键 env 设置：
  - `MM_SQLSETTINGS_DATASOURCE` 指向 postgres
  - `MM_SERVICESETTINGS_SITEURL=http://localhost:8065`
  - `MM_SERVICESETTINGS_ALLOWCORSFROM=*`（开发用）
  - `MM_SERVICESETTINGS_ENABLEUSERACCESSTOKENS=true`

### 验收
1. `cd docs/env && docker compose up -d` 后，30 秒内日志出现 `Server is listening on :8065`
2. 浏览器访问 `http://localhost:8065` 看到 Mattermost 安装向导
3. `docs/env-setup.md` 中"4. 生成 PAT"的步骤可走通
4. `volumes/` 在 `gudu-workbench/.gitignore` 内

---

## T1 · 搭 src/mattermost/ 骨架 {#t1}

- **status**: pending
- **依赖**: T0
- **预估**: 0.5d

### 目标
引入官方 SDK 与目录骨架，但**不写业务逻辑**，只做"导入即可编译通过"。

### 产出文件
- `package.json` — 新增依赖 `@mattermost/client`、`@mattermost/types`
- `src/mattermost/index.ts` — 桶文件，对外暴露 `mmClient`、`connectWs` 等
- `src/mattermost/client.ts` — 单例 `Client4` 实例
- `src/mattermost/ws.ts` — 占位（导出空函数 `connectWs / disconnectWs`）
- `src/mattermost/auth.ts` — 占位
- `src/mattermost/adapters/{channel,message,user,team}.ts` — 四个空文件，导出占位类型转换函数
- `src/mattermost/api/{channels,posts,teams}.ts` — 三个空文件，导出空 async 函数
- `src/mattermost/custom-post-types.ts` — 类型常量定义：`GD_POST_TYPE = { RICH: 'custom_gd_rich', ... }`

### 验收
1. `npm install` 后无报错
2. `npm run type-check` 通过
3. `npm run build` 通过
4. App 实际运行行为与之前完全一致（因为新代码未被任何组件引用）

---

## T2 · auth 与配置 {#t2}

- **status**: pending
- **依赖**: T1
- **预估**: 0.5d

### 目标
让 Vue 工作台启动时根据 `.env.local` 决定走 `mattermost` 还是 `mock` 数据源；走 mattermost 模式时初始化 Client4 + Token。

### 产出文件
- `.env.example`（仓库根） — 含 `VITE_MM_URL` / `VITE_MM_TEAM` / `VITE_MM_TOKEN` / `VITE_DATA_SOURCE`
- `src/env.d.ts` — 增补 ImportMetaEnv 类型
- `src/mattermost/auth.ts` —
  - `initAuth(): Promise<{ user, team } | null>`：根据 env 配置初始化 Client4、设置 token、`getMe()` 验证 + `getTeamByName()`
  - `getDataSource(): 'mattermost' | 'mock'`
- `src/mattermost/client.ts` — 真实实现 `mmClient: Client4`，由 `initAuth` 内部调用 `setUrl / setToken`
- `src/main.ts` — 在 `createApp(App).mount(...)` 前 `await initAuth()`，失败时全局 fallback 到 mock

### 验收
1. `.env.local` 配置正确时，启动 Vue 工作台后浏览器控制台打印 `[mm] auth ok, user=admin, team=guduu`
2. `.env.local` 配置错误（或缺失 Token）时，控制台打印 `[mm] auth failed, fallback to mock`，App 仍能正常展示 mock 数据
3. `npm run type-check` 通过

---

## T3 · Adapters {#t3}

- **status**: pending
- **依赖**: T1
- **预估**: 1d

### 目标
把 Mattermost 的数据结构无损转换为 GuDuu `src/types/` 里定义的类型。这是整个适配层的核心。

### 产出文件
- `src/mattermost/adapters/channel.ts`:
  ```ts
  export function toChannelItem(mmCh: Channel): ChannelItem
  export function toDmItem(mmCh: Channel, otherUser: UserProfile): DmItem
  ```
- `src/mattermost/adapters/message.ts`:
  ```ts
  export function toMessageData(post: Post, author: UserProfile): MessageData
  ```
  - 关键：根据 `post.type` 分流（普通文本走 `html`、`custom_gd_rich` 走 `rich`、`custom_gd_doc` 走 `doc`、`custom_gd_chart` 走 `chartCard`）
- `src/mattermost/adapters/user.ts`:
  ```ts
  export function toSender(user: UserProfile): Sender
  ```
  - 头像：用 `getProfilePictureUrl(user.id, user.last_picture_update)` 或回退到首字母
  - 颜色：根据 user.id 哈希到 GuDuu 调色板（沿用现 mock 的颜色规律）
- `src/mattermost/adapters/team.ts`:
  ```ts
  export function toWorkspaceMeta(team: Team): WorkspaceMeta
  ```

### 验收
1. 每个 adapter 至少一个 vitest 测试，覆盖 happy path
2. 对于未知 `post.type`，`toMessageData` 必须降级为纯文本（`html` 字段填 message），不抛错
3. `npm run type-check` 通过

---

## T4 · API 封装 {#t4}

- **status**: pending
- **依赖**: T2, T3
- **预估**: 1d

### 目标
基于 `mmClient` 暴露符合 GuDuu 语义的 API，调用方完全不感知 Mattermost。

### 产出文件
- `src/mattermost/api/channels.ts`:
  ```ts
  export async function listChannels(teamId: string): Promise<ChannelItem[]>
  export async function listDms(teamId: string): Promise<DmItem[]>
  export async function getChannelMembers(channelId: string): Promise<Member[]>
  export async function getUnreadCount(channelId: string): Promise<number>
  ```
- `src/mattermost/api/posts.ts`:
  ```ts
  export async function listPosts(channelId: string, opts?: { before?: string; perPage?: number }): Promise<MessageData[]>
  export async function createPost(input: CreatePostInput): Promise<MessageData>
  // CreatePostInput 支持四种富卡 type
  ```
- `src/mattermost/api/teams.ts`:
  ```ts
  export async function listMyTeams(): Promise<WorkspaceMeta[]>
  ```

### 实现要点
- 内部一律 try/catch，错误统一 `console.warn('[mm/api]', ...)` 后抛出
- `listPosts` 调 `mmClient.getPosts(channelId, page, perPage)`，按 `order` 数组顺序映射

### 验收
1. 单元测试用 vitest + msw（mock fetch），覆盖四个核心方法的 happy path
2. `npm run type-check` 通过

---

## T5 · 运行时 Store {#t5}

- **status**: pending
- **依赖**: T4
- **预估**: 1d

### 目标
建立 Pinia store（或同等的 reactive 单例）作为 Vue 组件读数据的唯一来源；mattermost 与 mock 两种模式都写入同一个 store。

### 产出文件
- `package.json` 新增依赖 `pinia`
- `src/main.ts` 注册 Pinia
- `src/stores/channels.ts` — `useChannelsStore()`，存当前 team 的 channels / dms，提供 `loadFromMM()` / `loadFromMock()`
- `src/stores/messages.ts` — 按 channelId 分桶存 MessageData[]，提供 `appendPost / replacePost / removePost`
- `src/stores/users.ts` — 用户在线状态缓存
- `src/stores/workspace.ts` — 当前选中的 team / channel

### 验收
1. `.env.local` 切到 `mock` 时，App 行为完全等同改造前
2. 切到 `mattermost` 时，刷新页面后频道侧栏来自 MM 实时数据
3. `npm run type-check` 通过

---

## T6 · Composables 切换数据源 {#t6}

- **status**: pending
- **依赖**: T5
- **预估**: 1d

### 目标
把现有 `src/composables/*` 中读 mock 数据的部分改为读 store；组件层完全无感知。

### 改动文件（增量编辑，不重写）
- `src/composables/useActiveWorkspace.ts` → 改读 `useWorkspaceStore()`
- `src/composables/useChannelAdmin.ts` → 频道列表读 `useChannelsStore()`
- 新增 `src/composables/useChannelMessages.ts` → 输入 channelId，返回响应式 messages（来自 `useMessagesStore()`）
- `src/views/OpsChannelView.vue`、`DashboardView.vue` 等可能需要从直接 import mock data 改为调 composable（**最小化修改**，能不动就不动）

### 验收
1. 启动 `VITE_DATA_SOURCE=mattermost` 模式，DCS-内外操协同 channel 显示真实消息列表
2. 启动 `VITE_DATA_SOURCE=mock` 模式，与 T5 完成时表现一致
3. `npm run type-check` 通过

---

## T7 · WebSocket {#t7}

- **status**: pending
- **依赖**: T5
- **预估**: 1.5d

### 目标
实时事件流入 store —— 新消息、删除、编辑、typing、状态。

### 产出文件
- `src/mattermost/ws.ts`:
  ```ts
  export function connectWs(): void   // 建立连接，注册到 Client4 的 WebSocketClient
  export function disconnectWs(): void
  export const wsBus: EventTarget     // 内部事件总线，便于调试
  ```
- 在 `src/main.ts` 的 `initAuth()` 成功后调 `connectWs()`
- ws.ts 内部根据事件名分发到对应 store action：
  | event | action |
  |---|---|
  | `posted` | `messagesStore.appendPost(adapted)` |
  | `post_edited` | `messagesStore.replacePost(adapted)` |
  | `post_deleted` | `messagesStore.removePost(postId)` |
  | `typing` | 触发 channel-level typing 指示（暂存 Map<channelId, Set<userId>>） |
  | `status_change` | `usersStore.setStatus(userId, status)` |
  | `channel_viewed` / `multiple_unreads` | `channelsStore.updateUnread(channelId, count)` |

### 实现要点
- 重连：指数退避 1s, 2s, 4s, 8s, 最多 30s；每次重连后**重拉一次当前频道的 posts** 防丢消息
- 关闭页面 / `disconnectWs()` 时清理监听
- 不要使用第三方 ws lib，用 `@mattermost/client` 自带的 `WebSocketClient`

### 验收
1. 在浏览器 A 上发消息，浏览器 B（同 channel）3 秒内看到消息（不依赖手动刷新）
2. 关闭 Mattermost 服务后再开启，WebSocket 在 30 秒内自动重连
3. 在浏览器控制台 `window.__gd.wsBus.addEventListener('posted', console.log)` 可调试事件
4. `npm run type-check` 通过

---

## T8 · Composer 发消息 {#t8}

- **status**: pending
- **依赖**: T4, T6
- **预估**: 1d

### 目标
现有 `Composer.vue` 的发送按钮，从 push 本地数组改为调 `api/posts.ts#createPost`，mock 模式时依然走本地。

### 改动文件
- `src/components/channel/Composer.vue` — emit `'send'` 不变，**只改 emit 后的 handler**
- 新增 `src/composables/useComposer.ts`:
  ```ts
  export function useComposer(channelId: Ref<string>) {
    const sendText = (text: string) => { ... }
    const sendRich = (rich: RichCardData) => { ... }
    return { sendText, sendRich }
  }
  ```
  - 内部根据 `getDataSource()` 分流：mattermost → `createPost`；mock → 写 store
- 父组件（如 OpsChannelView）原来直接修改 messages 数组的逻辑，改成调 `useComposer().sendText(...)`

### 验收
1. 在 Vue 工作台输入框敲一句"测试" → 浏览器 Mattermost 官方 UI（`http://localhost:8065`）能在同一 channel 看到
2. 反向：在官方 UI 发消息 → Vue 工作台 3 秒内显示（这条由 T7 保证）
3. mock 模式下行为不变
4. `npm run type-check` 通过

---

## T9 · 自定义富卡协议 {#t9}

- **status**: pending
- **依赖**: T3, T8
- **预估**: 2d

### 目标
让 RichCard / DocPreview / ChartCard / CCTV 这四类富卡能通过 Mattermost 端到端传递。

### 实现要点

**发送端**（在 `src/mattermost/api/posts.ts` 内）：
```ts
export type CreatePostInput =
  | { kind: 'text'; channelId: string; text: string }
  | { kind: 'rich'; channelId: string; rich: RichCardData }
  | { kind: 'doc';  channelId: string; doc: DocPreviewData }
  | { kind: 'chart'; channelId: string; chart: ChartCardData }
  | { kind: 'cctv'; channelId: string; rich: RichCardData /* 含 cctv 字段 */ }

// 内部根据 kind 映射到 post.type 与 post.props.gd
```

**接收端**（在 `src/mattermost/adapters/message.ts` 与 `custom-post-types.ts`）：
- 根据 `post.type` 进入对应分支，读 `post.props.gd` 还原结构
- 未知 type 降级为纯文本 `MessageData.html`
- 必须保证 `post.props.gd` 的 JSON 与 `src/types/message.ts` 中定义的 RichCardData / DocPreviewData / ChartCardData 完全同构

### 产出文件
- 更新 `src/mattermost/custom-post-types.ts`（不再是占位）
- 更新 `src/mattermost/api/posts.ts` 的 `createPost`
- 更新 `src/mattermost/adapters/message.ts`
- `docs/custom-post-types.md` — 简短的协议规范（给以后阶段二的 Plugin 复用）

### 验收
1. 用 curl 直接 POST：
   ```bash
   curl -X POST http://localhost:8065/api/v4/posts \
     -H "Authorization: Bearer $VITE_MM_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"channel_id":"<id>","message":"装置 A101 报警","type":"custom_gd_rich","props":{"gd":{"variant":"warn","tag":"安全","title":"压力高高报","kv":[{"k":"装置","v":"A101"}],"actions":[{"label":"派工","primary":true}]}}}'
   ```
   Vue 工作台立即显示一张完整 RichCard
2. 在 Vue 工作台触发现有 mock 数据里的"发巡检卡"动作，能发到 MM 并被另一浏览器接收
3. 未知 type（如 `custom_xx_unknown`）显示为纯文本，不报错
4. `npm run type-check` 通过

---

## T10 · Seed 脚本 {#t10}

- **status**: pending
- **依赖**: T9
- **预估**: 0.5d

### 目标
一行命令把现有 `src/data/messages/*.ts` 中的 mock 富卡全部灌进 Mattermost 对应 channel，**用于演示与回归**。

### 产出文件
- `scripts/seed-mm.ts` — 读 mock messages，根据频道名 match channel，逐条调 `createPost`
- `package.json` 新增 script `"seed:mm": "tsx scripts/seed-mm.ts"`
- 依赖：`tsx` 加入 devDependencies

### 验收
1. `npm run seed:mm` 完成后，登录官方 Mattermost UI 在对应 channel 看到与 Vue DEMO 一致的消息流
2. Vue 工作台刷新后也能完整渲染（说明协议端到端通了）

---

## T11 · 验收 Demo {#t11}

- **status**: pending
- **依赖**: T0–T10
- **预估**: 1d

### 目标
跑通一条完整的演示脚本，作为 POC 阶段的 Go/No-Go 闸口。

### 演示脚本（必须全部通过）

1. **冷启动**：从 `docker compose up -d` 起 Mattermost，到 Vue 工作台访问 http://localhost:5173，整体在 60 秒内可用。
2. **登录态**：Vue 工作台顶部头像显示 `admin`，左侧"总部"工作区显示 4 个频道。
3. **历史消息**：进入 `dcs-coord` 频道，能看到 Seed 灌入的富卡（至少 1 张 RichCard + 1 张 DocPreview + 1 张 ChartCard）。
4. **实时新消息**：在浏览器 B 的官方 MM UI 发一条文本，浏览器 A 的 Vue 工作台 3 秒内显示。
5. **反向**：Vue 工作台输入框发"班前会 9:00"，浏览器 B 的官方 UI 即时收到。
6. **富卡端到端**：用 curl 推一张带"派工"按钮的 RichCard，Vue 工作台正确渲染样式与按钮。
7. **CCTV 富卡**：Seed 中包含一张 CCTV 带 AI 框选的卡，Vue 工作台正确渲染百分比定位的方框。
8. **降级演示**：把 `.env.local` 的 `VITE_DATA_SOURCE=mock`，重启 dev server，Vue 工作台行为与改造前一致。
9. **类型检查**：`npm run type-check` 0 错误。
10. **构建**：`npm run build` 0 错误。

### 产出文件
- `docs/poc-demo-script.md` — 上述 10 步的演示脚本（给销售/老板看 Demo 用）
- 录屏一段（mp4，3 分钟内），覆盖步骤 1–7，放 `docs/assets/poc-demo.mp4`（git LFS 或外链）

### 验收
- 内部两人交叉走一遍演示脚本，全部通过
- 把 `ROADMAP.md` 阶段一标记为 `done`，开启阶段二

---

## 阶段一 Definition of Done

- [ ] T0–T11 全部 `status: done`
- [ ] `npm run type-check && npm run build` 全绿
- [ ] 演示脚本 10 步全过
- [ ] 评估报告的"建议下一步"中的三项全部完成（起 MM / 跑通 channels.list+posts.create+WebSocket / 富卡端到端）
- [ ] `docs/phase-2-plugin.md` 内的"开工前提"全部满足
