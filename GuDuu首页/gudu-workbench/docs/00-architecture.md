# 00 · 架构总图

> 本文档是 Claude Code 写代码前的"地图"。不深入代码细节，只回答：**这个项目长什么样、各部分怎么连、阶段一改什么、不改什么**。

## 1. 总图（阶段一 POC 形态）

```
┌────────────────────────────────────────────────────────────────────┐
│  浏览器                                                            │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────┐      │
│  │  GuDuu Vue 工作台（本仓库）                              │      │
│  │                                                          │      │
│  │   src/views/*       ── 频道视图，组件层尽量不动          │      │
│  │   src/components/*  ── RichCard / Doc / Chart / CCTV     │      │
│  │   src/composables/* ── useChannels / useMessages 等      │      │
│  │           │                                              │      │
│  │           │  读                                          │      │
│  │           ▼                                              │      │
│  │   src/stores/*      ── 运行时数据（reactive 单例）       │      │
│  │           ▲                                              │      │
│  │           │  写入                                        │      │
│  │   ┌───────┴──────────────────────────────┐               │      │
│  │   │  src/mattermost/  ★ 阶段一新增的核心  │               │      │
│  │   │                                       │               │      │
│  │   │   client.ts      auth.ts              │               │      │
│  │   │   ws.ts          custom-post-types.ts │               │      │
│  │   │   api/posts      api/channels         │               │      │
│  │   │   adapters/message  adapters/channel  │               │      │
│  │   └───────────────────┬───────────────────┘               │      │
│  └───────────────────────┼─────────────────────────────────┘      │
│                          │ HTTP + WebSocket                        │
└──────────────────────────┼──────────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────────────┐
│  Mattermost 实例（Docker Compose / 本地）                          │
│                                                                    │
│   POST /api/v4/posts        ← Composer 发消息                      │
│   GET  /api/v4/channels     ← Sidebar 频道列表                     │
│   GET  /api/v4/posts/{id}   ← 历史消息                             │
│   WS   /api/v4/websocket    ← 实时事件 (posted / typing / ...)     │
│                                                                    │
│   PostgreSQL（自动起）                                             │
└────────────────────────────────────────────────────────────────────┘
```

## 2. 改造原则（一个字：薄）

GuDuu 现有的 Vue 组件已经成型。**阶段一只在两个地方动手**：

1. 新增 `src/mattermost/`：所有与 Mattermost 的通讯都封闭在这一层，向上提供 GuDuu 的语义类型（来自 `src/types/`）。
2. 改造 `src/composables/use*.ts`：把原本读 mock 数据的逻辑，改成读 `src/stores/*` 里由 Mattermost 适配层填充的数据。

组件本身（`src/components/`、`src/views/`）几乎不动 —— 这是回到 mock 模式做演示的保险。

## 3. 数据流：以「Composer 发一条富卡消息」为例

```
用户在 Composer 里输入 "/safety 巡检"
        │
        ▼
Composer.vue            （现有组件，不改）
        │
        │ emit('send', payload)
        ▼
useComposer (新增)      （组合式逻辑）
        │
        │ 判断是斜杠命令 → 调 src/mattermost/api/slash.ts
        │ 否则           → 调 src/mattermost/api/posts.ts
        ▼
src/mattermost/api/posts.ts
        │
        │ POST /api/v4/posts
        │ body: { channel_id, message, type: 'custom_gd_rich', props: { gd: RichCardData } }
        ▼
Mattermost Server
        │
        │ WebSocket 广播 "posted" 事件
        ▼
src/mattermost/ws.ts    （订阅 posted）
        │
        │ adapters/message.ts 把 MM Post → MessageData
        ▼
src/stores/messages.ts  （Pinia/reactive 单例）
        │
        │ Vue 响应式
        ▼
MessageStream.vue → MessageItem.vue → RichCard.vue
（这一路 UI 组件不需要任何修改，因为 MessageData 类型不变）
```

## 4. 关键类型映射（必读）

| GuDuu 类型（src/types） | Mattermost 数据结构 | 转换在哪里 |
|---|---|---|
| `ChannelItem` | `Channel { id, type, display_name, name, total_msg_count, last_post_at }` | `src/mattermost/adapters/channel.ts` |
| `DmItem` | `Channel` (type='D' 直接消息 / 'G' 群消息) + `User` 信息 | `adapters/channel.ts` |
| `MessageData` | `Post { id, message, user_id, type, props, create_at }` | `adapters/message.ts` |
| `RichCardData` | `post.type = 'custom_gd_rich'`, `post.props.gd: RichCardData` | `custom-post-types.ts` |
| `DocPreviewData` | `post.type = 'custom_gd_doc'`,  `post.props.gd: DocPreviewData` | `custom-post-types.ts` |
| `ChartCardData` | `post.type = 'custom_gd_chart'`, `post.props.gd: ChartCardData` | `custom-post-types.ts` |
| `Sender` | `User { id, username, nickname, ... }` | `adapters/user.ts` |
| `WorkspaceMeta`（部门） | `Team { id, name, display_name }` | `adapters/team.ts`（阶段一够用） |
| `DeptLimits` AI 配额等 | 阶段一不映射 | 阶段三在 Server Plugin 中扩展 |

## 5. WebSocket 事件订阅清单（阶段一）

Mattermost WebSocket 事件名 → GuDuu 内部响应：

| MM 事件 | 触发 | 处理 |
|---|---|---|
| `hello` | 连接建立 | 记录 server_version、seq |
| `posted` | 新消息 | 转换为 MessageData，push 到 `stores/messages` |
| `post_edited` | 消息被编辑 | 替换对应 id |
| `post_deleted` | 消息删除 | 从 store 移除 |
| `typing` | 有人正在输入 | 显示 typing 指示 |
| `channel_viewed` / `multiple_unreads` | 已读 / 未读 | 更新 `stores/channels` 的 `unread` |
| `user_added` / `user_removed` | 成员变更 | 更新 `stores/members` |
| `status_change` | 在线状态 | 更新 `stores/users` 的 online |
| `reaction_added` / `reaction_removed` | 反应 | 阶段一可暂时忽略 |

完整列表见 Mattermost 官方：https://api.mattermost.com/#tag/WebSocket

## 6. 不动的东西（阶段一保护清单）

- 全部 `src/components/` 下的 `.vue` 文件（除非任务卡里明确点名）
- 全部 `src/views/` 下的 `.vue` 文件
- 全部 `src/styles/` 下的 CSS
- `vite.config.ts`、`tsconfig.json`（除非新增路径别名）
- `package.json` 仅允许新增依赖：`@mattermost/client`（或 `@mattermost/types`），不允许换 UI 库

## 7. 后续两阶段的关系（提一下，不展开）

- **阶段二**（B 路线）：会另起一个新仓库 `gudu-mattermost-plugin/`（Mattermost Webapp Plugin 工程，TypeScript + React），把本仓库阶段一沉淀下来的「自定义富卡协议」「业务画布逻辑」搬过去用 React 重写。**本仓库到阶段二会冻结为"参考实现 / 演示版"**，但不会被废弃。
- **阶段三**（建立壁垒）：会再起 `gudu-mattermost-server-plugin/`（Go），实现部门 AI 治理与审计。本仓库依旧不动。

详见 `docs/phase-2-plugin.md` 与 `docs/phase-3-moat.md`。
