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
import threading
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
        # 5→8(负责人实报连带):推理型模型(deepseek-v4-pro)习惯"做完再验证"——建专班后
        # 还要 list 检查一轮,5 步常在收尾前耗尽 → 明明全做成了却回兜底话术吓用户。
        max_steps: int = 8,
    ):
        self.llm = llm
        self.toolbox = toolbox
        self.system_prompt = system_prompt
        self.max_steps = max_steps
        # 用量计数的**线程本地**存储（2026-07-31 修计费竞态）：同一 model 的 Agent 实例会被
        # 不同房间的并发线程共享（见 bot._agent_for_model 缓存），若把用量记在普通实例属性上，
        # 两个并发 run 会互相清零/累加对方的数 → Token 经济计费串号（偏多或偏少）。
        # bot 是在跑完 run() 的**同一线程**里读 last_usage_tokens 结算的，thread-local 让
        # 每个线程各记各的账，天然隔离，调用方无需任何改动。
        self._usage_local = threading.local()

    @property
    def last_usage_tokens(self) -> int:
        """本线程上次 run 累计的模型输出用量（Token 经济计费用）；线程隔离，见 __init__。"""
        return int(getattr(self._usage_local, "value", 0))

    @last_usage_tokens.setter
    def last_usage_tokens(self, v: int) -> None:
        self._usage_local.value = int(v)

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

        # 本次 run 累计的模型输出用量（Token 经济按它计费）；每轮 complete 累加，
        # bot 在 run 结束后读 self.last_usage_tokens 结算（见 _run_agent_engine）。
        self.last_usage_tokens = 0

        for step in range(self.max_steps):
            turn = self.llm.complete_with_tools(messages, tools)
            self.last_usage_tokens += int(getattr(turn, "usage_tokens", 0) or 0)

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
                # 终止性工具(如 ask_user_choice 发选择卡):执行后**立即结束本轮**,
                # 交还控制权给用户,绝不继续调后续工具/进入下一轮(负责人实报:AI 发了
                # 「同名专班怎么处理」选项卡却没等点选,又建了第二个同名专班)。
                # 已通过卡片与用户交互,返回模型调工具前说的引导语(可能空,bot 判空不发)。
                if self.toolbox.is_terminal(call.name):
                    logger.info("遇终止性工具 %s,结束本轮等用户输入", call.name)
                    return turn.text or ""
            # 进入下一轮，让模型根据工具结果继续

        # 兜底：步数用尽仍没收敛。⚠️ 不能全盘否定——此刻工具大多**已真实执行**(建房/派单
        # 都生效了),旧文案"没能完成"让用户以为全失败(负责人实报:专班明明建好了却被吓到)。
        # 让模型基于已有工具结果**只做总结、禁止再调工具**,把真实进展告诉用户。
        logger.warning("Agent 达到最大步数 %d 仍未结束,转总结收尾", self.max_steps)
        try:
            messages.append(Message(
                role="user",
                content="(系统:操作轮数已达上限,请立即停止调用工具,"
                        "根据上面各工具的真实执行结果,简明总结哪些已完成、哪些没做完)",
            ))
            turn = self.llm.complete_with_tools(messages, [])  # 不给工具,只许说话
            self.last_usage_tokens += int(getattr(turn, "usage_tokens", 0) or 0)
            if turn.text:
                return turn.text
        except Exception:
            logger.debug("超步总结失败,退回固定文案", exc_info=True)
        return "操作做了一部分(部分步骤可能已生效,请刷新查看),但没能全部收尾——请把没完成的部分再吩咐我一次。"
