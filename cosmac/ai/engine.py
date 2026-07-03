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
from typing import Callable, List, Optional

from cosmac.ai.base import Message, ToolCall
from cosmac.ai.tools import Toolbox, ToolContext

logger = logging.getLogger(__name__)

# 引擎的隔离 HOME:CLI 子进程会读写 $HOME/.claude(状态/凭据)。指到固定的独立目录,
# 避免和机器上已有的 Claude 登录凭据串味(实测:不隔离时 CLI 会优先用本机 OAuth 凭据,
# 打到 DeepSeek 端点直接 401)。目录内容可随时删,无状态依赖。
_SDK_HOME = "/tmp/cosmac-sdk-home"


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


class ClaudeSdkEngine:
    """用 Claude Agent SDK 驱动的一次性问答引擎。

    与 legacy `Agent.run` 同签名,bot 里可无缝替换。每次 run 拉起一个 SDK 会话
    (CLI 子进程),跑完即弃——无跨请求状态,天然并发安全(bot 是每事件一线程)。
    体验代价:子进程冷启动约 3~8 秒,比 legacy 直连 HTTP 慢;换来的是完整的
    Claude Code harness(多轮工具循环/自动重试/上下文管理)。
    """

    def __init__(self, toolbox: Toolbox, get_system: Callable[[], str]) -> None:
        """toolbox=业务工具箱(桥接给引擎);get_system=取当前人设的回调
        (用回调而非快照:后台热更新人设后,下一次 run 自动生效,与 legacy 一致)。"""
        self.toolbox = toolbox
        self.get_system = get_system

    # ── 对外入口(同步;bot 的线程模型里直接调) ──────────────────────────────
    def run(
        self,
        user_text: str,
        ctx: ToolContext,
        extra_system: str = "",
        history: Optional[List[Message]] = None,
    ) -> str:
        """处理一句用户输入,返回最终文本回复。失败**抛异常**——由 bot 回退 legacy。"""
        import asyncio  # 局部 import:引擎未启用时本模块零依赖负担

        return asyncio.run(self._arun(user_text, ctx, extra_system, history))

    # ── 真正干活(async;SDK 是异步接口) ────────────────────────────────────
    async def _arun(
        self,
        user_text: str,
        ctx: ToolContext,
        extra_system: str,
        history: Optional[List[Message]],
    ) -> str:
        # 懒 import:claude-agent-sdk 只在 3.10+ 且已安装时存在;3.9 环境 import 会
        # ModuleNotFoundError → 抛给 bot 回退 legacy,不影响现有功能。
        import asyncio

        from claude_agent_sdk import (  # type: ignore[import-not-found]
            AssistantMessage,
            ClaudeAgentOptions,
            TextBlock,
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
        model = _env("SDK_MODEL", "deepseek-chat")
        max_turns = int(_env("SDK_MAX_TURNS", "8") or 8)

        env = {"HOME": _SDK_HOME}
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
            # 工具权限:业务安全不靠 SDK 的确认弹窗(没人在终端上点确认),而靠
            # Toolbox 内部的门控/配额/越权检查——那层对两种引擎一视同仁。
            permission_mode="bypassPermissions",
            max_turns=max_turns,
            system_prompt=system or None,
            env=env,
        )

        # ── 3) 跑一次会话,取最终文本 ──
        prompt = _history_text(history) + user_text
        final_text = ""
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock) and block.text.strip():
                        final_text = block.text.strip()  # 取最后一段非空文本 = 最终回复

        return final_text or "(引擎没有产出回复,请重试)"
