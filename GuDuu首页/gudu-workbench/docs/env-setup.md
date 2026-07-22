# 环境搭建 · Mattermost 本地实例

> 阶段一开发用的 Mattermost 实例，**只为本地联调**，不用做安全加固。本文档供 Claude Code 完整跑通"从 0 到 API 可调用"。

## 1. 前置

- macOS / Linux / Windows + Docker Desktop（已运行）
- 8065 / 8067 端口空闲
- 至少 4 GB 可用内存

## 2. 启动（一条命令）

```bash
cd docs/env
docker compose up -d
# 等待约 30 秒，PostgreSQL 初始化完成
docker compose logs -f mattermost | grep "Server is listening"
```

`docs/env/docker-compose.yml` 已在 Claude Code 的任务卡里作为 T0 任务产出（见 `phase-1-poc.md#t0`）。

## 3. 首次初始化

1. 浏览器打开 http://localhost:8065
2. **创建管理员账号**：
   - Email: `admin@guduu.local`
   - Username: `admin`
   - Password: `Guduu!Admin#2026`
3. 创建第一个 Team：
   - Team Name: `guduu`
   - Team URL: `guduu`
4. 创建几个测试 Channel（作为后续 Vue 工作台对接目标）：
   - `dcs-coord`（公开） — 对应 GuDuu 的"DCS-内外操协同"
   - `emergency`（公开） — "应急-分级通报"
   - `prod-daily`（公开） — "生产-日报周报"
   - `safety-briefing`（公开） — "班前安全交底"

## 4. 生成 Personal Access Token（PAT）

阶段一前端用 PAT 直接调 API，**仅开发用**（生产期会改成 OIDC/LDAP）。

1. **开启 PAT 功能**（管理员）：
   - System Console → Integrations → Integration Management
   - **Enable Personal Access Tokens**: `true`
   - Save
2. **赋予测试账户权限**：
   - System Console → User Management → Users
   - 找到 `admin` 用户，编辑其 Role，勾选 `system_user_access_token`
3. **生成 Token**：
   - 右上角头像 → Profile → Security → Personal Access Tokens → Create Token
   - 描述：`gudu-workbench-dev`
   - **保存输出的 Token 字符串**（只显示一次）
4. **填到项目根目录的 `.env.local`**：
   ```
   VITE_MM_URL=http://localhost:8065
   VITE_MM_TEAM=guduu
   VITE_MM_TOKEN=<刚才的 token>
   VITE_DATA_SOURCE=mattermost
   ```

## 5. 一键灌入演示数据（可选，T2 任务后启用）

T2 任务会产出 `scripts/seed-mm.ts`，能把 `src/data/messages/*` 里的 mock 富卡批量发到对应 channel，方便给客户演示。

```bash
npm run seed:mm
```

## 6. 验收：API 能调通的最小用例

完成上述步骤后，应该可以在终端直接 curl：

```bash
# 列出当前用户加入的所有团队
curl -H "Authorization: Bearer $VITE_MM_TOKEN" \
     http://localhost:8065/api/v4/users/me/teams

# 列出 guduu 团队下当前用户加入的 channel
TEAM_ID=$(curl -s -H "Authorization: Bearer $VITE_MM_TOKEN" \
  http://localhost:8065/api/v4/teams/name/guduu | jq -r .id)
curl -H "Authorization: Bearer $VITE_MM_TOKEN" \
     http://localhost:8065/api/v4/users/me/teams/$TEAM_ID/channels
```

如果返回 200 + JSON 数组，环境就绪。

## 7. 排错

| 症状 | 排查 |
|---|---|
| 8065 端口被占用 | `lsof -i :8065`，调 `docker-compose.yml` 的 ports 映射到 18065 |
| `Database connection failed` | `docker compose down -v && docker compose up -d` 重置卷 |
| Token 调 API 返回 401 | 确认 System Console 的 PAT 开关已开 + 用户有 `system_user_access_token` 角色 |
| WebSocket 连接被拒 | 检查 mattermost 的 `ServiceSettings.AllowCorsFrom = "*"`（开发用） |

## 8. 关停

```bash
cd docs/env
docker compose down       # 保留数据
docker compose down -v    # 同时删除数据卷
```
