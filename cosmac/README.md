# cosmac/ —— GuDuu OS 自有扩展层

GuDuu OS 所有自己的业务代码都在这里，与上游 `synapse/` 源码分离（详见根目录 `CLAUDE.md`）。

## 当前进度

✅ **第 1 块：主 AI 控制层（进行中）**
- 骨架：通过 Matrix Application Service 接入，主 AI 能"看到"群里每条消息、被邀请时自动进群、把消息回给群。
- 多模型已接入：`echo`/`claude`/`openai` 可配置（`ai/`）；无 API key 时自动降级 `echo`，bot 照常运行。
- 待做：让主 AI 真正"调用"IM 能力（创建群、查聊天记录等 —— 工具调用）。

### 启用真实模型
```bash
export COSMAC_LLM_PROVIDER=claude        # 或 openai（旧 GUDUU_* 仍兼容）
export ANTHROPIC_API_KEY=sk-ant-...     # openai 则配 OPENAI_API_KEY
.venv/bin/python -m cosmac
```
key 不写进代码，由 SDK 从环境变量读；部署到 Google Cloud 时配进 Secret/环境变量。

## 目录

| 路径 | 作用 |
|------|------|
| `config.py` | 运行配置（连哪个 Synapse、token、模型后端），支持环境变量覆盖 |
| `ai/base.py` | LLM 统一接口（多模型抽象层的核心） |
| `ai/echo.py` | 占位"回显"模型，用于打通链路；以后换成 Claude/OpenAI |
| `ai/__init__.py` | `get_provider(name)` 按名取模型后端 |
| `bots/matrix_client.py` | 主 AI 操作 IM 的"手"（加入房间、发消息…） |
| `bots/appservice_bot.py` | 主 AI 的"眼睛+反应"：收 Synapse 推来的事件并响应 |
| `__main__.py` | 启动入口 |
| `tests/` | 单元测试 |

## 本地跑起来

前提：Synapse 已按根目录 `CLAUDE.md` §9 启动（监听 8008），且 `homeserver.yaml`
已加载 `guduu-bot.yaml`（appservice 注册）。

```bash
# 1. 启动主 AI Bot（项目根目录下）
.venv/bin/python -m cosmac

# 2. 用 alice 建群并邀请 @guduu:guduu.local，然后发消息
#    Bot 会自动进群并回复
```

## 测试

```bash
.venv/bin/python -m unittest discover cosmac/tests
```
