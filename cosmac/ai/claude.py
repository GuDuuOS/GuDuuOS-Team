"""Claude (Anthropic) 模型后端。

用官方 anthropic SDK 调用 Claude。API key 不写在代码里 ——
SDK 自动从环境变量 ANTHROPIC_API_KEY 读取（部署到服务器时配进去即可）。

默认用最强的 claude-opus-4-8，并开启 adaptive thinking（让模型自己决定思考深度），
系统提示用 prompt caching 缓存，降低重复请求的成本与延迟。

本文件是"工具调用"厂商差异的**唯一**落点：把中立的 ToolSpec/ToolCall/Message
翻译成 anthropic 的 tool_use / tool_result 格式，再把 anthropic 的响应翻译回中立
结构。上层 Agent 看不到任何 anthropic 专有字段。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from cosmac.ai.base import (
    LLMProvider,
    Message,
    ToolCall,
    ToolSpec,
    TurnResult,
)

logger = logging.getLogger("cosmac.ai.claude")

# 默认模型：Claude Opus 4.8（最强；如需更便宜可在配置里换成 claude-sonnet-4-6）
DEFAULT_CLAUDE_MODEL = "claude-opus-4-8"


def _usage_output_tokens(response: Any) -> int:
    """从 Anthropic 响应中提取用户应结算的模型输出 token。

    参数:
        response: Anthropic SDK 返回的响应对象，期望带 ``usage``。
    返回:
        非负的 ``output_tokens``；字段缺失或格式异常时返回 0。

    故意不累加 ``input_tokens``，因为其中含有平台提示词、历史与
    工具定义；这些实现成本不能因上下文长度而清空用户钱包。
    """
    try:
        usage = getattr(response, "usage", None)
        if usage is None:
            return 0
        return max(0, int(getattr(usage, "output_tokens", 0) or 0))
    except (TypeError, ValueError, AttributeError):
        return 0


class ClaudeProvider(LLMProvider):
    """调用 Anthropic Claude 的后端实现（支持工具调用）。"""

    name = "claude"

    def __init__(
        self, model: str = "", system_prompt: str = "", api_key: str = "",
        base_url: str = "",
    ):
        # 延迟导入：只有真正用 Claude 时才依赖 anthropic 包
        from anthropic import Anthropic

        self.model = model or DEFAULT_CLAUDE_MODEL
        self.system_prompt = system_prompt
        # api_key 显式传入时用它（仅测试/特殊场景；管理后台不下发 key）；留空则
        # Anthropic() 从环境变量 ANTHROPIC_API_KEY 取（生产/启动配置那条路径）。
        kwargs: Dict[str, Any] = {}
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        self._client = Anthropic(**kwargs)

    # —— 内部：把中立结构翻译成 anthropic 所需的格式 ——

    def _build_system(self, messages: List[Message]) -> Any:
        """收集 system 提示（构造参数里的 + 历史里 role==system 的），做成可缓存块。"""
        chunks: List[str] = []
        if self.system_prompt:
            chunks.append(self.system_prompt)
        for msg in messages:
            if msg.role == "system" and msg.content:
                chunks.append(msg.content)
        if not chunks:
            return None
        # system 内容稳定，做成 ephemeral 缓存块，命中缓存省钱省时
        return [
            {
                "type": "text",
                "text": "\n\n".join(chunks),
                "cache_control": {"type": "ephemeral"},
            }
        ]

    def _build_messages(self, messages: List[Message]) -> List[Dict[str, Any]]:
        """把中立 Message 列表翻译成 anthropic 的 messages 数组。

        关键转换：
          - assistant 若带 tool_calls → content 里拼出 text 块 + 每个 tool_use 块。
          - tool 角色（工具执行结果）→ anthropic 里必须作为一条 user 消息，
            content 为 tool_result 块（用 tool_use_id 对回是哪次调用）。
          - 其余 user/assistant 纯文本照常。
        """
        convo: List[Dict[str, Any]] = []
        for msg in messages:
            if msg.role == "system":
                continue  # system 单独处理，不进 messages

            if msg.role == "tool":
                # 工具结果：anthropic 用 user 角色承载 tool_result
                convo.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": msg.tool_call_id,
                                "content": msg.content,
                            }
                        ],
                    }
                )
                continue

            if msg.role == "assistant" and msg.tool_calls:
                # 助手发起工具调用：text（可选）+ 每个 tool_use 块
                content: List[Dict[str, Any]] = []
                if msg.content:
                    content.append({"type": "text", "text": msg.content})
                for call in msg.tool_calls:
                    content.append(
                        {
                            "type": "tool_use",
                            "id": call.id,
                            "name": call.name,
                            "input": call.arguments,
                        }
                    )
                convo.append({"role": "assistant", "content": content})
                continue

            # 普通文本消息（user / assistant）
            role = "assistant" if msg.role == "assistant" else "user"
            convo.append({"role": role, "content": msg.content})
        return convo

    @staticmethod
    def _build_tools(tools: List[ToolSpec]) -> List[Dict[str, Any]]:
        """把中立 ToolSpec 翻译成 anthropic 的 tools 定义。"""
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.parameters,
            }
            for t in tools
        ]

    # —— 对外：纯对话 ——

    def complete(self, messages: List[Message]) -> str:
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=4096,
            thinking={"type": "adaptive"},  # 让模型自适应决定要不要思考
            system=self._build_system(messages),
            messages=self._build_messages(messages),
        )
        # 响应是内容块列表，只取文本块拼起来（thinking 块默认无文本，忽略）
        parts = [block.text for block in resp.content if block.type == "text"]
        return "".join(parts).strip()

    # —— 对外：带工具的一轮推理 ——

    def complete_with_tools(
        self, messages: List[Message], tools: List[ToolSpec]
    ) -> TurnResult:
        """一轮推理：模型要么给最终文本，要么请求调用一批工具。"""
        kwargs: Dict[str, Any] = dict(
            model=self.model,
            max_tokens=4096,
            thinking={"type": "adaptive"},
            system=self._build_system(messages),
            messages=self._build_messages(messages),
        )
        if tools:
            kwargs["tools"] = self._build_tools(tools)

        resp = self._client.messages.create(**kwargs)

        # 拆分响应：文本块拼成旁白文本；tool_use 块转成中立 ToolCall
        text_parts: List[str] = []
        tool_calls: List[ToolCall] = []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        # anthropic 已把入参解析成 dict，直接用
                        arguments=dict(block.input or {}),
                    )
                )
        # 用户计费量：只取模型输出 output_tokens。input_tokens 中包含平台
        # 注入的 system/history/tools，不应因为平台上下文变大就清空用户钱包。
        return TurnResult(
            text="".join(text_parts).strip(),
            tool_calls=tool_calls,
            usage_tokens=_usage_output_tokens(resp),
        )
