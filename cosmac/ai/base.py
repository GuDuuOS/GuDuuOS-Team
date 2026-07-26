"""LLM 统一接口定义（含工具调用抽象）。

所有 AI 模型后端（Claude / OpenAI / 本地模型 / 占位 echo）都实现同一个
``LLMProvider`` 接口。这样上层"主 AI"逻辑只面向接口编程，
换模型只是换一个实现类，业务代码一行都不用改。

本文件还定义了"工具调用"的**厂商中立**数据结构（ToolSpec / ToolCall /
TurnResult）。各厂商（Anthropic、OpenAI…）的工具调用协议格式各不相同，
但这些差异**只允许**出现在各自的 provider 实现里（如 ai/claude.py），
绝不能泄漏到上层 Agent / Bot 业务逻辑——上层只认这里的中立结构。
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class ToolCall:
    """模型决定要调用的一次工具调用（厂商中立）。

    id:        本次调用的唯一标识（把"调用"和"结果"对应起来用；不同厂商叫法
               不同，统一抽象成 id）。
    name:      要调用的工具名（与 ToolSpec.name 对应）。
    arguments: 模型给出的参数，已解析成 Python dict。
    """

    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class Message:
    """一条对话消息（可承载工具调用与工具结果）。

    role:    角色，取值 "system" / "user" / "assistant" / "tool"。
    content: 文本内容（assistant 调工具时可能为空；tool 角色放工具返回的文本）。
    tool_calls:   仅 assistant 用——这一轮模型发起的工具调用列表。
    tool_call_id: 仅 tool 用——本条结果回应的是哪一次工具调用（对应 ToolCall.id）。

    说明：把工具调用/结果也存进中立的 Message 历史里，是为了让每个 provider
    在每一轮都能从中立历史**重建**自己厂商所需的格式，从而保持 provider 之间
    互不耦合。
    """

    role: str
    content: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    tool_call_id: str = ""


@dataclass
class ToolSpec:
    """一个工具的"说明书"，交给模型让它知道有这个工具可用（厂商中立）。

    name:        工具名（如 "create_room"）。
    description: 工具是干嘛的（写清楚，模型据此判断什么时候该调用它）。
    parameters:  参数的 JSON Schema（object 类型，描述每个入参）。
    """

    name: str
    description: str
    parameters: Dict[str, Any]


@dataclass
class TurnResult:
    """模型"一轮"输出的结果（厂商中立）。

    要么是给用户的最终文本回复，要么是一批待执行的工具调用——二选一：
      - tool_calls 非空：模型想先调用工具，Agent 执行后把结果回灌再问下一轮。
      - tool_calls 为空：text 即最终回复，对话结束。
    text 在有 tool_calls 时也可能带着模型的"思考旁白"，可忽略或记录。
    usage_tokens: 本轮真实消耗的 LLM token 数（prompt+completion，后端能取到就填；
                  取不到=0）。Token 经济按它计费（见 cosmac/wallet.py），"真实计算使用量"
                  的数据来源之一（另一条是 SDK 引擎的 ResultMessage.usage）。
    """

    text: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    usage_tokens: int = 0


class LLMProvider(abc.ABC):
    """大模型后端的抽象基类。

    具体实现（如 ClaudeProvider）至少要实现 ``complete``（纯对话）；
    若该后端支持工具调用，再覆盖 ``complete_with_tools``。
    """

    #: 后端名字（用于日志/配置识别），子类覆盖。
    name: str = "base"

    @abc.abstractmethod
    def complete(self, messages: List[Message]) -> str:
        """根据对话历史生成一条回复文本。

        参数:
            messages: 按时间顺序排列的对话消息列表。
        返回:
            模型生成的回复（纯文本）。
        """
        raise NotImplementedError

    def complete_with_tools(
        self, messages: List[Message], tools: List[ToolSpec]
    ) -> TurnResult:
        """带工具的一轮推理：模型可返回文本，或请求调用工具。

        默认实现**不支持**工具（直接退回 ``complete`` 的纯文本），这样还没实现
        工具调用的后端（echo / openai）也能正常工作、绝不报错。支持工具的后端
        （如 Claude）覆盖本方法即可。
        """
        return TurnResult(text=self.complete(messages))
