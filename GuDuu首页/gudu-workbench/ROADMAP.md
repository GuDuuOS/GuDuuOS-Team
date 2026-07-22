# ROADMAP · GuDuu × Mattermost

> 12 个月的产品演进总图。Claude Code 每次开工前对照本文件确认"当前应该在做哪个里程碑"。

## 阶段视图

```
2026
   M1   M2   M3   M4   M5   M6   M7   M8   M9   M10  M11  M12
 ┌────────────┬────────────────────────────┬────────────────────────────────┐
 │  阶段一    │       阶段二                │        阶段三                  │
 │  POC       │       Plugin 产品化         │        建立壁垒                │
 │  (4 周)    │       (12 周)               │        (~21 周)                │
 │  C 路线    │       B 路线                │        Server Plugin + 治理    │
 └────────────┴────────────────────────────┴────────────────────────────────┘
   ▲                ▲                            ▲
   │                │                            │
   POC 验收           客户试点                       商用上线
```

## 关键里程碑

| # | 里程碑 | 目标日期（相对开工） | 验收闸口 | 当前状态 |
|---|---|---|---|---|
| **M0** | Mattermost 本地实例 + Vue 工作台 mock 模式正常 | T+3d | `docs/env-setup.md` 验收通过 | pending |
| **M1** | 阶段一 POC 完成 | T+4w | `docs/phase-1-poc.md` 全部 done + 演示脚本通过 | pending |
| **M2** | 客户演示反馈 + 阶段二开工决策 | T+5w | 至少 1 家客户书面/口头反馈 + 立项决议 | pending |
| **M3** | Mattermost Plugin 骨架可安装 | T+8w | `gudu-mattermost-plugin/` Sprint 1 完成 | pending |
| **M4** | GuDuu 主题 + 四类自定义富卡 React 实现 | T+12w | Sprint 3 完成 | pending |
| **M5** | Dashboard / Safety / Energy / Office / Todo 视图可用 | T+16w | Sprint 4-5 完成 | pending |
| **M6** | 阶段二完整 .tar.gz 安装包发布 | T+20w | `docs/phase-2-plugin.md` Definition of Done | pending |
| **M7** | 部门 AI 配额 + 审计 Plugin 试点客户上线 | T+32w | 阶段三 DeptLimits + Audit 模块完成 | pending |
| **M8** | 行业插件集市第一个包上架 | T+38w | 行业包（CCTV+数据+告警）上架 GuDuu Registry | pending |
| **M9** | GuDuu 通用版 1.0 商用版本发布 | T+44w | 至少 1 家付费客户、商业 License 商务流程跑通 | pending |

## 当前优先级

**今天最重要的事**：阶段一任务 T0（起 Mattermost 本地实例）。

让 Claude Code 接到这份 ROADMAP 后，工作流如下：

```
1. 读 CLAUDE.md         （理解约束与约定）
2. 读 ROADMAP.md        （知道现在该干哪个里程碑）
3. 读 docs/00-architecture.md  （理解架构）
4. 读 docs/phase-1-poc.md      （找到第一个 status: pending 的任务）
5. 复述方案 → 等用户确认 → 执行 → 更新 status → 提交 PR
```

## 决策点（已决定的不变项）

| 决策 | 选项 | 已选 |
|---|---|---|
| 改造路线 | A 完全替换 / B Plugin 化 / C 后端复用 | **B + C 混合** |
| 阶段一前端 | 复用 Vue DEMO / 直接 React 重写 | **复用 Vue DEMO（C 路线）** |
| Mattermost License 路径 | AGPL / 商业 License | **国企私有化用 AGPL；SaaS 时再议** |
| Mattermost 版本 | Team Edition / Enterprise Edition | **Team Edition（开源）** |
| 部署形态 | 私有云 / 公有云 SaaS | **优先私有化部署** |

## 待决策（阶段一末期需要拍板）

- [ ] 阶段二是否启动？看 POC 客户反馈
- [ ] 前端 React 培训方式（内训 / 外训 / 招人）
- [ ] 阶段二 Plugin 仓库是否开源？（建议核心私有，UI 主题/通用富卡可开源）
- [ ] 商业 License 与 Mattermost 公司的接触时机

## 风险登记

| 风险 | 影响 | 状态 |
|---|---|---|
| Mattermost 上游 API breaking change | 中 | 跟随主版本 + CI 兼容性测试 |
| 客户对"基于 Mattermost"有抵触 | 中 | 走品牌定制 + Custom Branding 解决感知 |
| 团队 React 学习曲线导致阶段二延期 | 高 | 阶段一末期同步组织培训 |
| AGPL 在 SaaS 场景的法务风险 | 中 | 阶段二上线前接触 Mattermost 商务 |
| 部门 AI 治理与现有客户 AD/审批流冲突 | 高 | 阶段三试点时做客户专项调研 |
