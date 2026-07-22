# 阶段二 · 产品化（Webapp Plugin 化）· 纲要

> 阶段二的细化将在阶段一通过验收后展开。本文档先给方向、组织结构与关键决策点。
> **本仓库（gudu-workbench）在阶段二**只作为"参考实现/演示版"，阶段二的工程主体在一个新仓库 `gudu-mattermost-plugin/`。

## 开工前提（必须满足才能进入阶段二）

- [ ] 阶段一 `Definition of Done` 全部通过
- [ ] POC 已经给至少 1 个目标客户演示过，反馈支持继续产品化
- [ ] 前端团队补齐 React 18 + Redux Toolkit 基础（建议 1-2 周培训）
- [ ] 法务确认 License 路径（私有化 / SaaS 商业 License）

## 1. 阶段二目标

把"GuDuu 工作台 = Mattermost + 一组 Plugin"做成现实：
- 用户**直接打开 Mattermost 官方 Webapp**（或 desktop / 移动端），看到的就是 GuDuu 工作台。
- Mattermost 服务器**不需要 fork**，只在 plugins 目录安装一个 `.tar.gz` 即可。
- 同一份 Plugin 既能在客户私有部署用，也能在 GuDuu SaaS 用。

## 2. 新仓库结构（建议）

```
gudu-mattermost-plugin/
├── CLAUDE.md                       # Claude Code 进入即读
├── plugin.json                     # MM Plugin manifest
├── go.mod                          # Server 部分
├── server/
│   ├── plugin.go                   # 主入口（implements plugin.MattermostPlugin）
│   ├── api.go                      # 自定义 HTTP 路由（/plugins/com.guduu.workbench/api/*）
│   ├── command.go                  # 斜杠命令处理
│   └── store/                      # KV store 封装
├── webapp/                         # Webapp Plugin（TS + React）
│   ├── src/
│   │   ├── index.tsx               # registerPlugin 入口
│   │   ├── components/
│   │   │   ├── lhs/                # 左侧栏注入（频道列表自定义渲染）
│   │   │   ├── rhs/                # 右侧栏（AiChatPanel 等价物）
│   │   │   ├── post-types/         # 自定义 post type 渲染器
│   │   │   │   ├── RichCard.tsx    # ← 把现 gudu-workbench RichCard.vue 用 React 重写
│   │   │   │   ├── DocPreview.tsx
│   │   │   │   ├── ChartCard.tsx
│   │   │   │   └── CCTV.tsx
│   │   │   ├── views/              # Dashboard/Safety/Energy/Office/Todo
│   │   │   └── modals/             # ChannelAdmin/DepartmentCreate 等
│   │   ├── hooks/
│   │   ├── store/                  # Redux slice（用 Redux Toolkit）
│   │   └── theme/                  # GuDuu 暖米色调注入
│   ├── package.json
│   └── webpack.config.js
└── build/
    └── make-plugin.sh              # 打包 .tar.gz
```

## 3. 工作清单（粒度比阶段一粗，正式开工时再细化为任务卡）

### Sprint 1 · 骨架（2 周）
- 用 `mattermost/mattermost-plugin-starter-template` 起项目
- 实现 plugin manifest、最小 server stub、webapp 注册
- 在本地 Mattermost 实例安装通过

### Sprint 2 · 主题与品牌（1 周）
- Custom Branding：替换 Logo、登录页文案、Favicon
- 注入 CSS：覆盖 Mattermost CSS Variables，还原 GuDuu 暖米色调
- 字体加载

### Sprint 3 · 自定义富卡（2 周）
- 实现四类 Post Type Component（RichCard / DocPreview / ChartCard / CCTV）
- 协议复用阶段一沉淀的 `custom_gd_*`（已在 `docs/custom-post-types.md` 规范）
- Chart.js 直接复用、CCTV 框选直接搬运逻辑

### Sprint 4 · 业务视图（2 周）
- 注入 LHS Section：把 GuDuu 的"驾驶舱 / 待办 / 安全 / 能效 / 公文"作为左侧顶部分类项
- 注入新路由（`/plugins/com.guduu.workbench/views/dashboard` 等）
- 视图内容用 React 重写（Dashboard 优先级最高）

### Sprint 5 · AI Chat 面板（2 周）
- 注入 RHS Plugin Component，挂载 GuDuu 的 AiChatPanel 等价物
- 与 Mattermost Posts 系统打通：AI 回复可以"以 Bot 身份发回到当前 channel"

### Sprint 6 · 部门治理 UI（2 周）
- ChannelAdminModal / DepartmentCreateModal 用 React 重写
- 接入 Server Plugin 提供的部门元数据 API（阶段三深化）

### Sprint 7 · 打包与分发（1 周）
- CI：GitHub Actions 出 .tar.gz
- 文档：客户安装指南
- 与阶段一 POC 客户做一次"换皮"演示

## 4. 关键技术决策（开工前需要拍板）

| 决策点 | 选项 | 建议 |
|---|---|---|
| webapp 状态管理 | Redux Toolkit / Zustand / Jotai | Redux Toolkit（与 Mattermost 主框架一致，可复用 selectors） |
| 样式方案 | CSS Modules / styled-components / Tailwind | CSS Variables + CSS Modules（与 Mattermost 一致，不引入 Tailwind） |
| 图标 | Mattermost 自带 / lucide / 自绘 SVG | 自绘 SVG（沿用阶段一的视觉） |
| Chart 库 | Chart.js / Recharts / D3 | Chart.js（与阶段一一致） |
| 国际化 | i18next | i18next（Mattermost 自带） |

## 5. 风险点

| 风险 | 缓解 |
|---|---|
| Mattermost Plugin API breaking change | 锁定 mattermost-server 主版本，CI 跑兼容性矩阵 |
| Webapp 微前端 module federation 冲突 | 严格按 Mattermost 模板的 webpack externals 设置 |
| 部门治理需要的字段 Mattermost 不存原生 | 用 plugin KV store + 自定义 HTTP 路由 |
| 移动端 React Native 不能直接复用 Web 组件 | 优先级降级：阶段二只保证 Web/Desktop，移动端阶段三或独立项目 |
| 团队 React 学习曲线 | 阶段一末期提前组织培训 + Pair programming |

## 6. 阶段二的 Definition of Done

- [ ] `.tar.gz` 在两个不同版本的 Mattermost 上安装成功
- [ ] 同一份 Plugin 在客户私有部署 + GuDuu 演示环境两边都跑通
- [ ] 阶段一的 POC 客户在新的 Webapp Plugin 形态下完整跑通演示脚本
- [ ] 阶段三的 Server Plugin 接口契约已经在本仓库的 `server/api.go` 留好桩
