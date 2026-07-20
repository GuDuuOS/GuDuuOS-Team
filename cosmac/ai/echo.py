"""占位用的"回显"模型后端。

它不真正调用任何大模型，只是把用户最后一句话原样回显。
作用：在还没接入真实 LLM 时，先打通"收到消息 → 生成回复 → 发回群"的完整链路。
等链路验证通过，把它换成真正的 Claude/OpenAI 实现即可（接口不变）。
"""

from __future__ import annotations

from typing import List

from cosmac.ai.base import LLMProvider, Message


class EchoProvider(LLMProvider):
    """回显后端：返回一句包含用户原话的固定格式回复。"""

    name = "echo"

    def complete(self, messages: List[Message]) -> str:
        # 找到最后一条 "user" 消息（即用户刚发的那句）
        last_user_text = ""
        for msg in reversed(messages):
            if msg.role == "user":
                last_user_text = msg.content
                break

        # 还没接真模型，先用固定话术证明"我看到你说的话了，也能回话"
        return f"🤖 CosMac AI（占位）收到你说的：「{last_user_text}」"
