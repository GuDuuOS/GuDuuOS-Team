# GuDuu OS

> 基于 [Matrix (Synapse)](https://github.com/element-hq/synapse) 的 IM + **主 AI 控制层**。
> 在标准 IM（聊天/群组/联邦）之上，叠加一个能感知并操作 IM 全部功能的 AI 系统：
> 主 AI 能拆解任务、组建专班、调配「人 / AI 同事 / 技能 / 知识库 / 规则」，
> 并内置会员变现、外部工作流对接与 OEM 白牌发行体系。

## 核心特性

- **主 AI 中枢**：私聊即全局助理——跨频道统筹、拆任务、建专班拉人派单、审核回填；频道内是该频道的专属分身（资源严格隔离）
- **群级智能配置**：每个频道独立的 人设 / 技能 / 智能体 / 规则（条目+Markdown 规则文档）/ 知识库（RAG）/ 记忆，写入房间 state 多端同步，服务端强制隔离
- **任务看板**：AI 拆解登记、真人+AI 共同执行、逾期提醒、归档催办
- **多模型可插拔**：Claude / OpenAI / DeepSeek(方舟或官方) / Gemini 统一抽象，配置切换、无 key 自动降级
- **会员与门控**：免费/付费/创作者分层，能力门控+用量配额服务端强制；订单/支付抽象已就绪
- **外部工作流**：对接 n8n / Dify / Coze / ComfyUI 等平台（连接器引擎+异步回调），不自建引擎
- **OEM 发行版**：`distro/` 四容器 docker 一键部署（自动 HTTPS），GuDuu Nexus 母舰统一 KEY 授权 / LLM 网关计量 / 心跳遥测

## 仓库结构

| 目录 | 说明 |
|---|---|
| `cosmac/` | GuDuu OS 服务端（appservice bot、AI 抽象层、知识库/技能/会员/交易、DB） |
| `client/` | Web 客户端（Vue 3 + Vite） |
| `distro/` | OEM 发行版（docker compose 四容器 + install/update/doctor 脚本） |
| `nexus/` | GuDuu Nexus 母舰（KEY 签发/实例注册/心跳/token 钱包） |
| `console/` | Nexus 数据大屏前端 |
| `synapse/` | 上游 Synapse 源码（**只读参考**，协议层零改动） |
| `docs/` | 功能清单（FEATURES）、版本规则（VERSIONING）等 |

## 文档地图

- **[CLAUDE.md](CLAUDE.md)** — 项目宪法：架构原则、数据存储分层、路线图、开发守则
- **[ARCHITECTURE.md](ARCHITECTURE.md)** — 系统架构总览（组成/数据流转/AI 工作方式）
- **[docs/FEATURES.md](docs/FEATURES.md)** — 已上线功能全貌
- **[docs/VERSIONING.md](docs/VERSIONING.md)** — 版本号规则（SemVer）与发版/周报/月报流程
- **[DEVLOG.md](DEVLOG.md)** — 开发日志（每次交付一条，版本发布条目含「新增/修复/优化/变更」）
- **[TODO.md](TODO.md)** — 待办清单

## 版本与更新

对外版本号走标准 SemVer（`MAJOR.MINOR.PATCH`），发版提交统一
`release: GuDuu OS X.Y.Z (patch|minor|major)` 格式并打 tag `vX.Y.Z`——
在 [Releases/Tags](../../tags) 与 [DEVLOG.md](DEVLOG.md) 均可追溯每一版的变更内容。

## 架构铁律

**不改 Synapse 核心。** 全部业务逻辑在独立扩展层 `cosmac/`，经 Synapse 的
Application Service 协议与管理 API 接入；Matrix 协议层（`/_matrix/*`、`m.*` 事件）零改动，
标准 Matrix 客户端始终兼容。

## 本地开发

```bash
# 后端测试（内存 SQLite、零外部依赖）
.venv/bin/python -m unittest discover -s cosmac/tests

# 客户端
cd client && npm install && npm run dev

# Lint
.venv/bin/ruff check cosmac/
```

完整的本地运行环境（Synapse + bot + 客户端联调）见 [CLAUDE.md](CLAUDE.md) §9。

---

© GuDuu · 本仓库为私有项目
