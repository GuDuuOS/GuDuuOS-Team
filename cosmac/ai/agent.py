"""主 AI Agent —— 工具调用循环（"会动手的大脑"）。

把"可配置的大模型后端"和"操作 IM 的工具箱"接在一起，跑一个标准的
ReAct 式循环：

    用户说一句话
      → 模型看到所有工具，决定：直接回答 / 先调用工具
      → 若调用工具：执行（真的建群/发消息/查记录），把结果回灌给模型
      → 模型据结果继续，直到给出最终文本答复
      → 把最终答复发回群

为防止模型反复调工具陷入死循环，限制最多 ``max_steps`` 轮。
"""

from __future__ import annotations

import logging
from typing import List, Optional

from cosmac.ai.base import LLMProvider, Message
from cosmac.ai.tools import Toolbox, ToolContext

logger = logging.getLogger("cosmac.ai.agent")


class Agent:
    """主 AI 的"思考-行动"循环。"""

    def __init__(
        self,
        llm: LLMProvider,
        toolbox: Toolbox,
        system_prompt: str = "",
        max_steps: int = 5,
    ):
        self.llm = llm
        self.toolbox = toolbox
        self.system_prompt = system_prompt
        self.max_steps = max_steps

    def run(
        self,
        user_text: str,
        ctx: ToolContext,
        extra_system: str = "",
        history: Optional[List[Message]] = None,
        progress_cb=None,
    ) -> str:
        """处理一句用户输入，返回要发回群里的最终文本回复。

        参数:
            user_text:    用户说的话（已去掉 @ 前缀）。
            ctx:          工具执行上下文（当前房间 / 发起人）。
            extra_system: 临时追加到系统提示里的内容（如本群/本人当前生效的技能说明）。
                          按 (房间, 发起人) 每条消息动态算出来，不污染 Agent 的常驻人设。
            history:      最近的对话历史（不含当前这句），给主 AI「短期记忆」。
                          由 bot 从 Matrix 读最近消息映射而来（聊天记录存在 Synapse，不重存）。
        """
        # 初始历史：系统提示 + 最近对话 + 用户这句话
        # 把常驻人设和本轮技能 addendum **合并成单条 system 消息**——有的 provider
        # （如 Claude）只认一个 system，分两条会被丢掉，合并最稳。
        messages: List[Message] = []
        sys_text = self.system_prompt
        if extra_system:
            sys_text = f"{sys_text}\n\n{extra_system}" if sys_text else extra_system
        if sys_text:
            messages.append(Message(role="system", content=sys_text))
        if history:
            messages.extend(history)
        messages.append(Message(role="user", content=user_text))

        tools = self.toolbox.specs()

        for step in range(self.max_steps):
            turn = self.llm.complete_with_tools(messages, tools)

            # 没有工具调用 → 这就是最终回复
            if not turn.tool_calls:
                return turn.text or "（我这边没有可回复的内容。）"

            # 有工具调用：先把"助手这一轮发起了哪些调用"记进历史
            messages.append(
                Message(
                    role="assistant",
                    content=turn.text,
                    tool_calls=turn.tool_calls,
                )
            )
            # 逐个执行工具，把结果作为 tool 消息回灌
            for call in turn.tool_calls:
                # 过程可见:执行前把"正在调用什么"报给回调(bot 用它滚动更新状态消息)。
                # 回调任何异常都不影响执行——它只是给用户看的过场。
                if progress_cb:
                    try:
                        progress_cb(call.name, call.arguments or {})
                    except Exception:
                        pass
                result = self.toolbox.execute(call, ctx)
                logger.info("工具 %s 结果: %s", call.name, result)
                messages.append(
                    Message(role="tool", content=result, tool_call_id=call.id)
                )
            # 进入下一轮，让模型根据工具结果继续

        # 兜底：步数用尽仍没收敛
        logger.warning("Agent 达到最大步数 %d 仍未结束", self.max_steps)
        return "我尝试了多步操作但没能完成，请换种说法或稍后再试。"
