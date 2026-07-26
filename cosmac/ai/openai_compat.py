"""通用 OpenAI 兼容模型后端。

DeepSeek（火山方舟）、OpenAI（ChatGPT）、Gemini（Google 的 OpenAI 兼容端点）等
都用 OpenAI 的 Chat Completions 格式，所以共用这一个实现 —— 只是 base_url /
api_key / model 不同。Claude 用 anthropic 自己的格式，单独在 claude.py。

key 由调用方（build_provider）传入；生产恒为服务端环境变量里的 key，管理后台不下发
key。本类自身不读 env、不写死任何厂商逻辑（差异只在 base_url/model）。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from cosmac.ai.base import LLMProvider, Message, ToolCall, ToolSpec, TurnResult

logger = logging.getLogger("cosmac.ai.openai_compat")


class OpenAICompatProvider(LLMProvider):
    """调用任意 OpenAI 兼容接口的后端（支持工具调用）。"""

    name = "openai_compat"

    def __init__(
        self,
        api_key: str,
        model: str,
        system_prompt: str = "",
        base_url: Optional[str] = None,
    ):
        # 延迟导入：只有真正用到时才依赖 openai 包
        from openai import OpenAI

        self.model = model
        self.system_prompt = system_prompt
        kwargs: Dict[str, Any] = {"api_key": api_key or ""}
        if base_url:
            kwargs["base_url"] = base_url  # 指向方舟 / Gemini 等；不传则用 OpenAI 官方
        # 显式超时 + 限重试(负责人实报:推进 AI 执行卡死很久没响应)。OpenAI SDK 默认超时长达
        # 600s、且默认重试 2 次——一次卡住的模型调用能拖十几分钟,表现为"正在执行"转圈不动。
        # 用 COSMAC_LLM_TIMEOUT 配置(默认 120s、最低 20s),重试压到 1 次,让卡住的调用尽快失败、
        # 走上层兜底(auto-executor 会把任务退回并提示),而不是无限等。
        from cosmac.config import _env
        try:
            _to = float(_env("LLM_TIMEOUT", "") or 120)
        except (TypeError, ValueError):
            _to = 120.0
        kwargs["timeout"] = max(20.0, _to)
        kwargs["max_retries"] = 1
        self._client = OpenAI(**kwargs)

    # —— 内部：中立结构 → OpenAI 兼容格式 ——

    def _build_messages(self, messages: List[Message]) -> List[Dict[str, Any]]:
        """把中立 Message 列表翻译成 OpenAI 的 messages 数组。

        - tool 角色 → {role: tool, tool_call_id, content}
        - assistant 带 tool_calls → {role: assistant, content, tool_calls:[function...]}
        - system 提示：历史里没有 system 消息时才用构造时的 self.system_prompt 兜底，
          避免与上层 Agent 传入的 system 消息重复。
        """
        convo: List[Dict[str, Any]] = []
        has_system = any(m.role == "system" for m in messages)
        if self.system_prompt and not has_system:
            convo.append({"role": "system", "content": self.system_prompt})

        for msg in messages:
            if msg.role == "system":
                convo.append({"role": "system", "content": msg.content})
            elif msg.role == "tool":
                convo.append(
                    {
                        "role": "tool",
                        "tool_call_id": msg.tool_call_id,
                        "content": msg.content,
                    }
                )
            elif msg.role == "assistant" and msg.tool_calls:
                convo.append(
                    {
                        "role": "assistant",
                        "content": msg.content or None,  # 有工具调用时 content 可空
                        "tool_calls": [
                            {
                                "id": c.id,
                                "type": "function",
                                "function": {
                                    "name": c.name,
                                    # OpenAI 要求 arguments 是 JSON 字符串
                                    "arguments": json.dumps(
                                        c.arguments, ensure_ascii=False
                                    ),
                                },
                            }
                            for c in msg.tool_calls
                        ],
                    }
                )
            else:
                role = "assistant" if msg.role == "assistant" else "user"
                convo.append({"role": role, "content": msg.content})
        return convo

    @staticmethod
    def _build_tools(tools: List[ToolSpec]) -> List[Dict[str, Any]]:
        """把中立 ToolSpec 翻译成 OpenAI 的 tools 定义。"""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]

    # —— 对外：纯对话 ——

    def complete(self, messages: List[Message]) -> str:
        resp = self._client.chat.completions.create(
            model=self.model,
            max_tokens=4096,
            messages=self._build_messages(messages),
        )
        return (resp.choices[0].message.content or "").strip()

    # —— 对外：带工具的一轮推理 ——

    def complete_with_tools(
        self, messages: List[Message], tools: List[ToolSpec]
    ) -> TurnResult:
        kwargs: Dict[str, Any] = dict(
            model=self.model,
            max_tokens=4096,
            messages=self._build_messages(messages),
        )
        if tools:
            kwargs["tools"] = self._build_tools(tools)

        resp = self._client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message

        tool_calls: List[ToolCall] = []
        for tc in msg.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except (ValueError, TypeError):
                args = {}  # 模型偶尔吐非法 JSON，兜底空参数
            tool_calls.append(
                ToolCall(id=tc.id, name=tc.function.name, arguments=args)
            )
        return TurnResult(text=(msg.content or "").strip(), tool_calls=tool_calls)
