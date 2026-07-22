# 阶段三 · 建立壁垒（Server Plugin · 部门 AI 治理 + 审计）· 纲要

> 阶段三是 GuDuu 真正的产品差异化所在 —— Mattermost 不提供、Slack/Teams 也不提供，但中国国企/央企/政府客户**强需求**的能力。
>
> 本阶段细化将在阶段二通过验收后展开。这里只列方向、关键能力与契约。

## 1. 阶段三的产品立意

> "Mattermost 让我有了 IM；GuDuu 让我敢把 AI 用在生产/安全/调度场景里。"

阶段三建设三套核心能力，它们都是中国大型企业上 AI 必须有、但开源 IM 普遍缺失的：

1. **部门级 AI 配额与治理**（DeptLimits）
2. **数据密级与对话边界**（Confidentiality Boundary）
3. **AI 操作审计与回放**（Audit Trail）

加上一套配套的：

4. **行业插件集市**（Vertical Plugin Marketplace）—— 化工 / 电力 / 政务 / 银行的开箱即用包

## 2. 新仓库：`gudu-mattermost-server-plugin/`

```
gudu-mattermost-server-plugin/
├── plugin.json
├── server/
│   ├── plugin.go
│   ├── deptlimits/
│   │   ├── model.go        # 数据模型
│   │   ├── store.go        # KV store
│   │   ├── enforce.go      # 每次 AI 调用前的配额/密级校验
│   │   └── api.go          # REST: GET/PUT /api/v1/dept-limits
│   ├── ai-gateway/
│   │   ├── proxy.go        # 拦截所有 LLM 调用
│   │   ├── budget.go       # Token 预算扣减
│   │   ├── ratelimit.go    # 速率限制（令牌桶）
│   │   ├── prompt-shield.go # Prompt 注入防护
│   │   └── classifier.go   # 敏感词/密级分类
│   ├── audit/
│   │   ├── logger.go       # 审计落库（PostgreSQL 单独 schema）
│   │   ├── api.go          # 查询接口
│   │   └── export.go       # 导出 CSV/JSON（合规交付）
│   └── marketplace/
│       └── registry.go     # 行业插件元数据
├── webapp/
│   └── system-console/     # System Console 注入页（部门治理后台）
└── db/migrations/          # PostgreSQL schema
```

## 3. 三套核心能力

### 3.1 部门级 AI 配额与治理（DeptLimits）

继承自现 `src/types/channel.ts#DeptLimits`，扩展为持久化模型：

```go
type DeptLimits struct {
    TeamID         string  // 对应 Mattermost Team
    MemberCap      int
    VisibilityDefault string  // public / private
    AI struct {
        Enabled       bool
        Model         string   // claude-sonnet-4 / qwen-72b / 自托管 ...
        TokenBudget   int      // 月度，单位 万 token
        RateLimit     int      // 次/分钟
        MaxLevel      string   // 公开 / 内部 / 机密
        MemoryScope   string   // 仅本部门 / 全集团
        AllowControl  bool     // AI 是否可执行控制类动作（高危）
        Audit         bool
    }
}
```

API：
- `GET  /plugins/com.guduu.governance/api/v1/dept-limits?team_id=...`
- `PUT  /plugins/com.guduu.governance/api/v1/dept-limits`
- `GET  /plugins/com.guduu.governance/api/v1/dept-limits/usage?team_id=...&period=2026-05`

UI 在 Mattermost System Console 新增"GuDuu Governance"分类。

### 3.2 数据密级与对话边界（Confidentiality Boundary）

- 每个 Channel 标注密级（默认继承 Team）
- 每条 Post 标注密级（默认继承 Channel）
- AI Gateway 在每次 LLM 调用前做"密级合规校验"：上下文中**所有** Post 的 max 密级 ≤ Team 的 `MaxLevel`
- 违规：拦截 + 审计 + 用户提示
- 跨部门 DM：自动判定密级取上限

### 3.3 AI 操作审计与回放（Audit Trail）

每次 AI 调用落审计日志（Append-only），包含：

- `trace_id` / `user_id` / `team_id` / `channel_id` / `post_id`
- `model` / `prompt_hash` / `prompt_size` / `output_size` / `tokens_in` / `tokens_out`
- `confidentiality_in` / `confidentiality_out`
- `tools_called`（如有 function calling）
- `decision`（allowed / blocked / degraded）
- `latency_ms`

提供：
- 审计查询 UI（用户可查"我的对话"、Admin 可查全部）
- 导出 CSV/JSON 接口（合规审计需要）
- 关联回放：根据 `trace_id` 还原一次完整 AI 调用全链路

## 4. 行业插件集市

- 起一个独立的"GuDuu Plugin Registry"（可以是 GitHub Org + 静态站点）
- 每个行业包是一组 Mattermost Plugin 的组合：
  - 化工：CCTV 接入 + DCS 联动 + 应急指挥模板
  - 电力：调度指令 + 故障树
  - 政务：公文流转 + 政策检索
  - 银行：风控话术 + 客户档案
- 客户在 GuDuu System Console 一键安装

## 5. 工作量粗估（开工时再细化）

| 模块 | 周期 |
|---|---|
| DeptLimits Server Plugin + UI | 4 周 |
| AI Gateway（含 Prompt Shield） | 4 周 |
| Audit Trail（含导出） | 3 周 |
| 行业包 × 4 | 6 周（可分批） |
| 整体集成 + 客户试点 | 4 周 |
| **合计** | **约 21 周（~5 个月）** |

## 6. 商业意义

阶段三完工后，GuDuu 的产品标签可以从"基于 Mattermost 改的工作台"变成：

> **"中国第一家在 IM 之上做企业 AI 治理的产品"**

这是任何开源 IM（包括 Mattermost 官方）短期不会做、但客户花钱买的能力。

## 7. 开工前提

- [ ] 阶段二 Definition of Done 全部通过
- [ ] 已有至少 1 个客户愿意为"部门 AI 治理"付费试点
- [ ] 法务 + 合规已确认审计日志的存证要求（可能涉及《数据安全法》《个人信息保护法》）
- [ ] 后端团队补齐 Go + Mattermost Plugin Framework 经验

## 8. 阶段三的 Definition of Done

- [ ] DeptLimits 在试点客户跑通 1 个月以上、无 P0 故障
- [ ] 至少 1 次完整的"审计导出 → 客户合规检查通过"全流程
- [ ] 至少 1 个行业包上架 GuDuu Plugin Registry 并被客户安装
- [ ] 产品定价模型确定（按部门数 / 按 Token 用量 / 按席位）
