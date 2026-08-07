"""GuDuu OS AI 层 —— 主 AI 的大脑 + 多模型抽象。

统一的 LLM 接口在 base.py；具体后端按配置选：
  - echo            ：占位回显，用于打通骨架（无需任何 key）
  - claude          ：Anthropic Claude（key: ANTHROPIC_API_KEY）
  - openai          ：OpenAI ChatGPT（key: OPENAI_API_KEY）
  - deepseek / ark  ：火山引擎方舟（OpenAI 兼容，接 DeepSeek 等，key: ARK_API_KEY）
  - gemini          ：Google Gemini（OpenAI 兼容端点，key: GEMINI_API_KEY）

业务代码只依赖统一接口，绝不直接调用某家厂商 SDK，方便随时切换模型后端。
API key 来自节点加密设置或服务端环境变量，绝不写入 Matrix state event；取不到 key、
或缺对应 SDK时优雅降级到 echo。业务层仍只通过 ``build_provider`` 传递已经在服务端
解密的值，浏览器接口不会读回密钥原文。
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Optional

from cosmac.ai.base import (
    LLMProvider,
    Message,
    ToolCall,
    ToolSpec,
    TurnResult,
)
from cosmac.ai.echo import EchoProvider

if TYPE_CHECKING:
    from cosmac.config import CosmacConfig

logger = logging.getLogger("cosmac.ai")

# 各 provider 的 OpenAI 兼容 base_url（claude 不在此列，走 anthropic 自己的 SDK）
ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

# 各 provider 没指定模型时的默认值（以各家实际可用 id 为准，可被配置覆盖）
DEFAULT_MODELS = {
    "claude": "claude-opus-4-8",
    "openai": "gpt-4o",
    "deepseek": "deepseek-v3.2",
    "ark": "deepseek-v3.2",
    "gemini": "gemini-2.0-flash",
}

# 各 provider 从哪个环境变量兜底取 key（当运行时配置没给 key 时）
ENV_KEYS = {
    "claude": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "deepseek": "ARK_API_KEY",
    "ark": "ARK_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


def build_provider(
    provider: str,
    api_key: str = "",
    model: str = "",
    system_prompt: str = "",
    base_url: str = "",
    allow_env_fallback: bool = True,
) -> LLMProvider:
    """按「provider 名 + 显式 key + 模型」构造后端（多模型抽象的总入口）。

    api_key 为空时，从该 provider 对应的环境变量兜底取（启动配置那条路径）。
    任一情况下取不到 key、或缺 SDK、或 provider 未知降级处理：
      - 缺 key / 缺 SDK → 返回 EchoProvider（保证 bot 不会因此起不来/不回话）。
      - 未知 provider → 抛 ValueError（明显配置错误，早暴露）。
    """
    name = (provider or "echo").lower()
    if name == "echo":
        return EchoProvider()
    if name not in ENV_KEYS:
        raise ValueError(
            f"未知的 LLM provider: {name!r}"
            "（可选 echo/claude/openai/deepseek/ark/gemini）"
        )

    # key：优先运行时下发，其次环境变量
    key = api_key or (
        os.environ.get(ENV_KEYS[name], "") if allow_env_fallback else ""
    )
    if not key:
        logger.warning("provider=%s 缺少 API key，主 AI 暂时降级为 echo 占位。", name)
        return EchoProvider()

    use_model = model or DEFAULT_MODELS[name]

    try:
        if name == "claude":
            from cosmac.ai.claude import ClaudeProvider

            return ClaudeProvider(
                model=use_model, system_prompt=system_prompt, api_key=key,
                base_url=base_url,
            )
        # 其余都是 OpenAI 兼容：只是 base_url 不同
        from cosmac.ai.openai_compat import OpenAICompatProvider
    except ImportError:
        logger.warning("provider=%s 所需 SDK 未安装，主 AI 暂时降级为 echo 占位。", name)
        return EchoProvider()

    resolved_base_url: Optional[str] = base_url or None
    if not resolved_base_url and name in ("deepseek", "ark"):
        resolved_base_url = (
            os.environ.get("ARK_BASE_URL", ARK_BASE_URL)
            if allow_env_fallback else ARK_BASE_URL
        )
    elif not resolved_base_url and name == "gemini":
        resolved_base_url = GEMINI_BASE_URL
    # openai：base_url=None → 用 OpenAI 官方端点
    return OpenAICompatProvider(
        api_key=key, model=use_model, system_prompt=system_prompt, base_url=resolved_base_url
    )


def get_provider(config: "CosmacConfig") -> LLMProvider:
    """按启动配置（环境变量）构造后端。key 走环境变量，故这里 api_key 传空。"""
    return build_provider(
        config.llm_provider,
        api_key="",
        model=config.llm_model,
        system_prompt=config.system_prompt,
    )


__all__ = [
    "LLMProvider",
    "Message",
    "ToolCall",
    "ToolSpec",
    "TurnResult",
    "EchoProvider",
    "get_provider",
    "build_provider",
]
