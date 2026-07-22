# GuDuu 工作台

Claude Code 风格暖米色调 IM 工作台 Demo，行业 AI 工作台通用版（以「示例企业」为演示数据）。

## 技术栈

- Vue 3 + `<script setup>` + Composition API
- Vite 6 + TypeScript
- vue-router 4（hash 模式，便于静态托管）
- Chart.js 4
- 原生 CSS（变量 + 模块化，无运行时 CSS 框架依赖）

## 启动

```bash
npm install
npm run dev          # http://localhost:5173
npm run build        # 类型检查 + 产物到 dist/
npm run preview      # 预览生产构建
npm run type-check
```

## 目录结构

```
src/
├── main.ts                 # 入口
├── App.vue                 # 顶栏 + 三列布局 + RouterView
├── router/                 # hash 路由
├── styles/                 # 全局样式，按模块拆分
│   ├── tokens.css          # 设计变量（暖米色调）
│   ├── reset.css
│   ├── layout.css / topbar.css / sidebar.css
│   ├── channel.css         # 消息流 / 富卡 / CCTV / 文档预览
│   ├── composer.css / right.css / canvas.css
│   └── index.css           # 汇总 @import
├── types/                  # 频道与消息类型
├── data/                   # mock 数据：channels / kpi / messages / charts
├── composables/            # useClock / useCountUp / useChart
├── components/
│   ├── layout/             # TopBar / WorkspaceRail / ChannelSidebar / RightPanel
│   ├── channel/            # Header / MessageStream / MessageItem / RichCard /
│   │                       # CCTVFrame / DocPreview / ChartCard / Composer
│   └── canvas/             # KpiCard / UnitGrid / PanelChart
└── views/
    ├── DashboardView.vue   # # 总览-工作台驾驶舱
    ├── SafetyView.vue      # # 智能-告警中心
    ├── EnergyView.vue      # # 数据-分析建议
    ├── OfficeView.vue      # # 办公-文档协作
    └── DuuChatView.vue     # GuDuu 私聊（/ 斜杠命令）
```

## 后续可细化方向

- 各 view 接入真实接口（WebSocket 推流 / REST 拉取）
- 富卡 actions 接入工单系统
- DocPreview 增加可编辑画布
- ChartCard 支持时间范围切换
- 国际化（i18n）与暗色主题
