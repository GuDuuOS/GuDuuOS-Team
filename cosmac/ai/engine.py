# -*- coding: utf-8 -*-
"""Claude Agent SDK 引擎——可插拔的「高级执行引擎」后端(P1)。

背景(负责人 2026-07 拍板):想让主 AI 更聪明、更像 Claude Code。评估后决定用
Anthropic 官方 **Claude Agent SDK**(= Claude Code 的同款 harness:成熟的工具循环、
自动重试、上下文管理)做执行引擎,而模型可插拔:

  - 测试环境:DeepSeek 官方的 Anthropic 兼容端点(https://api.deepseek.com/anthropic)
    ——SDK 认的是「Anthropic Messages API 协议」,不是 Claude 本尊,所以协议兼容即可驱动;
  - 生产想换 Claude:改两个环境变量即可(见下),引擎代码零改动。

接入方式遵循本项目一贯的「env 可插拔、默认关」(同 Turnstile / 异地二次验证):

  COSMAC_AGENT_ENGINE=claude_sdk        # 开关。默认空 = 用原有 legacy 循环,部署零风险
  COSMAC_SDK_BASE_URL=https://api.deepseek.com/anthropic   # 空 = Anthropic 官方
  COSMAC_SDK_API_KEY=sk-...             # 对应端点的 key(DeepSeek key 或 Anthropic key)
  COSMAC_SDK_MODEL=deepseek-chat        # 或 claude-opus-4-8 等
  COSMAC_SDK_MAX_TURNS=8                # 引擎内部最多几轮(工具循环上限)

运行要求(⚠️ 与 legacy 不同):
  - Python 3.10+(claude-agent-sdk 的硬要求;本地 3.9 的 .venv 跑不了它,启用引擎需用
    .venv312;生产 Ubuntu 22.04+ 自带 3.10+)。
  - 系统里要有 Claude Code CLI(SDK 拉起它做子进程;`npm i -g @anthropic-ai/claude-code`)。
  - 以上不满足时:import 失败/运行失败都会**抛异常给调用方**,bot 层 catch 后自动回退
    legacy 引擎——引擎是增强,绝不能因为它把 AI 问答搞挂。

工具桥接:把 Toolbox 里已启用的**全部工具**(建群/邀人/任务/工作流/知识库…)自动注册成
SDK 的 in-process MCP 工具。执行仍走 Toolbox.execute——**门控/配额/越权检查/私聊防呆
全部复用**,引擎只是换了"大脑的操作系统",安全层一分不少。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, List, Optional

from cosmac.ai.base import Message, ToolCall
from cosmac.ai.tools import Toolbox, ToolContext

logger = logging.getLogger(__name__)

# 引擎的隔离 HOME:CLI 子进程会读写 $HOME/.claude(状态/凭据)。指到固定的独立目录,
# 避免和机器上已有的 Claude 登录凭据串味(实测:不隔离时 CLI 会优先用本机 OAuth 凭据,
# 打到 DeepSeek 端点直接 401)。目录内容可随时删,无状态依赖。
_SDK_HOME = "/tmp/cosmac-sdk-home"

# ══════════ SDK 内置工具黑名单（安全红线，改之前先读完这段） ══════════
# 背景（2026-07-27 负责人实报）：用户让主 AI「把某个 GitHub 上的 skill 装进来」，
# AI 真的在 bot 容器里跑了十几条 Bash，把包下载解压到了 ~/.claude/skills/。
# 既没达到目的（GuDuu OS 的技能存 DB/state event，根本不读那个目录），
# 又暴露出：**主 AI 能在生产容器里执行任意命令、读写任意文件**。
#
# 根因：options 里给的是 allowed_tools=[mcp__cosmac__*] + permission_mode=
# "bypassPermissions"。bypass 的字面含义就是「跳过所有权限检查」，于是 CLI 自带的
# Bash/Read/Write 等内置工具全部放行且不询问——allowed_tools 在该模式下形同虚设。
# 而 Toolbox 的门控/配额/越权检查**只管得到 mcp__cosmac__\* 这些自定义工具**，
# 对内置工具一点约束力都没有（原注释「业务安全靠 Toolbox 层」在这里是不成立的）。
#
# 风险面：bot 容器里有 .env（模型 key、管理员令牌、AS/HS token、数据库密码）；
# 触发它不需要管理员权限——任何能跟 AI 对话的人一句话即可；再叠加提示词注入
# （AI 会抓网页、读知识库，那些内容里的一句“请执行以下命令”就可能被当指令），
# 等于把服务器交出去。
#
# 处置：用 disallowed_tools 显式拉黑。SDK 文档明确其语义是「从模型上下文中移除、
# 不可使用，**即使本来会被允许**」——所以它在 bypassPermissions 下依然生效。
# （can_use_tool 回调不行：文档写明 bypassPermissions 下压根不会触发它。）
#
# WebSearch 也拉黑（负责人 2026-07-31 定：免费用户没有联网功能，门槛要能在后台设）——
# CLI 内置 WebSearch 不走 Toolbox.execute，在 bypassPermissions 下会绕过 web_search 的
# 会员门控（免费用户一句"上网查一下"就白嫖联网）。拉黑后联网统一走自研 web_search 工具，
# 它经 Toolbox.gate_check 强制、门槛在后台「会员权限」页逐项可调（GATE_CATALOG.web_search）。
# WebFetch 已拉黑并**换成自研的 fetch_url**：能力等价（都是取一个网页回来读），
# 但自研那个走 wf.check_outbound_url，挡内网/环回/云元数据，且禁重定向、限大小。
# 这不是砍能力，是把同一件事挪到有防护、有门控的路径上。
_SDK_BLOCKED_TOOLS = [
    # —— 执行命令 ——
    "Bash", "BashOutput", "KillShell", "KillBash",
    # —— 读写宿主文件系统（Read 能直接读 .env 拿到全部密钥）——
    "Read", "Write", "Edit", "MultiEdit", "NotebookEdit", "NotebookRead",
    # —— 文件系统侦察（为上面两类踩点）——
    "Glob", "Grep",
    # —— 会加载并执行 ~/.claude/skills 下的技能：正是本次事故里被误用的那个 ——
    "Skill",
    # —— 能派生子代理 / 执行斜杠命令，可能绕开上面的限制 ——
    "Task", "SlashCommand",
    # —— 抓任意 URL = SSRF：能打容器内网(实测 synapse:8008 / postgres:5432 都可达)
    #    与云元数据(RFC 6598 元数据端点 100.100.100.200 可取 RAM 临时凭据)。
    #    不是砍掉联网能力——换成自研的 fetch_url，那个走 wf.check_outbound_url 防护。
    "WebFetch",
    # —— 内置搜索绕过会员门控：不经 Toolbox.execute，免费用户可白嫖联网。
    #    换成自研 web_search（受后台可调的 gate 强制），见上方注释。
    "WebSearch",
]


def _env(key: str, default: str = "") -> str:
    """读 COSMAC_ 前缀环境变量(与项目其它模块同约定;此引擎较新,不做 GUDUU_ 回退)。"""
    return os.environ.get(f"COSMAC_{key}", default)


def sdk_engine_enabled() -> bool:
    """总开关:COSMAC_AGENT_ENGINE=claude_sdk 才启用(默认关,行为与部署零变化)。"""
    return _env("AGENT_ENGINE").strip().lower() == "claude_sdk"


def _history_text(history: Optional[List[Message]], limit: int = 12) -> str:
    """把 legacy 的对话历史转成文本前缀,拼进 prompt。

    为什么不喂结构化 history:Agent SDK 自己管理会话上下文,没有"注入外部 history"
    的入口;把最近几轮拼成文本是官方推荐的替代做法,对"记得上文"足够用。
    """
    if not history:
        return ""
    lines: List[str] = []
    for m in history[-limit:]:
        if m.role == "user" and (m.content or "").strip():
            lines.append(f"用户: {m.content.strip()}")
        elif m.role == "assistant" and (m.content or "").strip():
            lines.append(f"你(AI): {m.content.strip()}")
    if not lines:
        return ""
    return "### 本群最近对话(供参考)\n" + "\n".join(lines) + "\n\n### 用户这次说\n"


def _result_usage_tokens(message: Any) -> int:
    """从 SDK 的 ResultMessage 里取模型输出 token 数。取不到返回 0。

    ``ResultMessage.usage`` 可能是 dict 或对象。用户钱包只结算
    ``output_tokens``；input/cache token 是系统提示词、历史与工具等平台
    实现成本，不转嫁给用户。任何异常都退化为 0，不影响回复。
    """
    try:
        usage = getattr(message, "usage", None)
        if usage is None:
            return 0
        value = (
            usage.get("output_tokens", 0)
            if isinstance(usage, dict)
            else getattr(usage, "output_tokens", 0)
        )
        return max(0, int(value or 0))
    except (TypeError, ValueError, AttributeError):
        return 0


class ClaudeSdkEngine:
    """用 Claude Agent SDK 驱动的一次性问答引擎。

    与 legacy `Agent.run` 同签名,bot 里可无缝替换。每次 run 拉起一个 SDK 会话
    (CLI 子进程),跑完即弃——无跨请求状态,天然并发安全(bot 是每事件一线程)。

    ⚠️ **别再想"长连接复用同一个 client 提速"**(2026-07-26 生产实测结论,详见 TODO C 节):
    ① 固定开销实测只有约 2.6s(connect 0.7s + 首次 query 暖机 1.9s),不是早先估计的 3~8s;
    ② SDK 的 `query(session_id=...)` **根本不隔离上下文**——同一 client 上 A 会话存的内容
    B 会话读得到,复用即**跨用户泄露**;③ `system_prompt` 只能 connect 时定,而我们每轮都不同。
    提速改走**流式输出**(stream_cb):边生成边显示,体感收益远大于 2.6s 且零正确性风险。
    """

    # 上次 run 的模型输出用量（Token 经济计费用）；run 开始清零、由 ResultMessage 累加。
    last_usage_tokens: int = 0

    def __init__(
        self, toolbox: Toolbox, get_system: Callable[[], str], model_override: str = ""
    ) -> None:
        """toolbox=业务工具箱(桥接给引擎);get_system=取当前人设的回调
        (用回调而非快照:后台热更新人设后,下一次 run 自动生效,与 legacy 一致)。
        model_override=**群级模型联动**:本群绑定的智能体若指定了模型,用它替代全局
        COSMAC_SDK_MODEL——与 legacy 引擎的 _agent_for_model 同语义。传的应是 SDK 端点
        认识的模型 id;若端点不认(如填了 ark 专属 id),run 会抛错、由 bot 回退 legacy
        (legacy 在原生 provider 上仍按群模型跑,行为不劣化)。"""
        self.toolbox = toolbox
        self.get_system = get_system
        self.model_override = (model_override or "").strip()

    def _resolve_model(self) -> str:
        """本次会话用的模型:群覆盖优先,否则全局 env(默认 deepseek-chat)。独立成方法便于单测。"""
        return self.model_override or _env("SDK_MODEL", "deepseek-chat")

    # ── 对外入口(同步;bot 的线程模型里直接调) ──────────────────────────────
    def run(
        self,
        user_text: str,
        ctx: ToolContext,
        extra_system: str = "",
        history: Optional[List[Message]] = None,
        progress_cb=None,
        stream_cb=None,
    ) -> str:
        """处理一句用户输入,返回最终文本回复。失败**抛异常**——由 bot 回退 legacy。

        progress_cb(tool_name, args):每次工具调用前回调,给用户滚动展示"正在干什么"。
        stream_cb(partial_text):**流式输出**——正文每增长一点就回调一次(传的是当前这段
        文本块的**累计**内容,不是增量,调用方直接拿去覆盖显示即可)。传了才开启增量流。
        """
        import asyncio  # 局部 import:引擎未启用时本模块零依赖负担

        return asyncio.run(
            self._arun(user_text, ctx, extra_system, history, progress_cb, stream_cb)
        )

    # ── 真正干活(async;SDK 是异步接口) ────────────────────────────────────
    async def _arun(
        self,
        user_text: str,
        ctx: ToolContext,
        extra_system: str,
        history: Optional[List[Message]],
        progress_cb=None,
        stream_cb=None,
    ) -> str:
        # 懒 import:claude-agent-sdk 只在 3.10+ 且已安装时存在;3.9 环境 import 会
        # ModuleNotFoundError → 抛给 bot 回退 legacy,不影响现有功能。
        import asyncio

        from claude_agent_sdk import (  # type: ignore[import-not-found]
            AssistantMessage,
            ClaudeAgentOptions,
            ResultMessage,
            StreamEvent,
            TextBlock,
            ToolUseBlock,
            create_sdk_mcp_server,
            query,
            tool,
        )

        os.makedirs(_SDK_HOME, exist_ok=True)

        # ── 1) 把 Toolbox 已启用的工具全部桥接成 SDK 工具 ──
        # handler 闭包捕获本次请求的 ctx:执行走 Toolbox.execute,门控/配额/防呆全复用。
        # 同步的 execute 丢线程池跑(内部有 requests 网络调用,不能阻塞 SDK 的事件循环)。
        def _make_handler(tool_name: str):
            async def _handler(args):
                text = await asyncio.to_thread(
                    self.toolbox.execute,
                    ToolCall(id=f"sdk-{tool_name}", name=tool_name, arguments=dict(args or {})),
                    ctx,
                )
                return {"content": [{"type": "text", "text": text}]}

            return _handler

        sdk_tools = []
        for spec in self.toolbox.specs():
            try:
                sdk_tools.append(
                    tool(spec.name, spec.description, spec.parameters)(_make_handler(spec.name))
                )
            except Exception:
                # 单个工具 schema 不被 SDK 接受不至于整体失败:跳过并留日志
                logger.warning("工具 %s 桥接失败,已跳过", spec.name, exc_info=True)

        server = create_sdk_mcp_server(name="cosmac", version="1.0.0", tools=sdk_tools)
        allowed = [f"mcp__cosmac__{s.name}" for s in self.toolbox.specs()]

        # ── 2) 组 SDK 选项:端点/模型按 env,可从 DeepSeek 一键切 Claude ──
        base_url = _env("SDK_BASE_URL")
        api_key = _env("SDK_API_KEY")
        model = self._resolve_model()  # 群级模型联动:群绑定的模型覆盖全局 SDK_MODEL
        # 默认 16:组班这类多步骤任务(建群→邀人→派单→设RULE→发消息…)一条消息内工具调用
        # 轻松超 8 轮。太小会频繁"达上限"回退 legacy;太大则复杂任务跑更久更费 token。16 折中。
        max_turns = int(_env("SDK_MAX_TURNS", "16") or 16)

        # IS_SANDBOX=1:发行版 bot 容器以 root 跑,Claude Code CLI 出于安全拒绝
        # root + bypassPermissions(线上实测 exit 1 且 stderr 被吞,引擎静默回退 legacy)。
        # 容器即沙箱,官方 devcontainer 同款放行方式。业务安全仍靠 Toolbox 门控/配额层。
        env = {"HOME": _SDK_HOME, "IS_SANDBOX": "1"}
        if base_url:
            env["ANTHROPIC_BASE_URL"] = base_url
            # 非官方端点(如 DeepSeek)也把"快小模型"指到同一个模型,否则 CLI 内部
            # 的辅助调用(标题生成等)会去找 haiku 而 404。
            env["ANTHROPIC_MODEL"] = model
            env["ANTHROPIC_SMALL_FAST_MODEL"] = model
        if api_key:
            env["ANTHROPIC_AUTH_TOKEN"] = api_key

        system = (self.get_system() or "").strip()
        if extra_system:
            system = f"{system}\n\n{extra_system}" if system else extra_system

        options = ClaudeAgentOptions(
            model=model,
            mcp_servers={"cosmac": server},
            allowed_tools=allowed,
            # 流式输出:只有调用方要流时才开——开了 SDK 会额外推大量 StreamEvent,
            # 不用则平白多一堆进程间消息。
            include_partial_messages=bool(stream_cb),
            # 工具权限:业务安全不靠 SDK 的确认弹窗(没人在终端上点确认),而靠
            # Toolbox 内部的门控/配额/越权检查——那层对两种引擎一视同仁。
            permission_mode="bypassPermissions",
            # 安全红线：bypassPermissions 会放行**所有** CLI 内置工具（Bash/Read/Write…），
            # 而 Toolbox 的门控层管不到它们。这里显式拉黑，语义是"从模型上下文移除、
            # 即使本来允许也不可用"，故在 bypass 模式下依然生效。详见 _SDK_BLOCKED_TOOLS。
            disallowed_tools=_SDK_BLOCKED_TOOLS,
            max_turns=max_turns,
            system_prompt=system or None,
            env=env,
        )

        # ── 3) 跑一次会话,取最终文本(带整体超时) ──
        # 负责人实报:"推进 AI 执行"卡死很久没响应——某次模型/工具调用挂住,而 query 循环没有
        # 整体超时,就无限等、前端"正在执行"一直转圈。这里包一层超时:超了就抛 TimeoutError,
        # 交给 bot 的引擎兜底(_run_agent_engine:已执行过工具就返回"遇到故障停在这里",没执行过
        # 就回退 legacy),把"无限转圈"变成一条明确回复。COSMAC_SDK_TIMEOUT 可配(默认 240s、最低 30s)。
        try:
            _sdk_to = float(_env("SDK_TIMEOUT", "") or 240)
        except (TypeError, ValueError):
            _sdk_to = 240.0
        _sdk_to = max(30.0, _sdk_to)
        prompt = _history_text(history) + user_text
        final_text = ""
        # 本次会话模型输出用量：SDK 末尾 ResultMessage.usage 带 output token，
        # 这里累计；bot 在 run 后读 self.last_usage_tokens 结算用户钱包。
        self.last_usage_tokens = 0

        # 流式输出用:当前正在生成的那个文本块的累计内容。模型可能先说一段、调工具、再说
        # 最终答复——每遇到新文本块就清零,与下面"取最后一段非空文本作最终回复"口径一致。
        stream_buf = ""

        async def _consume() -> None:
            # 内部协程:跑完整个 query 流。用 asyncio.wait_for 包它(3.9 兼容,不用 3.11 的
            # asyncio.timeout),超时会取消它、连带取消底层 query 生成器。
            nonlocal final_text, stream_buf
            async for message in query(prompt=prompt, options=options):
                # ── 流式增量(开了 include_partial_messages 才有)──
                # event 是标准 Anthropic SSE 事件 dict。只取 text_delta:thinking_delta 是
                # 模型的**内部推理**,绝不能流给用户看。
                if stream_cb is not None and isinstance(message, StreamEvent):
                    try:
                        ev = message.event or {}
                        et = ev.get("type")
                        if et == "content_block_start":
                            if (ev.get("content_block") or {}).get("type") == "text":
                                stream_buf = ""
                        elif et == "content_block_delta":
                            delta = ev.get("delta") or {}
                            if delta.get("type") == "text_delta":
                                stream_buf += str(delta.get("text") or "")
                                stream_cb(stream_buf)
                    except Exception:
                        # 流式是纯体验增强:解析/回调出任何问题都吞掉,绝不影响这条回复
                        logger.debug("处理流式增量失败(忽略)", exc_info=True)
                    continue
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, ToolUseBlock) and progress_cb:
                            # 过程可见:引擎每发起一次工具调用就报给回调(工具名去掉 mcp 前缀)。
                            try:
                                name = str(block.name or "").split("__")[-1]
                                progress_cb(name, dict(block.input or {}))
                            except Exception:
                                pass
                        if isinstance(block, TextBlock) and block.text.strip():
                            final_text = block.text.strip()  # 取最后一段非空文本 = 最终回复
                elif isinstance(message, ResultMessage):
                    # 会话结束消息：只累计模型 output token 作为用户计费量。
                    self.last_usage_tokens += _result_usage_tokens(message)

        try:
            await asyncio.wait_for(_consume(), timeout=_sdk_to)
        except (asyncio.TimeoutError, TimeoutError):
            logger.warning("Claude SDK 引擎执行超时(%ss),中止本轮", _sdk_to)
            raise TimeoutError(f"Claude SDK engine timed out after {_sdk_to}s")

        return final_text or "(引擎没有产出回复,请重试)"
