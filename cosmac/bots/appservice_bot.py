"""GuDuu OS 主 AI —— Application Service Bot（最小骨架）。

职责（第一步，主 AI 控制层的地基）：
  1. 启动一个 HTTP 服务，接收 Synapse 推送过来的事件（这是主 AI 的"眼睛"）。
  2. 看到群里每一条文本消息。
  3. 被邀请进群时自动加入。
  4. 对收到的消息，调用 AI 模型生成回复，并发回群（这是主 AI 的"嘴"）。

后续会在这个地基上扩展：让 AI 真正"理解"消息、调用创建群/查记录等 IM 能力、
接入群级记忆与知识库等。

技术说明：用 Python 标准库 http.server 起服务（开发够用、无额外依赖）；
对 Synapse 的反向调用走 cosmac.bots.matrix_client。
"""

from __future__ import annotations

import hmac
import hashlib
import json
import logging
import os
import re
import socket
import threading
import time
from collections import OrderedDict
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Set, Tuple

from cosmac.ai import build_provider, get_provider
from cosmac.ai.agent import Agent
from cosmac.ai.base import LLMProvider, Message
from cosmac.ai.tools import Toolbox, ToolContext
from cosmac.bots.matrix_client import MatrixClient
from cosmac import nexus_link  # 模块6：实例→母舰心跳（未配置时全静默）
from cosmac.config import (
    AGENTS_EVENT_TYPE,
    AI_CONFIG_EVENT_TYPE,
    CHANNEL_CONFIG_EVENT_TYPE,
    CONTROL_ADMINS_EVENT_TYPE,
    GATING_EVENT_TYPE,
    MEMBER_EVENT_TYPE,
    ONBOARDING_TEMPLATES_EVENT_TYPE,
    PEOPLE_EVENT_TYPE,
    QUOTAS_EVENT_TYPE,
    RULES_EVENT_TYPE,
    SKILLS_EVENT_TYPE,
    WORKFLOWS_EVENT_TYPE,
    CosmacConfig,
)
from cosmac.members import (
    GATE_ADMIN,
    MEMBER_TIERS,
    TIER_CREATOR,
    TIER_FREE,
    GatingStore,
    MembersStore,
    gate_capability_label,
    gate_rank,
    is_valid_tier,
    tier_label,
    tier_level,
)
from cosmac.skills_text import render_skills  # 纯渲染、不依赖 DB

logger = logging.getLogger("cosmac.appservice_bot")

# 「AI 执行过程可见」:工具名 → 用户能看懂的中文动作(Claude Code 式交互,负责人点名要的)。
_TOOL_ACTION_LABELS: Dict[str, str] = {
    "create_room": "创建频道",
    "invite_to_room": "发出邀请",
    "send_message_to_room": "发送消息",
    "list_room_members": "查看成员",
    "get_recent_messages": "调取聊天记录",
    "run_workflow": "运行工作流",
    "create_tasks": "登记任务",
    "search_knowledge": "检索知识库",
    "web_search": "联网搜索",
    "list_capabilities": "查阅能力名册",
    "assemble_team": "组建专班",
    "list_room_tasks": "查看任务进度",
    "update_task": "更新任务",
    "ask_user_choice": "征询选择",
    "archive_project": "归档项目",
    "list_my_rooms": "查看频道清单",
    "query_hr": "查询人事数据",
    "query_sales": "查询销售业绩",
}
# 从工具参数里挑一个最有信息量的值,拼进动作描述(如 组建专班「暑期招生」)
_TOOL_ARG_HINT_KEYS = ("project", "name", "room_name", "user_id", "query", "goal", "slug")

# query_hr / query_sales 的 action → 中文子标签：让重复调用可区分、显得有条理
# （把主 AI 的多步查询秀成"人数编制→薪酬统计→绩效分布"这样的分析过程）。
_HR_ACTION_LABELS: Dict[str, str] = {
    "summary": "整体概况", "roster": "花名册", "headcount": "人数编制",
    "salary": "薪酬统计", "performance": "绩效分布", "ranking": "排行榜",
    "attendance": "考勤请假", "trend": "入离职趋势", "find": "查个人档案",
}
_SALES_ACTION_LABELS: Dict[str, str] = {
    "summary": "整体概况", "ranking": "业绩排行", "trend": "销售趋势",
    "person": "个人业绩",
}


class _ProgressReporter:
    """AI 执行过程的滚动状态消息:第一次工具调用时发一条,之后**原地编辑**追加步骤。

    像 Claude Code 那样让用户看到"在调取什么、在干什么",而不是几十秒的沉默后
    突然蹦出结果。一条消息反复编辑,绝不刷屏;纯聊天(没调工具)不发任何过程消息。
    进度展示是"过场",任何失败都静默忽略,绝不影响主回复。
    """

    def __init__(self, client, room_id: str) -> None:
        self.client = client
        self.room_id = room_id
        self.event_id: Optional[str] = None
        self.steps: List[str] = []

    def __call__(self, tool_name: str, args: Dict[str, Any]) -> None:
        label = _TOOL_ACTION_LABELS.get(tool_name, tool_name)
        hint = ""
        # 数据查询类工具：用 action 的中文子标签 + 部门作提示，重复调用也一目了然
        if tool_name in ("query_hr", "query_sales"):
            act = str((args or {}).get("action") or "").strip().lower()
            sub_map = _HR_ACTION_LABELS if tool_name == "query_hr" else _SALES_ACTION_LABELS
            sub = sub_map.get(act)
            dep = str((args or {}).get("department") or "").strip()
            if sub:
                hint = "·" + sub
            if dep:
                hint += f"「{dep}」"
        else:
            for k in _TOOL_ARG_HINT_KEYS:
                v = str((args or {}).get(k) or "").strip()
                if v:
                    hint = f"「{v[:24]}」"
                    break
        self.steps.append(label + hint)
        # 已完成的步骤打勾,当前步骤沙漏
        lines = [
            ("  ✅ " if i < len(self.steps) - 1 else "  ⏳ ") + s
            for i, s in enumerate(self.steps)
        ]
        text = "🤖 正在执行:\n" + "\n".join(lines)
        try:
            if self.event_id is None:
                self.event_id = self.client.send_text(self.room_id, text)
            else:
                self.client.edit_text(self.room_id, self.event_id, text)
        except Exception:
            logger.debug("更新执行进度失败(忽略)", exc_info=True)

    def finish(self) -> None:
        """回复发出后,把状态消息定格成全部完成的过程小结。"""
        if not self.event_id or not self.steps:
            return
        text = f"🤖 执行过程({len(self.steps)} 步):\n" + "\n".join(
            f"  ✅ {s}" for s in self.steps
        )
        try:
            self.client.edit_text(self.room_id, self.event_id, text)
        except Exception:
            logger.debug("定格执行进度失败(忽略)", exc_info=True)


class _StreamWriter:
    """流式回复:AI 边生成,这里边把「草稿」消息原地编辑出来,而不是憋到最后一次性发。

    为什么做它(2026-07-26):实测「长连接复用」只能省约 2.6 秒、且 SDK 的 session 不隔离
    有跨用户泄露风险(见 engine.py 类注释),所以提速改走这条——**体感**收益远大于 2.6 秒
    (用户 1 秒内就看到字在动),且完全不碰规则注入/会话隔离,零正确性风险。

    工作方式:
      - 第一次收到正文 → 发一条草稿消息(记 event_id);之后**节流**编辑同一条。
      - :meth:`finalize` 把草稿定格成最终回复,并返回 True 表示「这条消息我已经发过了」,
        调用方据此**跳过**原来的发送,避免同一段话在群里出现两次。
      - 傀儡身份(AI 同事)回复时,草稿也以它的身份发/改(edit_text_as)。
      - **全程 best-effort**:任何一步失败都把自己置为不可用(owns=False),让调用方回落到
        原来的"一次性发送"路径——流式坏了顶多退回旧体验,绝不能丢回复。

    节流参数的取舍:每次编辑都是一条真实 Matrix 事件,会永久留在房间时间线里。太密会刷爆
    事件量、也可能触发限频;太疏又没有"在动"的感觉。取 1.2 秒/24 字,并限制单条回复最多
    编辑 24 次(超过就只等最终定格),兼顾观感与事件量。
    """

    _MIN_INTERVAL = 1.2      # 两次编辑最小间隔（秒）
    _MIN_CHARS = 24          # 距上次至少新增这么多字才值得编辑一次
    _MAX_EDITS = 24          # 单条回复最多编辑次数（防长文把房间刷成编辑流水）

    def __init__(self, client, room_id: str, as_user: str = "") -> None:
        self.client = client
        self.room_id = room_id
        self.as_user = as_user or ""
        self.event_id: Optional[str] = None
        self._last_ts = 0.0
        self._last_text = ""     # 草稿当前显示的内容（定格时据此免掉重复编辑）
        self._edits = 0
        self._broken = False     # 出过错就彻底停用,不再打扰

    def _send(self, text: str) -> Optional[str]:
        if self.as_user:
            return self.client.send_text_as(self.room_id, text, self.as_user)
        return self.client.send_text(self.room_id, text)

    def _edit(self, text: str) -> bool:
        if self.as_user:
            return self.client.edit_text_as(self.room_id, self.event_id, text, self.as_user)
        return self.client.edit_text(self.room_id, self.event_id, text)

    def __call__(self, partial: str) -> None:
        """引擎每吐一点正文就调一次(partial=当前文本块的累计内容)。节流后原地更新草稿。"""
        if self._broken:
            return
        text = (partial or "").strip()
        if not text:
            return
        now = time.monotonic()
        if self.event_id is not None:
            # 已有草稿:同时满足"间隔够久"和"新增够多"才编辑；编辑次数用完就只等定格
            if self._edits >= self._MAX_EDITS:
                return
            if (now - self._last_ts) < self._MIN_INTERVAL:
                return
            if (len(text) - len(self._last_text)) < self._MIN_CHARS:
                return
        try:
            if self.event_id is None:
                ev = self._send(text)
                if not ev:
                    self._broken = True
                    return
                self.event_id = ev
            else:
                if not self._edit(text):
                    self._broken = True
                    return
                self._edits += 1
        except Exception:
            logger.debug("流式更新失败(停用流式,回落一次性发送)", exc_info=True)
            self._broken = True
            return
        self._last_ts = now
        self._last_text = text

    def finalize(self, final_text: str) -> bool:
        """把草稿定格成最终回复。返回 True=这条已由我发出,调用方不要再发一遍。

        草稿内容与最终文本一致时不做多余编辑(省一条事件)。最终文本为空(终止性工具场景)
        时保留草稿原样——那是模型真实说过的引导语,留着比删掉好。
        """
        if self._broken or self.event_id is None:
            return False
        final = (final_text or "").strip()
        if not final:
            return True     # 空回复:草稿已在房里,别再发一条空消息
        if final == self._last_text:
            return True     # 草稿正好就是最终文本,省一条编辑事件
        try:
            if not self._edit(final):
                # 定格失败:草稿停在中途会让用户看到半截话——如实退回,让调用方补发完整回复
                self._broken = True
                return False
        except Exception:
            logger.debug("定格流式回复失败(回落一次性发送)", exc_info=True)
            self._broken = True
            return False
        return True


# 公开回调端点（外部工作流平台调）允许的最大请求体（防无认证内存 DoS）。
# 工作流结果文本不大、下游还会截断，512KB 绰绰有余。
_MAX_CALLBACK_BODY = 512 * 1024
# 回调结果发进群的消息正文上限（防超 Matrix 事件大小→send 持续失败→无限重试）。
_MAX_WF_MSG = 4000
# Synapse 事务推送请求体上限（纵深防御；批量事件给足余量）。
_MAX_TXN_BODY = 8 * 1024 * 1024

# 主 AI 的「交互行为准则」——内置基线，每轮对话都注入（在管理员人设/RULE 之上做底）。
# 目的：把"含糊指令"这类问题统一处理成「先推断+直接做+说假设+给下一步」，而不是反问干等。
# 放在 _skill_addendum 最前段；它是行为风格，不与平台硬约束冲突（硬约束随后注入、优先级更高）。
_INTERACTION_POLICY = (
    "【交互行为准则（始终遵守）】\n"
    "1. 指令信息不全时：先用最近对话、当前工作区、用户画像推断意图，给出合理默认并**直接执行**；"
    "执行后简要说明你的假设，并主动给出下一步可选项。不要用开放式反问让用户干等。\n"
    "2. 仅当动作代价高、不可逆、或存在真正歧义时，才提出**一个**最关键的澄清问题。\n"
    "3. 建群/建频道/拆任务等轻量、可撤销的动作：一律先做、再让用户调整，不要先追问名字。\n"
    "4. 凡是能用工具真正完成的事，就调用工具去做，而不是只用文字描述步骤。\n"
    "5. 每次回复尽量落一个明确的「下一步」，把事情向前推进。\n"
    "6. 让 AI 同事写内容并发到频道时：**每段内容都用 send_message_to_room 的 as_agent 参数、"
    "以该同事的身份发出**（各填各的 slug，如 copywriter/social/analyst，分多次调用）——这样频道里"
    "一眼看得出哪段是谁写的，同事也会自动进频道。**绝不**把多个同事的产出攒成一条、以你自己"
    "（主AI）的名义统一发出（那样用户分不清内容归属、同事也没露面）。\n"
    "7. 汇报任务/交付状态时**只依据工具的真实返回**：没有拿到工具成功回执，就**不要**声称"
    "「已创建/已派单/已交付/已完成/已归档」。绝不凭对话记忆或想当然编造进度（如没核实就说"
    "『N 个任务全部交付』）。拿不准时先用 list_room_tasks 看真实看板、用 get_recent_messages"
    "看频道里到底发了什么，再如实汇报——查到是空的就直说是空的。\n"
    "8. **用户交代的每件事都要落成任务**：只要用户是在「让你做一件事」（装个技能、写篇文案、"
    "查个数据、建个群…），就用 create_tasks 记一条——**哪怕它只有一步、不需要拆解**。"
    "用户要能在进度面板里看到「我交代的事进行到哪了」，而不是做完就无影无踪。\n"
    "   · 只有一步就建一条，别硬凑多条；goal 写这件事的目标（如「导入 PPT 技能」）。\n"
    "   · 做完立刻用 update_task 标 done——建了不更新，面板会一直挂着"
    "「进行中」，比不建更糟。\n"
    "   · **例外**：纯聊天、问答、查询、闲聊不建任务（「今天几号」「你能干嘛」"
    "「解释一下这段代码」这类没有交付物的，建了只会把看板刷满噪音）。"
)


def _token_hash(token: str) -> str:
    """回调 token 只在 DB 里存**哈希**（#4）：DB/日志泄露也拿不到可用的明文 token。
    明文 token 只活在交给外部平台的回调地址里、且单次用完即废。"""
    import hashlib

    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def _env_int(name: str, default: int) -> int:
    """读整数型环境变量（走 cosmac.config._env 的 COSMAC_/GUDUU_ 前缀回退）；非法/空回 default。"""
    from cosmac.config import _env

    try:
        v = _env(name, "")
        return int(v) if str(v).strip() else default
    except (TypeError, ValueError):
        return default


def _stream_reply_enabled() -> bool:
    """流式回复总开关（默认**开**；设 COSMAC_STREAM_REPLY=0 可一键关掉回落旧行为）。

    默认开是因为它纯属体验增强、且内部全程 best-effort（坏了自动回落一次性发送）；
    留这个开关是为了万一线上表现异常（编辑刷屏/客户端渲染问题），改 env 重启即可止血，
    不用回滚发版。
    """
    return _env_int("STREAM_REPLY", 1) != 0


class CosmacBot:
    """主 AI 的事件处理核心：把 Synapse 推来的事件变成 AI 的反应。"""

    def __init__(self, config: CosmacConfig):
        self.config = config
        # 主 AI 操作 IM 的"手"
        self.client = MatrixClient(
            homeserver_url=config.homeserver_url,
            as_token=config.as_token,
            bot_user_id=config.bot_user_id,
        )
        # 主 AI 的"大脑"（可配置的多模型后端）
        self.llm: LLMProvider = get_provider(config)
        # 主 AI 的"工具箱"（把指令落成真实 IM 操作）+ "会动手的大脑"Agent
        self.toolbox = Toolbox(
            self.client, control_room_alias=config.control_room_alias
        )
        # 会员等级（账号权限分层）读写：控制室 cosmac.members（见 cosmac.members）。
        # 用于「会员」自查/管理命令，以及预留给模块4支付的 grant_member_tier。
        self.members = MembersStore(self.client, config.control_room_alias)
        # 功能门控策略：控制室 cosmac.gating（带 TTL 缓存）。后台配「能力→最低等级」，
        # bot 在执行点服务端强制（见 _gate_allows / _tool_gate_check）。
        self.gating = GatingStore(self.client, config.control_room_alias)
        # 用量配额（变现第二步）：控制室 cosmac.quotas（带 TTL 缓存）。后台配「计量项→各等级上限」，
        # bot 在执行点服务端计数 + 强制（见 _quota_limit / _rate_quota_blocked）。计数进 cosmac DB。
        from cosmac.quotas import QuotaStore

        self.quotas = QuotaStore(self.client, config.control_room_alias)
        # 模块4 变现·Token 经济（P1）：用户 token 钱包 + 计量 + 充值。读控制室 cosmac.token_config
        # （倍率/汇率/免费日额度/总开关，带 TTL 缓存），钱包/流水进各实例 cosmac DB。
        # **总开关默认关**——现网存量用户钱包都是 0，开关关着时 precheck/charge 全放行、零影响；
        # 等前端充值与赠送就绪、给存量用户补过额度后，管理员后台再打开（见 cosmac/wallet.py）。
        from cosmac.wallet import WalletStore

        self.wallet = WalletStore(self.client, config.control_room_alias)
        # 模块4 交易系统：订单服务（读控制室套餐 cosmac.plans + 建订单 + 支付成功开会员）。
        # 前端「升级会员」走 bot 的 /cosmac/pay/* 端点调它（前端够不到 cosmac DB）。
        from cosmac.trading.service import OrderService

        self.orders = OrderService(
            self.members, self.client, config.control_room_alias,
            wallet=self.wallet,  # token 充值单支付成功后经它入账（1c）
        )
        # 让 run_workflow 工具能走异步连接器的回调协议（#1）：注入 bot 的 _dispatch_async。
        # 没配 public_url 时不注入——_dispatch_async 没有回调地址也没意义。
        if config.public_url:
            self.toolbox.dispatch_async = self._dispatch_async
        # 功能门控：把工具调用也接进会员门控（"让 AI 帮我建群/跑工作流"与命令同一道闸）。
        self.toolbox.gate_check = self._tool_gate_check
        # 用量配额：可计量工具（建专班数/工作流次数）按 tier 限量（变现第二步）。
        # check 只拦超额；consume 由工具在成功路径上调（先扣后执行会把失败也扣，审查 bug#7）。
        self.toolbox.quota_check = self._tool_quota_check
        self.toolbox.quota_consume = self._tool_quota_consume
        # 知识库检索工具化：把 bot 的检索逻辑注入 Toolbox，让主 AI 能主动调 search_knowledge
        # 工具（在每轮盲塞 RAG 之外，模型还能用精准关键词多次深挖）。门控走 knowledge 闸。
        self.toolbox.kb_search = self._kb_search_for_tool
        # 能力名册（模块3.5 档1）：注入"列出可调配资源"的回调，让主AI 拆任务时知道找谁。
        self.toolbox.list_capabilities = self._list_capabilities_for_tool
        # 从 GitHub 装 Skill/Agent：preview 只读、import 才落库(且要带预览的 sha256)
        self.toolbox.manifest_preview = self._manifest_preview_for_tool
        self.toolbox.manifest_import = self._manifest_import_for_tool
        # 频道清单可见范围：管理员/负责人可跨工作区看全部频道，普通用户只看自己在的（隐私边界）。
        self.toolbox.is_admin = self._is_platform_admin
        # 邀请前校验停用账号用：AI 拉人时跳过登不进来的停用账号（负责人实报）。
        self.toolbox.inactive_users = self._deactivated_user_ids
        # update_task 授权用：与看板「看得到=改得动」同口径，执行者本人可跨频道改自己的任务
        # （负责人实报:执行者让 AI 改自己的任务被拦、AI 还谎报 done 却另建了新任务）。
        self.toolbox.can_access_task = self._can_access_task
        # 资源存在性校验(组班链路完善):assemble_team 据此识别"库里没有的 Agent/Skill"并提醒缺口。
        # M2 越权修复:带 for_user 时按发起人 access 过滤——发起人**够不到**的受限智能体不进可见集,
        # assemble_team 里点名它当 lead/worker 会被当"缺口"剔除(不注入其付费人设),堵住"点名绕过
        # 名册过滤"。for_user=None 保持全量(供无发起人上下文的场景)。
        # 返回 dict[slug→名称](而非纯 slug 集合):assemble_team 的宽容解析据此支持
        # 按中文名匹配(模型有时写「营销活动策划」而非 slug),精确 slug 匹配照常。
        self.toolbox.known_agents = lambda for_user=None: {
            str(a.get("slug") or ""): str(a.get("name") or "")
            for a in self._global_agent_items()
            if a.get("slug") and (for_user is None or self._resource_visible(a, for_user))
        }
        # 用 _skill_library(含预置技能):否则主 AI 组班时绑预置技能会被误报"库里没有"
        self.toolbox.known_skills = lambda for_user=None: {
            str(s.get("slug") or ""): str(s.get("name") or "")
            for s in self._skill_library()
            if s.get("slug") and (for_user is None or self._resource_visible(s, for_user))
        }
        # AI 任务自动执行器:专班派单后,派给 AI 同事的任务后台自动执行(产出发频道+回填看板)
        self.toolbox.auto_execute_agent_tasks = self._auto_execute_agent_tasks
        # 方案B:建专班时把协作 Agent 的傀儡账号拉进频道(注册→邀请→join,幂等)
        self.toolbox.ensure_worker_in_room = self._ensure_worker_in_room
        self.agent = Agent(
            llm=self.llm,
            toolbox=self.toolbox,
            system_prompt=config.system_prompt,
        )
        # 已处理过的事务 id，用于去重（Synapse 可能重发同一批事件）。
        # #2：用有界 LRU(OrderedDict) 防无限增长；并尽力持久化到 DB，重启后也能识别重放。
        self._seen_txns: "OrderedDict[str, None]" = OrderedDict()
        self._seen_txn_calls = 0  # 计数器，偶尔触发一次 DB 旧记录清理
        self._last_orphan_sweep: float = float("-inf")
        # 「按群模型覆盖」用的 Agent 缓存：model_id → Agent（同 provider 换 model）。
        # 全局配置(provider/人设)变化时清空，避免用到旧 provider/人设构建的实例。
        self._model_agents: Dict[str, Agent] = {}

        # —— 运行时 AI 配置（管理后台「AI 配置」下发）——
        self._control_room: Optional[str] = None  # 控制室 room_id（别名解析一次后缓存）
        self._cfg_cache: Dict[str, Any] = {}
        # 「AI 会话房」判定缓存(room_id → 是否带 cosmac.ai_session 标记;标记不变,永久缓存)
        self._ai_session_room_cache: Dict[str, bool] = {}
        self._named_channel_cache: Dict[str, bool] = {}  # 房间是否"实名频道"(私聊/群聊判定用)
        # 用户→入驻模板缓存(资源「可用范围」判定用;5 分钟 TTL,引导完成后很快生效)
        self._user_template_cache: Dict[str, Tuple[str, float]] = {}
        # 用户→商城「已获取」智能体 slug 缓存(能力名册每条消息都查;获取端点写入时主动失效)
        self._acquired_cache: Dict[str, Tuple[Set[str], float]] = {}
        # 用户→已获取的**创作者 Agent**(cagent listing)缓存(P2 创作者商城;同上口径)
        self._acquired_cagent_cache: Dict[str, Tuple[List[Dict[str, Any]], float]] = {}
        # 用户→**已买断的创作者技能**(cskill listing)缓存(P4;每轮注入都查,必须缓存)
        self._acquired_cskill_cache: Dict[str, Tuple[List[Dict[str, Any]], float]] = {}
        # AI 同事傀儡账号缓存(slug → MXID;空串=注册失败,重启前不重试)
        self._worker_account_cache: Dict[str, str] = {}
        # 傀儡「已在房」缓存((room_id, slug)):免每次发送前重复 邀请+join 两个 HTTP
        self._worker_in_room_cache: Set[Tuple[str, str]] = set()
        # 平台管理员判定缓存(user_id → (是否, ts)):60 秒 TTL + power_levels 事件清表(评审 #9)
        self._admin_flag_cache: Dict[str, Tuple[bool, float]] = {}
        # ═══ 群消息热路径缓存(评审 #3):@智能体触发判定跑在**每条**群消息上,
        # 其依赖的 全局agent/技能库(控制室 state)、群配置(room state)、自建agent(DB)
        # 此前每次都发 HTTP/SQL——活跃群 20 条闲聊≈数百次串行请求。═══
        # 全局 agent/技能原始合并列表(20 秒 TTL,与后台「保存后约 20 秒热生效」同口径)
        self._agents_items_cache: Tuple[List[Dict[str, Any]], float] = ([], float("-inf"))
        self._skills_items_cache: Tuple[List[Dict[str, Any]], float] = ([], float("-inf"))
        # 群配置缓存(room_id → (gctx, ts)):20 秒 TTL 兜底 + 收到 channel_config
        # state 事件时**精确失效**(改绑定零延迟生效,见 _handle_event)
        self._gctx_cache: Dict[str, Tuple[Dict[str, Any], float]] = {}
        # 自建智能体缓存(owner → (列表, ts)):5 分钟 TTL,工坊保存/删除端点写入时失效
        self._my_agents_cache: Dict[str, Tuple[List[Dict[str, Any]], float]] = {}
        # SDK 引擎回退告警的节流时间戳(1小时最多向控制室发一条,防刷屏)
        self._engine_alert_ts: float = 0.0        # 上次读到的配置覆盖
        # —— 任务时效提醒（定时扫描）——扫描间隔 + "快到期"窗口，都可用 env 调；单实例内定时够用。
        # 【并发】AI 回复线程池:appservice 事务是串行等 ack 的,LLM 长任务若在事务线程
        # 同步跑会堵死全平台消息(负责人实报:一个账号执行中,另一账号问 AI 完全无响应)。
        # 回复剥到工作线程,事务立即 ack;同房间加锁保序,不同账号并发。
        # 同一账号即使跨房间也必须串行：配额/钱包采用“回复前检查、回复后结算”，若只锁
        # 房间，同一用户可在多个房间同时穿过前拦，形成免费多跑 LLM 的计费竞态。
        # None = 同步模式(单测/调试用,COSMAC_SYNC_REPLY=1 或测试里置 None)。
        from concurrent.futures import ThreadPoolExecutor
        self._reply_pool: Optional[ThreadPoolExecutor] = (
            None if _env_int("SYNC_REPLY", 0) else
            ThreadPoolExecutor(max_workers=4, thread_name_prefix="ai-reply")
        )
        self._room_reply_locks: Dict[str, threading.Lock] = {}
        self._user_reply_locks: Dict[str, threading.Lock] = {}
        # 锁字典本身也要受保护：两个线程若同时为同一新用户建锁，不能各拿到不同 Lock，
        # 否则表面“加锁”实际仍会并行。这里只保护取/建锁的极短临界区，不包 LLM 调用。
        self._reply_locks_guard = threading.Lock()
        self._reminder_interval_secs = _env_int("TASK_REMINDER_INTERVAL", 900)  # 默认每 15 分钟扫一次
        _soon_hours = _env_int("TASK_REMINDER_SOON_HOURS", 24)                  # 默认到期前 24h 提醒
        self._reminder_soon_secs = max(1, _soon_hours) * 3600
        # 上次读取时间（缓存 20s，别每条消息都打服务器）。
        # 用 -inf 当"从未读过"的哨兵：保证首次必读（monotonic 起点不定，别用 0）。
        self._cfg_cache_ts: float = float("-inf")
        # 当前已生效的 (provider, model, system_prompt, _) 签名；任一项变了才热重建模型/Agent。
        # 第 4 段保留位恒为 ""（key 只走环境变量、绝不进签名，见 _apply_runtime_config）。
        self._applied_sig: Tuple[str, str, str, str] = (
            config.llm_provider, config.llm_model, config.system_prompt, "",
        )

    # —— 事件分发 ——

    _SEEN_TXN_MAX = 4096  # 内存去重 LRU 上限（防无限增长）
    _ORPHAN_SWEEP_INTERVAL = 300.0  # 有事务流量时每 5 分钟检查一次提交遗孤

    def handle_transaction(self, txn_id: str, events: List[Dict[str, Any]]) -> bool:
        """处理 Synapse 推来的一批事件（一个事务）。返回是否可回 200。

        去重 + 崩溃安全（#2/#3）：内存有界 LRU 快路 + DB **原子两阶段抢占**。
          - True ：已处理完 / 已是重复（回 200，告诉 Synapse 别重发）。
          - False：另一处理中(未过期)，或 DB 暂判定让位（回非 200，让 Synapse 稍后重试）——
                   避免重复处理，也避免"先标记后处理"在崩溃时永久丢一整批。
        """
        now = time.monotonic()
        if now - self._last_orphan_sweep >= self._ORPHAN_SWEEP_INTERVAL:
            # 在正常事务循环里周期执行，弥补“只在启动时扫一次”导致新遗孤永久残留。
            self._last_orphan_sweep = now
            self.recover_interrupted_runs()
        # 内存快路：本进程已处理过直接跳过（也是 DB 不可用时的唯一防线）
        if txn_id in self._seen_txns:
            logger.info("事务 %s 已处理过（内存），跳过", txn_id)
            return True

        # DB 原子抢占。DB 不可用 → None，退回"内存标记后处理"（尽力而为）。
        status = self._claim_txn(txn_id)
        if status == "done":
            self._remember_txn(txn_id)  # 回填内存，下次走快路
            logger.info("事务 %s 已处理完（持久化），跳过重放", txn_id)
            return True
        if status == "inflight":
            # 另一处理中且未过期：不重复处理，让 Synapse 稍后重试（届时多半已 done→200）
            logger.info("事务 %s 正在处理中，让上游稍后重试", txn_id)
            return False

        # status == "claimed"（抢到）或 None（无 DB，退回内存去重）：占住并处理
        had_error = False
        for event in events:
            try:
                self._handle_event(event)
            except Exception:
                logger.exception("处理事件出错: %s", event.get("event_id"))
                had_error = True
        if had_error:
            # 任一事件失败都不能把整个 txn 标记 done；否则 Synapse 会认为已成功投递，
            # 失败事件永久丢失。这里返回 False 让上游重试（成功事件需靠各自幂等保护）。
            return False
        # #1：**处理成功后**才标记 done + 记内存。绝不能在处理前就写内存——否则处理途中
        # Synapse 超时重试会命中内存快路直接回 200，原处理若随后崩溃，DB 的 processing
        # 再没机会被重抢（Synapse 已不再重试）→ 整批永久丢。
        # 进程崩在处理中途则到不了这里：DB 行留 processing、内存也没记，过期后由 Synapse
        # 重试时 claim 重新抢占重处理（at-least-once，不永久丢）。
        self._finish_txn(txn_id)
        self._remember_txn(txn_id)
        return True

    def recover_interrupted_runs(self) -> None:
        """周期结清长期停在提交阶段的工作流运行并通知用户（尽力而为）。

        进程内线程池不跨重启——in-flight/排队的提交与 ComfyUI 轮询随旧进程一起消失，
        对应的 queued 永远等不到开始。启动时和事务周期内都收口；pending 只在超过可配置
        回调期限后标记超时，避免永久残留。DB 不可用则跳过。
        （注意：这是"让中断**可见**"，不是"恢复执行"——真要不丢任务需durable队列，见架构说明。）
        """
        try:
            from cosmac.db import session_scope
            from cosmac.db.wf_repo import reclaim_orphans

            with session_scope() as s:
                orphans = reclaim_orphans(s)
        except Exception:
            return  # 没 DB / 出错：跳过，不阻断启动
        for run_id, slug, room_id, reason in orphans:
            if not room_id:
                continue
            try:
                # 固定 txn id：万一通知本身重发也被 Synapse 去重，群里不重复
                self.client.send_text(
                    room_id,
                    f"⚠️ 工作流「{slug}」(#{run_id}) {reason}。"
                    "请先到外部平台确认任务状态，再决定是否重试。",
                    txn_id=f"cosmac-wf-orphan-{run_id}",
                )
            except Exception:
                logger.warning("通知中断运行失败 run_id=%s", run_id)
        if orphans:
            logger.info("启动时结清 %d 条中断的工作流运行", len(orphans))

    def _remember_txn(self, txn_id: str) -> None:
        """记进内存有界 LRU；超上限淘汰最旧的。"""
        self._seen_txns[txn_id] = None
        self._seen_txns.move_to_end(txn_id)
        while len(self._seen_txns) > self._SEEN_TXN_MAX:
            self._seen_txns.popitem(last=False)

    def _claim_txn(self, txn_id: str) -> Optional[str]:
        """DB 原子抢占（尽力而为）。返回 'claimed'/'done'/'inflight'；DB 不可用返回 None。"""
        try:
            from cosmac.db import session_scope
            from cosmac.db.dedup import claim_txn

            with session_scope() as s:
                return claim_txn(s, txn_id)
        except Exception:
            return None  # 没 DB → 调用方退回内存去重，不阻断收消息

    def _finish_txn(self, txn_id: str) -> None:
        """标记事务处理完成（尽力而为）；偶尔顺手清理过期记录控制表大小。"""
        try:
            from cosmac.db import session_scope
            from cosmac.db.dedup import finish_txn, prune_old

            with session_scope() as s:
                finish_txn(s, txn_id)
                self._seen_txn_calls += 1
                if self._seen_txn_calls % 500 == 0:
                    prune_old(s)
        except Exception:
            pass  # 没 DB 就只靠内存去重，不阻断收消息

    def _handle_event(self, event: Dict[str, Any]) -> None:
        """处理单条事件。"""
        sender = event.get("sender", "")
        event_id = event.get("event_id", "")
        event_type = event.get("type", "")
        room_id = event.get("room_id", "")

        # 忽略主 AI 自己发的消息，否则会无限自我回复;
        # 方案B:AI 同事傀儡账号发的消息同样忽略——否则傀儡交付产出会触发 bot 再应答,自转不停
        if sender == self.config.bot_user_id or self._worker_slug_of(sender):
            return

        # 模块6 心跳统计：记一条"今日看到的用户消息"（未接入 OEM 体系时只是加个内存计数）
        if event_type == "m.room.message":
            nexus_link.note_message()

        # 1) 被邀请进群 → 自动加入
        if event_type == "m.room.member":
            membership = event.get("content", {}).get("membership")
            state_key = event.get("state_key")
            if state_key == self.config.bot_user_id and membership == "invite":
                logger.info("收到来自 %s 的入群邀请，自动加入 %s", sender, room_id)
                self.client.join_room(room_id)
            return

        # 1b) 控制室「期望管理员集」变化 → 主 AI(power 100)对齐控制室成员：
        #     把不再是服务器管理员、却仍有写权限的成员降权 + 踢出。这是浏览器(管理员
        #     power 只有 50)做不到的——同级互相无法降权/踢出，所以交给 100 的 bot 执行。
        if event_type == CONTROL_ADMINS_EVENT_TYPE and event.get("state_key") is not None:
            self._reconcile_control_members(room_id, event.get("content", {}))
            return

        # 1c) 本房频道配置(channel_config)变了 → 群配置缓存精确失效:
        #     改绑定/人设/RULE 零延迟生效(缓存另有 20 秒 TTL 兜底事件丢失,评审 #3)。
        if event_type == CHANNEL_CONFIG_EVENT_TYPE and event.get("state_key") is not None:
            self._gctx_cache.pop(room_id, None)
            return

        # 1d) 后台改了全局智能体/技能(控制室 state)→ 20 秒缓存提前失效,即刻热生效
        if event_type == AGENTS_EVENT_TYPE and event.get("state_key") is not None:
            self._agents_items_cache = ([], float("-inf"))
            return
        if event_type == SKILLS_EVENT_TYPE and event.get("state_key") is not None:
            self._skills_items_cache = ([], float("-inf"))
            return
        # 1e) 会员等级/控制室权限变了 → 相关 60 秒缓存清表,变更即刻生效(评审 #9)。
        #     后台直改 state 不经 grant(),只有这里能感知;变更低频,整表清无碍。
        if event_type == MEMBER_EVENT_TYPE and event.get("state_key") is not None:
            try:
                self.members.invalidate_cache()
            except Exception:
                pass
            return
        if event_type == "m.room.power_levels" and event.get("state_key") is not None:
            self._admin_flag_cache.clear()
            # 不 return:power_levels 变化极少,后续无消息处理逻辑,直接落到默认忽略

        # 2) 群里的文本消息
        if event_type == "m.room.message":
            content = event.get("content", {})
            if content.get("msgtype") != "m.text":
                return  # 第一步只处理纯文本，图片/文件等以后再说
            # 编辑事件(m.replace)不是新消息：AI 会话房/私聊对每条 m.text 都回，若不排除，用户编辑
            # 一次自己发过的消息，bot 会对 fallback 正文"* 新内容"再答一遍(#10)。编辑不触发新回复。
            relates = content.get("m.relates_to")
            if isinstance(relates, dict) and relates.get("rel_type") == "m.replace":
                return
            user_text = content.get("body", "")

            # 私聊（仅用户+主AI，≤2人）里对每句话都回；
            # 群聊里只在被 @ 提及时才回（避免误触发/刷屏）。
            # ⚠️ AI 会话房(带 cosmac.ai_session 标记)**永远按私聊对待**——它可能被误拉进第三人
            # 而超过 2 人,若只按人数判定,bot 会突然要求 @ 才响应,用户在 AI 面板里莫名"无响应"
            # (实测踩过)。标记判定优先,人数是兜底。
            # ⚠️ 人数兜底只对**无名房/「中枢 AI」房**生效(兼容无标记的旧私聊房)——实名频道
            # 即使暂时只有 2 人也按群聊。否则新频道人少时每句必回、成员加入后突然要 @ 才回,
            # 用户看到的就是"AI 在频道里时灵时不灵"(QA)。
            is_dm = self._is_ai_session_room(room_id) or (
                self.client.joined_member_count(room_id) <= 2
                and not self._room_is_named_channel(room_id)
            )
            # 群聊触发有两条路:① 叫主 AI 本尊(@/名字开头);② **点名某个可路由的智能体**
            # (专班绑定 worker / 本人自建 / 商城已获取)——负责人实测「@copywriter 润色」没
            # 反应的根因就是此前只有 ①,消息在这被丢弃,根本走不到档3b 的 worker 路由。
            mentioned_ids = [
                str(u) for u in ((content.get("m.mentions") or {}).get("user_ids") or [])
            ]
            if (not is_dm and not self._is_bot_mentioned(content)
                    and not self._agent_mention_hit(room_id, sender, user_text, mentioned_ids)):
                return
            logger.info(
                "[房间 %s|%s] %s: %s",
                room_id, "私聊" if is_dm else "群@", sender, user_text,
            )

            # 去掉开头的 @提及，拿到真正的指令/内容
            text = self._strip_mention(user_text)

            # 2a) 确定性命令快路（建专班等）。命中就执行动作、不再走 Agent。
            #     保留它做"一句话直接出富卡派单"的演示；自然语言走下面的 Agent。
            if self._try_handle_command(room_id, sender, text, event_id=event_id):
                return

            # 2b) 否则交给会"动手"的 Agent。但先过「基础 AI 对话」门控：低于门槛的用户
            #     @ 中枢AI 会被礼貌提示升级（命令如「会员/技能/知识/工作流」已在上面处理、
            #     不受此门控影响——保证用户随时能查/升级会员）。
            if not self._gate_allows(sender, "ai_chat"):
                self.client.send_text(room_id, self._gate_denied_text("ai_chat"))
                return
            # 【并发修复·负责人实报】AI 回复(LLM+工具循环)可能跑几分钟——事务线程里
            # 同步跑会让 Synapse 等 ack、后续所有用户的消息被堵死。改为线程池异步:
            # 事务立即 ack;同房间加锁保序,不同房/不同账号并发互不影响。
            if self._reply_pool is None:   # 同步模式(单测/调试)
                self._reply_locked(room_id, sender, user_text, text,
                                   content, is_dm, event_id or "", mentioned_ids)
            else:
                self._reply_pool.submit(
                    self._reply_locked, room_id, sender, user_text, text,
                    content, is_dm, event_id or "", mentioned_ids,
                )
            return

    # 短期记忆窗口：最多带最近这么多条历史；单条正文截断长度（控 token）。
    _HISTORY_LIMIT = 12

    # 长期记忆：每多少轮回复后台重摘要一次（攒一批再摘，省 LLM 调用）；摘要字数上限。
    _MEMORY_SUMMARIZE_EVERY = 8
    _MEMORY_SUMMARY_CHARS = 400

    def _reply_locked(
        self, room_id: str, sender: str, user_text: str, text: str,
        content: Dict[str, Any], is_dm: bool, event_id: str,
        mentioned_ids: List[str],
    ) -> None:
        """AI 回复工作线程入口：同用户、同房间串行，不同用户并发；绝不抛异常。

        用户锁覆盖“配额/余额前查 → LLM → 回复 → 结算”的完整周期，堵住同一账号跨房间
        并发穿透计费；房间锁继续保证不同用户在同一房间的回复顺序。统一按“用户→房间”
        顺序取锁，避免未来扩展时出现锁顺序倒置的死锁。
        """
        with self._reply_locks_guard:
            user_lock = self._user_reply_locks.setdefault(sender, threading.Lock())
            room_lock = self._room_reply_locks.setdefault(room_id, threading.Lock())
        with user_lock, room_lock:
            try:
                self._reply_to_message(
                    room_id, sender, user_text, text, content, is_dm,
                    event_id, mentioned_ids,
                )
            except Exception:
                logger.exception("异步 AI 回复失败(已兜底,不影响其他消息)")

    def _reply_to_message(
        self, room_id: str, sender: str, user_text: str, text: str,
        content: Dict[str, Any], is_dm: bool, event_id: str,
        mentioned_ids: List[str],
    ) -> None:
        """生成并发送一条 AI 回复(原 _handle_event 内联主体,并发修复时提取)。"""
        # 用量配额（变现第二步）：每天 AI 对话条数。超额提示升级并停在这（不消耗 LLM）。
        # L2：这里**只查不扣**——真正出成回复后才计数(见下方 send_text 成功之后)。否则 LLM
        # 报错/超时/工具循环崩了也照扣，用户白白少一次额度却没得到任何回复(与工具路径"成功
        # 才扣"、#7 失败兜底同口径)。
        quota_msg = self._rate_quota_blocked(sender, "ai_msg_daily", consume=False)
        if quota_msg:
            self.client.send_text(room_id, quota_msg)
            return
        # Token 经济前拦（模块4）：今日免费额度 + 钱包余额都空则拦（总开关关时恒放行）。
        # 与配额同口径——回复前只拦、不扣，模型输出量在回复成功后结算。
        wallet_msg = self._wallet_precheck_blocked(sender)
        if wallet_msg:
            self.client.send_text(room_id, wallet_msg)
            return
        #     它能边想边调用工具（建群/发消息/查记录），最后把结论发回群。
        #     （echo 后端不支持工具，会自动退化为纯文本回复。）
        # ③ 流式体感：进入可能较慢的 LLM 生成/工具调用前打开"正在输入…"，让用户看到
        # bot 在干活而非死寂；try/finally 保证无论成功失败都关掉、不卡住输入中状态。
        self.client.set_typing(room_id, True)
        try:
            # 回复前先按管理后台下发的运行时配置（人设/模型/工具开关）对齐一次。
            self._apply_runtime_config()
            # 本群上下文读一次（人设/绑定技能/模型覆盖），供 addendum 与选模型共用。
            gctx = self._group_context(room_id)
            # 档3b：消息点名了某可路由智能体(worker/自建/已获取)→ 以它的人设/技能/模型
            # 回这条(任务RULE 不变);没点名维持 lead。⚠️ 传**原始正文** user_text +
            # m.mentions——与触发判定同一输入(text 被 _strip_mention 剥过句首 @,
            # 用它路由会让「@文案 …」永远切不到已获取智能体,评审 #1)。
            gctx = self._apply_worker_routing(
                user_text, gctx, sender=sender, mentioned_ids=mentioned_ids,
            )
            # 创作者 Agent 按次付费前拦（P2）：固定价/次是预付语义——余额不够这一次就
            # 明确拒绝，不产生欠账。仅创作者本人免（自己用自己的不形成销售）。
            cag_listing = int(gctx.get("cagent_listing") or 0)
            cag_price = int(gctx.get("cagent_price") or 0)
            # 创作者商品不是平台自己的 AI 用量：平台管理员只能豁免平台用量，不能免掉
            # 应付给第三方创作者的标价，否则管理员测试/使用会让创作者零收益。唯一免付者
            # 是商品创作者本人（自用不形成虚假销售流水）。
            cag_payer = bool(
                cag_listing and cag_price > 0
                and sender != str(gctx.get("cagent_creator") or "")
            )
            if cag_payer:
                try:
                    blocked = self.wallet.agent_use_precheck(sender, cag_price)
                except Exception:
                    # 付费商品必须 fail-closed：计费服务坏掉时放行，会直接把创作者的付费
                    # 商品送成免费。平台内置 AI 仍维持既有 fail-open 可用性口径。
                    logger.exception(
                        "创作者 Agent 计费前置校验失败：buyer=%s listing=%s",
                        sender, cag_listing,
                    )
                    blocked = "创作者 Agent 计费服务暂时不可用，本次没有扣费，请稍后再试。"
                if blocked:
                    self.client.send_text(room_id, blocked)
                    return
            # 按 (本群, 发起人) 算出本轮 system addendum：人设 + 技能 + 知识库检索片段(RAG)。
            # 任何失败（DB 没装/没数据/出错）都返回空串、绝不阻断回复（见 _skill_addendum）。
            # 图文教程答疑：全局图文(付费可读)会在 _kb_context 里按 doc_read 门控自动纳入 RAG，
            # 让中枢 AI 也能基于平台图文内容作答（无需前端传作用域）。
            extra_system = self._skill_addendum(
                room_id, sender, query=text or user_text, gctx=gctx,
                is_dm=is_dm,
            )
            # 双层作用域指令(频道分身 vs 全局助理):告诉 AI 它现在是哪种身份、边界在哪。
            # 智能水平两种模式相同(同一引擎/能同样拆任务建专班),只是"能拿到的原料"不同。
            extra_system = self._scope_directive(is_dm) + (
                ("\n\n" + extra_system) if extra_system else ""
            )
            # 频道感知(负责人报:中枢 AI 在多频道切换时把上一频道的约束带进当前频道):
            # 全局会话横跨多个频道话题,前端随消息捎「当前所在频道」,历史消息也带同款
            # 标记(见 _recent_history 的〔当时在频道:X〕前缀)——在此明确告诫按频道区分。
            if is_dm:
                active_room = str(content.get("cosmac.active_room_name") or "").strip()
                where = f"用户此刻正在查看频道「{active_room}」。" if active_room else ""
                extra_system += (
                    f"\n\n【频道上下文纪律】{where}你们的对话历史横跨多个频道/项目"
                    "(历史消息前的〔当时在频道:X〕标记了当时的频道)。回答本条时:"
                    "只依据用户本条消息与其当前频道的语境;**其他频道的规则、约束、任务、"
                    "人设一律不得带入**,除非用户明确提到。不确定用户指哪个频道时,先确认再答。"
                )
            # 短期记忆：把本房间最近的对话(不含当前这条)喂给模型，主 AI 才"记得"上文。
            history = self._recent_history(room_id, sender, user_text)
            # 本群若绑定的智能体指定了模型 → 用该模型的 Agent 回这条（否则用默认 Agent）。
            agent = self._agent_for_model(gctx.get("model", ""))
            tool_ctx = ToolContext(
                room_id=room_id, sender=sender,
                source_key=f"event:{event_id}:ai" if event_id else "",
                is_dm=is_dm,   # 工具层防"把人邀进私聊"等语义事故
                # 前端随每条发给中枢AI 的消息带上当前工作区；拆任务时盖在任务上，
                # 任务看板据此按工作区过滤（私聊房的 room_id 归不了工作区）。
                space_id=str(content.get("cosmac.doc_space") or "")[:255],
                # 本频道已授权的工作流：入驻模板预置 + 频道绑定的智能体自带（都是管理员
                # 显式配置）。绑定即授权——这批在本频道免过 workflow_run 会员门控，
                # 免得出现「AI 说它能用、一调就被拒」。配额与 SSRF/凭据校验照常。
                authorized_workflows=tuple(gctx.get("workflow_slugs") or ()),
            )
            # 以谁的身份回这条：worker 路由解析出傀儡(AI 同事)就用它，否则主 AI。
            # ⚠️ 这段**必须在引擎开跑前**定下来：流式草稿一上来就要以最终身份发，
            # 不然会出现"草稿是主AI发的、定稿却该是同事发"的错位。
            # 拉不进房(权限等)则清空 as_user，直接走主 AI 身份，省一次注定失败的请求。
            as_user = str(gctx.get("as_user") or "")
            if as_user:
                _slug = self._worker_slug_of(as_user)
                if _slug and not self._ensure_worker_in_room(room_id, _slug):
                    as_user = ""
            # 流式输出：AI 边生成边把草稿消息原地更新出来（体感提速）。
            # 出任何问题都会自动停用、回落到下面的一次性发送，绝不丢回复。
            # 一键停用：设 COSMAC_STREAM_REPLY=0（改 env 重启即可，无需改代码）。
            streamer = (
                _StreamWriter(self.client, room_id, as_user)
                if _stream_reply_enabled() else None
            )
            reply, usage_tokens = self._run_agent_engine(
                agent, text or user_text, tool_ctx, extra_system, history,
                model_override=gctx.get("model", ""),  # 群级模型联动:SDK 引擎也认群模型
                stream_cb=streamer,
            )
            # 幂等发送：用 event_id 派生固定 txn_id，让 Synapse 据此去重。
            # 场景：同一事务里若有别的事件失败，handle_transaction 会让 Synapse 重发**整批**，
            # 已成功的这条 AI 回复会被重新处理；固定 txn_id 保证群里不会冒出两条同样的回复。
            # 方案B:worker 路由若解析出傀儡账号(as_user),回复以该 AI 同事本人身份发——
            # 时间线上显示它的名字/头像;傀儡发送失败退回主 AI 身份,绝不丢回复。
            # 流式已把这段话发出去了(草稿定格成最终文本)→ 跳过下面的发送，避免同一段话
            # 在群里出现两条。流式没启用/中途坏了/定格失败 → streamed=False，照旧一次性发。
            streamed = bool(streamer and streamer.finalize(reply))
            # 空回复不发多余消息(终止性工具如 ask_user_choice 已把选择卡发进房,
            # Agent 返回空串——此时再发一条空文本就是骚扰)。选择卡本身已是给用户的交互。
            if reply.strip() and not streamed:
                sent_ok = False
                if as_user:
                    sent_ok = bool(self.client.send_text_as(
                        room_id, reply, as_user,
                        txn_id=f"cosmac-ai-{event_id}" if event_id else None,
                    ))
                if not sent_ok:
                    # 兜底 txn 带 -fb 后缀:防"傀儡实际已发成功但响应丢失"时,主 AI 复用同
                    # txn 被 Synapse 去重成静默——宁可极端情况下重复一条,不可丢回复。
                    self.client.send_text(
                        room_id, reply,
                        txn_id=f"cosmac-ai-fb-{event_id}" if event_id else None,
                    )
            # AI 会话房首轮结束 → 给这段会话起个能看懂的标题（只做一次，失败静默）。
            # 放在回复发出之后：标题是附加价值，绝不该挡在用户看到回复的前面。
            self._maybe_name_ai_session(room_id, text or user_text, reply)
            # L2：回复真正发出后才消费当日 AI 对话额度（失败走下面的 except 分支、不扣）。
            self._rate_quota_blocked(sender, "ai_msg_daily", consume=True)
            # Token 经济（模块4）：回复成功后结算。**二选一**（负责人定稿）：
            # 用创作者 Agent = 按固定价/次扣并分账（90% 创作者 / 10% 平台），不再叠加
            # 平台内置 AI 按模型输出量扣（先今日免费额度、再钱包余额）。
            # 扣费失败都不影响这条已发出的回复。
            if cag_payer:
                try:
                    r = self.wallet.charge_agent_use(sender, cag_listing, room_id=room_id)
                    if r.get("charged"):
                        logger.info(
                            "创作者Agent按次扣费：buyer=%s listing=%s 价=%s 抽成=%s 创作者得=%s",
                            sender, cag_listing, r.get("charged"), r.get("fee"), r.get("net"),
                        )
                except Exception:
                    logger.debug("按次扣费失败（忽略）", exc_info=True)
            else:
                self._wallet_charge(sender, usage_tokens, room_id)
        except Exception:
            # 引擎/LLM 本体调用失败（网络错、模型不存在、后端 4xx/5xx 等）：绝不让异常穿透到
            # handle_transaction —— 那会使其返回 False、Synapse 重发**整批**、整条 Agent run
            # 从头重跑，而循环中途已执行的建群/发消息/邀人等工具**没有幂等键**、会重复副作用
            #（#7）。这里就地兜住：给用户一条明确失败提示（带 txn_id 幂等，纵使别的事件触发
            # 重发也不刷屏），然后正常返回——本条事务视为已消化，不再重试。
            logger.exception("AI 回复失败（引擎/LLM 调用异常），已就地兜底、不重试")
            try:
                self.client.send_text(
                    room_id,
                    "😵 抱歉，AI 暂时不可用（可能是模型服务波动或配置异常），请稍后再试一次。",
                    txn_id=f"cosmac-ai-err-{event_id}" if event_id else None,
                )
            except Exception:
                logger.debug("发送 AI 失败提示也失败了（忽略）", exc_info=True)
            return
        finally:
            self.client.set_typing(room_id, False)  # 关掉"正在输入…"
        # 长期记忆：回复发完后推进本群滚动摘要（到阈值才后台重摘要，绝不阻塞本次回复）。
        self._maybe_update_memory(room_id, history, text or user_text, reply, sender)

    def _maybe_update_memory(
        self, room_id: str, history: List[Message], user_text: str, reply: str,
        sender: str = "",
    ) -> None:
        """推进本群长期记忆：累计轮数到阈值就**后台**用 LLM 重摘要（不阻塞回复）。

        长期记忆是付费功能（memory 门控）：低于门槛的用户不积累/不摘要。
        全程兜异常 + DB 懒导入：没装 DB / 出错都静默跳过，绝不影响已发出的回复。
        echo 占位后端不做摘要（complete 只是回显、摘不出东西、反而污染记忆）。
        """
        if getattr(self.llm, "name", "") == "echo":
            return  # 占位后端：摘要无意义，跳过
        if sender and not self._gate_allows(sender, "memory"):
            return  # 长期记忆是付费功能：低于门槛不积累
        try:
            from cosmac.db import session_scope
            from cosmac.db.memory_repo import bump_and_check
            from cosmac.db.models import SCOPE_ROOM

            with session_scope() as s:
                due, prior = bump_and_check(
                    s, SCOPE_ROOM, room_id, self._MEMORY_SUMMARIZE_EVERY
                )
        except Exception:
            logger.debug("推进长期记忆计数失败（忽略）", exc_info=True)
            return
        if not due:
            return
        # 组装本轮要喂给摘要器的对话文本（短期窗口 + 当前这轮），在事件线程内先拼好，
        # 后台任务只做 LLM 调用 + 写库，不再碰 Matrix。
        convo = self._render_convo_for_summary(history, user_text, reply)

        def _work() -> None:
            try:
                new_summary = self._summarize_memory(prior, convo)
                if not new_summary:
                    return
                from cosmac.db import session_scope
                from cosmac.db.memory_repo import save_summary
                from cosmac.db.models import SCOPE_ROOM

                with session_scope() as s:
                    save_summary(s, SCOPE_ROOM, room_id, new_summary)
            except Exception:
                logger.exception("后台更新长期记忆失败 room=%s", room_id)

        # 走 fast 池（LLM 摘要，秒级）；池满则本轮跳过、下次到阈值再摘，不积压。
        from cosmac.wf import submit_background

        submit_background(_work, pool="fast")

    @staticmethod
    def _render_convo_for_summary(
        history: List[Message], user_text: str, reply: str
    ) -> str:
        """把短期历史 + 当前这轮渲染成"用户/助手"逐行文本，供摘要器读。"""
        lines: List[str] = []
        for m in history or []:
            who = "助手" if m.role == "assistant" else "用户"
            body = (m.content or "").strip()
            if body:
                lines.append(f"{who}: {body}")
        if user_text.strip():
            lines.append(f"用户: {user_text.strip()}")
        if reply.strip():
            lines.append(f"助手: {reply.strip()}")
        return "\n".join(lines)

    def _summarize_memory(self, prior: str, convo: str) -> str:
        """用当前 LLM 把(已有记忆 + 最近对话)融合成一份更新后的长期记忆摘要。

        只输出摘要本身；失败/空返回空串（调用方据此不覆盖旧摘要）。
        """
        if not convo.strip():
            return ""
        sys = (
            "你是对话记忆整理器。把【已有记忆】和【最近对话】融合成一份简洁的长期记忆摘要，"
            "保留：用户是谁、偏好、长期目标、已达成的结论、待办与承诺、关键事实；"
            "去掉寒暄和一次性细节。用要点式中文，"
            f"控制在 {self._MEMORY_SUMMARY_CHARS} 字内。只输出摘要本身，不要客套。"
        )
        user = (
            f"【已有记忆】\n{prior or '（暂无）'}\n\n"
            f"【最近对话】\n{convo}\n\n请输出更新后的长期记忆摘要："
        )
        try:
            out = self.llm.complete(
                [Message(role="system", content=sys), Message(role="user", content=user)]
            )
        except Exception:
            logger.debug("LLM 摘要调用失败（忽略）", exc_info=True)
            return ""
        return (out or "").strip()[: self._MEMORY_SUMMARY_CHARS * 3]  # 字数上限留余量
    _HISTORY_CHARS = 600

    def _recent_history(
        self, room_id: str, cur_sender: str, cur_body: str
    ) -> List[Message]:
        """读本房间最近消息，映射成对话历史(不含当前这条)，给主 AI 短期记忆。

        聊天记录存在 Synapse(见 CLAUDE.md §3，不重存)，这里实时读最近 N 条。
        bot 自己发的→assistant，其它人→user。任何失败都返回空(不阻断回复)。
        """
        try:
            msgs = self.client.get_messages(room_id, limit=self._HISTORY_LIMIT + 1)
        except Exception as e:
            logger.debug("读历史失败（忽略，无短期记忆继续）：%s", e)
            return []
        # 当前触发消息是**最新**那条(msgs 按旧→新排列，通常在末尾)。要剔的正是它——而不是历史里
        # 更早的同文本消息。M15：旧实现从最旧端剔第一条匹配，用户重复发"继续/好的"时被剔的是旧的、
        # 当前这条仍留在历史，随后又被 Agent.run 作为最后的 user 追加 → 模型看到当前输入出现两遍
        # (还扰乱了时序)。故从**最新端**反向定位、只剔那一条。
        cur = (cur_body or "").strip()
        drop_idx = -1
        for i in range(len(msgs) - 1, -1, -1):
            b = (msgs[i].get("body") or "").strip()
            if b == cur and (msgs[i].get("sender") or "") == cur_sender:
                drop_idx = i
                break
        out: List[Message] = []
        for i, m in enumerate(msgs):
            if i == drop_idx:
                continue
            body = (m.get("body") or "").strip()
            s = m.get("sender") or ""
            if not body:
                continue
            if len(body) > self._HISTORY_CHARS:
                body = body[: self._HISTORY_CHARS] + "…"
            role = "assistant" if s == self.config.bot_user_id else "user"
            # 频道感知(负责人报:中枢 AI 把上一频道的约束带进新频道):全局会话的历史
            # 横跨多个频道话题,给带频道标记的 user 消息加「〔当时在频道:X〕」前缀,
            # 让模型能分清历史各段分别属于哪个频道,不再张冠李戴。
            ar = str(m.get("active_room") or "").strip()
            if role == "user" and ar:
                body = f"〔当时在频道:{ar}〕{body}"
            out.append(Message(role=role, content=body))
        return out[-self._HISTORY_LIMIT:]

    def _scope_directive(self, is_dm: bool) -> str:
        """按对话模式给主 AI 的作用域指令。频道模式=频道分身(只服务本频道);全局模式=全局助理。"""
        if is_dm:
            return (
                "【你的身份：全局助理】你正在与用户的私人会话里对话。你能纵观用户所在的各个频道,"
                "可跨频道调取资料、拆解任务、调配全平台的人/AI/技能/知识库来帮 TA 统筹。"
                "跨频道的用法:先用 list_my_rooms 列出 TA 所在的频道,再用 get_recent_messages"
                "(room_id=目标频道) 调取那个频道的最近讨论,或用 send_message_to_room/invite_to_room"
                "(带 room_id) 操作目标频道。用户问『XX频道最近聊了什么/汇总一下各频道进展』这类问题时,"
                "主动用这些工具去调取,不要说你看不到。"
                "跨频道操作时以用户本人的成员身份为界——不替 TA 访问 TA 不在的频道。"
                "接到要组队执行的目标时的正确链路:先 list_capabilities 看库里有哪些人/AI/技能/知识库,"
                "拆解任务后用 assemble_team 一键建专班(把成员/AI/技能/任务/定制的任务RULE一并带上);"
                "库里没有的资源**不要编造**,组班结果里会提示缺口——把缺口如实转告用户,"
                "建议 TA 到管理后台补充后再完善专班。"
            )
        return (
            "【你的身份：本频道专属 AI】你正在某个频道里服务。你的记忆、知识、可派单的人、"
            "可用的技能都**只限于这个频道**——只看本频道的对话与资料,派单只派给本频道成员。"
            "你和全局助理一样聪明(能拆任务/建专班/跑工作流),但原料只取本频道。"
            "**不要**去读或操作别的频道;用户要跨频道统筹时,引导 TA 到右侧「私人会话」里找你。"
        )

    def _skill_addendum(
        self,
        room_id: str,
        sender: str,
        query: str = "",
        gctx: Optional[Dict[str, Any]] = None,
        extra_scopes: Optional[List[str]] = None,
        is_dm: bool = True,
    ) -> str:
        """拼出本轮注入主 AI 的 system addendum = 人设 + 技能 + 知识库检索片段(RAG)。

        多来源、各自兜异常、互不拖累：
          - **人设/技能**：控制室 state event(全局) + cosmac DB(群/个人) + 绑定的智能体。
          - **知识库(RAG)**：按 query 检索本群/个人知识库 top-K 片段(cosmac DB)。
        **绝不能因为它出问题就让主 AI 不回话**——任一来源异常都只是少注入、不抛出。
        """
        try:
            # 平台级硬约束（全局规则）——放最前、优先级最高
            rules_text = self._global_rules_text()
            # 本群上下文（人设/绑定技能/模型/本专班任务RULE）——_handle_event 已读则复用
            if gctx is None:
                gctx = self._group_context(room_id)
            persona = gctx.get("persona", "")
            # 本专班任务 RULE（档3）：项目主AI 的缰绳，紧随平台规则之后、优先级高于人设。
            task_rule = (gctx.get("task_rule") or "").strip()
            task_rule_text = (
                "【本专班任务约束（RULE，须严格遵守；你只围绕本项目分配与审核，不越界）】：\n"
                + task_rule
            ) if task_rule else ""
            # 频道管理「规则」tab 的规则(此前从未注入——负责人报的缺陷,现在真正生效)
            ch_rules = (gctx.get("channel_rules") or "").strip()
            ch_rules_text = (
                "【本频道规则（RULE，须严格遵守）】：\n" + ch_rules
            ) if ch_rules else ""
            # 频道规则文档(Markdown):整篇工作规范,每轮全文注入(负责人需求,类 CLAUDE.md)
            rule_doc = (gctx.get("rule_doc") or "").strip()
            rule_doc_text = (
                "【本频道规则文档（完整工作规范，须严格遵守）】：\n" + rule_doc
            ) if rule_doc else ""
            agent_slugs = gctx.get("skill_slugs", [])
            items = (
                # 全局技能按发起人的「可用范围」过滤(资源级权限:等级/模板/仅管理员);
                # 群绑定的(_agent_skill_items)不过滤——绑定是管理员显式配置,即授权。
                self._global_skill_items(for_user=sender)
                + self._db_skill_items(room_id, sender)
                # 从创作者商城**买断**的技能(P4):付过钱就永久随发起人生效,与自建技能同权重
                + self._acquired_cskill_items(sender)
                + self._agent_skill_items(agent_slugs)
            )
            # 按 slug 去重（全局已注入的技能若又被 Agent 绑定，不重复注入；保留首次出现）
            seen: Set[str] = set()
            deduped: List[Dict[str, Any]] = []
            for it in items:
                slug = str(it.get("slug") or "")
                if slug and slug in seen:
                    continue
                seen.add(slug)
                deduped.append(it)
            skills_text = render_skills(deduped)
            # 用户个人偏好（About me / Outputs）：跟人走（发起人），放在人设之后、优先级最低。
            user_pref_text = self._user_profile_text(sender)
            mem_text = self._memory_context(room_id, sender)
            # 频道绑定的知识库来源(组班"调进频道"的个人/资料库频道/平台库)一并纳入 RAG
            # 频道知识隔离(负责人硬性要求:频道 AI 只能用本频道资源,个人库/平台资料
            # 曾在频道里被检索出来、把平台内部信息说给了频道成员——线上实报的泄漏):
            # 频道模式(非 DM)只查 本频道库+管理员显式绑定进频道的知识源;私聊(全局助理)不变。
            kb_text = self._kb_context(
                room_id, sender, query, extra_scopes,
                bound_sources=gctx.get("kb_scopes"),
                channel_isolated=not is_dm,
            )
            wf_text = self._preset_workflows_text(gctx.get("workflow_slugs") or [])
            # 当前时间：让模型能把"3天后/下周五"这类相对期限换算成绝对日期（拆任务设 due 用）。
            # 按产品时区(默认北京时间,见 tzutil)——服务器是 UTC,直接 localtime 会差 8 小时。
            # 附未来两周「日期↔星期」对照表:模型心算未来日期的星期常错(线上写过
            # "7月18日(周五)"实际是周六),涉及日期的文案让它照抄对照表,不许自己推。
            from cosmac.tzutil import now_text as _tz_now
            from cosmac.tzutil import weekday_table

            now_text = (
                "【当前时间】" + _tz_now()
                + "\n未来两周星期对照(写日期时照抄,别自己推算):" + weekday_table()
            )
            # 频道资源纪律(负责人硬性要求):**每个频道恒定注入**——不管建房时有没有写 RULE,
            # 存量频道一并覆盖。私聊(全局助理)不注入(那是用户自己的空间,可用个人库)。
            channel_policy = "" if is_dm else (
                "【频道资源纪律(必须遵守)】你是本频道的专属 AI:只使用本频道的人设、技能、"
                "智能体、规则与知识库(含管理员显式绑定进本频道的知识源)作答;"
                "不得引用、透露或依赖频道之外的任何内容——包括其他频道的信息、"
                "成员的个人知识库、平台内部资料与项目开发信息。"
                "若本频道资料不足以回答,如实说明并建议把所需资料上传到本频道知识库。"
            )
            # 规则自检闸(负责人实报:规则文档写了「严禁对用户身份做评价」,AI 照样给出
            # 成员表现评价,被追问才承认违规)。规则块在长 prompt 中段,模型遵守率低;
            # 把「发送前逐条自检」放在 addendum **末尾**——距离生成最近、遵守率最高。
            # 只在本频道真的配了规则时注入,不给无规则频道白加 token。
            has_rules = bool(ch_rules or rule_doc or task_rule)
            self_check = (
                "【发送前自检(硬性流程,每次回答都要做)】本频道配有规则(见上文"
                "【本频道规则】/【本频道规则文档】/【本专班任务约束】)。写完回答后、"
                "发送前,逐条核对是否违反其中任何一条:\n"
                "· 有违反 → 删掉违规部分再发;\n"
                "· 用户的请求本身会导致违规(如让你做规则禁止的事) → 拒绝该部分,"
                "并指出依据哪条规则;\n"
                "· 规则与用户要求冲突时,**规则优先**。"
            ) if has_rules else ""
            # 时间 → 交互准则(内置基线) → 平台规则 → 频道纪律 → 任务RULE → 人设 → 用户偏好 → 长期记忆 → 技能 → 知识库 → 预置工作流 → 规则自检(收尾)
            return "\n\n".join(
                p for p in (
                    now_text, _INTERACTION_POLICY,
                    rules_text, channel_policy, ch_rules_text, rule_doc_text,
                    task_rule_text, persona, user_pref_text,
                    mem_text, skills_text, kb_text, wf_text, self_check,
                ) if p
            )
        except Exception as e:
            # 兜住**最终组装**：脏数据绝不能让这条消息收不到回复（docstring 的承诺）
            logger.debug("组装 addendum 失败（忽略，按无附加继续）：%s", e)
            return ""

    def _user_profile_text(self, sender: str) -> str:
        """读发起人的「个人偏好画像」(About me / Outputs)，渲染成注入块。

        跟人走（不分群）：主 AI 据此知道"现在面对的是谁、TA 希望怎样的回答"。
        失败/没设过/已停用都返回空串——绝不能因为它出问题就让主 AI 不回话。
        """
        try:
            from cosmac.db import session_scope
            from cosmac.db.user_profile_repo import get_profile, render_profile_text

            with session_scope() as s:
                return render_profile_text(get_profile(s, sender))
        except Exception:
            logger.debug("读取用户个人偏好失败（忽略，按无附加继续）", exc_info=True)
            return ""

    def _global_rules_text(self) -> str:
        """读控制室「全局规则」state event，渲染成「必须遵守」块（失败返回空）。"""
        try:
            ctrl = self.client.resolve_alias(self.config.control_room_alias)
            if not ctrl:
                return ""
            ev = self.client.get_state_event(ctrl, RULES_EVENT_TYPE) or {}
            texts = [
                str(r.get("text") or "").strip()
                for r in (ev.get("rules") or [])
                if isinstance(r, dict) and r.get("enabled", True)
            ]
            texts = [t for t in texts if t]
            if not texts:
                return ""
            lines = ["【必须严格遵守的平台规则，优先级高于其它指示】："]
            lines += [f"{i}. {t}" for i, t in enumerate(texts, 1)]
            return "\n".join(lines)
        except Exception as e:
            logger.debug("读取全局规则失败（忽略）：%s", e)
            return ""

    def _kb_retrieve(
        self, room_id: str, sender: str, query: str,
        room_k: int = 3, user_k: int = 2,
        extra_scopes: Optional[List[str]] = None,
        bound_sources: Optional[List[str]] = None,
        include_user_scope: bool = True,
    ) -> List[Tuple[str, str, float]]:
        """检索本群+个人+**频道绑定的知识库**，返回 [(标题, 片段, 相关度), ...] 降序。无命中/出错返回 []。

        这是 RAG 的共享底座：自动注入(`_kb_context`)和 search_knowledge 工具(`_kb_search_for_tool`)
        都走它，避免两份检索逻辑漂移。**不在此做门控**——调用方各自负责(自动注入走 knowledge
        闸；工具走 execute 的 gate_check)。cosmac.db 懒导入 + 全程兜异常，绝不抛出。
        必须在 session 内就把 title/text 取成普通值——session 关了再读惰性的 ch.doc 会报错。

        ``extra_scopes``：额外要搜的 room 作用域（P2 文档答疑：中枢 AI 带上的「当前工作区」
        Space id），让全局 DM 也能基于某工作区的文档(按 Space 存)作答。
        ``bound_sources``：**频道绑定的知识库来源**(channel_config.kbScopes)——组班时把平台/个人/
        某资料库频道的知识库"调进"这个频道,对全频道成员生效。每项前缀化标识:
          · ``user:<uid>`` = 某人的个人库(如发起人个人库对全班开放)
          · ``room:<rid>`` = 某频道的知识库(把资料库频道挂给专班)
          · ``platform``    = 平台级共享知识库(SCOPE_GLOBAL 固定作用域,后台维护)
        """
        q = (query or "").strip()
        if not q:
            return []
        # 三类作用域各自去重收集:room / user / global(平台)
        room_scopes: List[str] = [room_id] if room_id else []
        for x in (extra_scopes or []):
            if x and x not in room_scopes:
                room_scopes.append(x)
        # include_user_scope=False(频道隔离):发起人个人库**不再默认带入**——此前个人库在
        # 任何频道都被检索,把用户自己存的平台/项目资料泄进了频道对话(负责人线上实报)。
        # 显式绑定(bound_sources 的 user:xxx)不受影响——那是管理员对本频道的明确授权。
        user_scopes: List[str] = [sender] if (sender and include_user_scope) else []
        global_scopes: List[str] = []
        # 解析频道绑定的知识库来源,分派到对应作用域
        for src in (bound_sources or []):
            src = str(src).strip()
            if src == "platform":
                if self._PLATFORM_KB_SCOPE not in global_scopes:
                    global_scopes.append(self._PLATFORM_KB_SCOPE)
            elif src.startswith("user:"):
                uid = src[5:].strip()
                # 越权防护(#4)：kbScopes 存在房间 state event、任意有写 state 权限的成员都能改，
                # 绝不能凭它裸读**别人**的个人库。只认「属主本人是当前频道成员」的绑定——这正是
                # 合法语义（发起人把自己的个人库开放给自己所在的专班）；攻击者在自建房绑
                # user:@受害者、受害者非本房成员 → is_joined_member 返回 False → 拒绝，不泄漏。
                # uid==sender（自己的库）直接放行，省一次网络查询。
                if uid and uid not in user_scopes and (
                    uid == sender or self.client.is_joined_member(room_id, uid)
                ):
                    user_scopes.append(uid)
            elif src.startswith("room:"):
                rid = src[5:].strip()
                # 越权防护(#4)：把某频道库「调进」本频道，只对**当前发言人自己有权访问**(是该频道
                # 成员)的资料库频道生效——否则任意成员可绑 room:!别人的频道，跨频道读走其知识库。
                if rid and rid not in room_scopes and self.client.is_joined_member(rid, sender):
                    room_scopes.append(rid)
        try:
            from cosmac.ai.embeddings import get_embedder
            from cosmac.db import session_scope
            from cosmac.db.kb import search
            from cosmac.db.models import SCOPE_GLOBAL, SCOPE_ROOM, SCOPE_USER

            # 查询向量只算一次（embed_one 可能要打网络），各库共用，省请求
            emb = get_embedder()
            qvec = emb.embed_one(q)
            with session_scope() as s:
                hits: List[Tuple[Any, float]] = []
                for rid in room_scopes:
                    hits += search(s, query=q, scope=SCOPE_ROOM, scope_id=rid, k=room_k,
                                   min_score=0.05, embedder=emb, qvec=qvec)
                for uid in user_scopes:
                    hits += search(s, query=q, scope=SCOPE_USER, scope_id=uid, k=user_k,
                                   min_score=0.05, embedder=emb, qvec=qvec)
                for gid in global_scopes:
                    hits += search(s, query=q, scope=SCOPE_GLOBAL, scope_id=gid, k=room_k,
                                   min_score=0.05, embedder=emb, qvec=qvec)
                hits.sort(key=lambda t: t[1], reverse=True)
                # session 内就物化成普通值，避免关闭后惰性加载 ch.doc.title 报错
                return [((ch.doc.title or "").strip(), ch.text, score) for ch, score in hits]
        except Exception as e:
            logger.debug("知识库检索失败（忽略）：%s", e)
            return []

    def _memory_context(self, room_id: str, sender: str) -> str:
        """长期记忆注入：读本群滚动摘要，渲染成「长期记忆」块塞进 system（无则空串）。

        长期记忆是付费功能（memory 门控）：低于门槛的用户不注入长期记忆。
        cosmac.db 懒导入 + 全程兜异常：没装 DB / 无摘要 / 出错都返回空串，绝不阻断回复。
        """
        if not self._gate_allows(sender, "memory"):
            return ""
        try:
            from cosmac.db import session_scope
            from cosmac.db.memory_repo import get_summary
            from cosmac.db.models import SCOPE_ROOM

            with session_scope() as s:
                summary = get_summary(s, SCOPE_ROOM, room_id)
        except Exception as e:
            logger.debug("读取长期记忆失败（忽略）：%s", e)
            return ""
        if not summary:
            return ""
        return "【长期记忆（你与本群/该用户之前对话沉淀的要点，供连贯作答参考）】：\n" + summary

    def _kb_context(
        self, room_id: str, sender: str, query: str,
        extra_scopes: Optional[List[str]] = None,
        bound_sources: Optional[List[str]] = None,
        channel_isolated: bool = False,
    ) -> str:
        """RAG 自动注入：按 query 检索知识库 top-K 片段，渲染成「参考资料」块塞进 system。

        每轮都跑、给一条 baseline；模型若想深挖再自行调 search_knowledge 工具。
        min_score 过滤太不相关的（哈希兜底嵌入下尤其重要，避免硬塞无关内容）。
        ``extra_scopes``：额外搜的 room 作用域（文档答疑传当前工作区 Space id）。
        ``bound_sources``：频道绑定的知识库来源(组班时"调进频道"的个人/资料库频道/平台库)。
        """
        if not (query or "").strip():
            return ""
        # 知识库门控：低于门槛的用户在普通对话里也不享受 RAG 注入（与知识命令同一道闸）
        if not self._gate_allows(sender, "knowledge"):
            return ""
        # 图文教程是全平台一份、付费可读：付费用户的每轮对话(含中枢 AI)自动把全局图文纳入 RAG，
        # 让 AI 能基于平台图文内容作答；非付费用户不注入（与查看图文同一道 doc_read 闸）。
        scopes = list(extra_scopes or [])
        # 频道隔离模式:全局图文教程也不带(它是平台内容,不属于本频道)——负责人要求频道
        # AI 只用本频道资源;私聊/全局助理照旧纳入。
        if not channel_isolated and self._doc_can_read(sender) \
                and self._GLOBAL_DOC_ROOM not in scopes:
            scopes.append(self._GLOBAL_DOC_ROOM)
        hits = self._kb_retrieve(
            room_id, sender, query, extra_scopes=scopes, bound_sources=bound_sources,
            include_user_scope=not channel_isolated,
        )
        if not hits:
            return ""
        lines = ["参考以下「知识库」资料作答（与问题相关，未必完整）："]
        for i, (title, text, _score) in enumerate(hits[:4], 1):
            lines.append(f"[{i}] 《{title}》 {text}")
        return "\n".join(lines)

    def _kb_search_for_tool(self, query: str, ctx: ToolContext) -> str:
        """search_knowledge 工具的执行体（注入 Toolbox.kb_search）。

        门控由 execute() 的 gate_check 统一裁决(search_knowledge→knowledge)，这里不重复判。
        给模型读的结构化结果：命中按相关度降序列出，无命中明确说"没找到"（提示别编造）。
        """
        # 与自动注入同一隔离口径:频道里用 search_knowledge 工具也只查本频道(+绑定源)
        gctx = self._group_context(ctx.room_id) if not ctx.is_dm else {}
        hits = self._kb_retrieve(
            ctx.room_id, ctx.sender, query, room_k=4, user_k=3,
            bound_sources=gctx.get("kb_scopes") if gctx else None,
            include_user_scope=ctx.is_dm,
        )
        if not hits:
            return "知识库里没找到与此相关的资料（可以换个关键词再试，或据常识作答并说明未引用知识库）。"
        lines = ["知识库检索结果（相关度降序）："]
        for i, (title, text, score) in enumerate(hits[:5], 1):
            lines.append(f"[{i}] 《{title}》(相关度 {score:.2f}) {text}")
        return "\n".join(lines)

    def _group_context(self, room_id: str) -> Dict[str, Any]:
        """读本群频道配置**一次**，得出 {persona, skill_slugs, model}。

        优先级：① 绑定了全局智能体(persona.agentSlug) → 用它的人设 + 绑定技能 + 模型覆盖；
                ② 否则用本群自定义人设(persona.prompt)。都没有 → 空。
        失败一律返回空 dict（绝不阻断回复）。
        20 秒缓存(评审 #3):点名判定跑在每条群消息上,不能每条都读 room state;
        收到本房 channel_config state 事件时精确失效(改绑定零延迟,见 _handle_event)。
        """
        cached = self._gctx_cache.get(room_id)
        if cached and time.monotonic() - cached[1] < 20:
            return dict(cached[0])
        out = self._group_context_uncached(room_id)
        self._gctx_cache[room_id] = (out, time.monotonic())
        if len(self._gctx_cache) > 5000:
            self._gctx_cache.clear()
        return dict(out)

    def _group_context_uncached(self, room_id: str) -> Dict[str, Any]:
        """_group_context 的真实读取体(缓存壳见上)。"""
        out: Dict[str, Any] = {
            "persona": "", "skill_slugs": [], "model": "", "task_rule": "",
            "worker_slugs": [], "workflow_slugs": [], "kb_scopes": [],
            "channel_rules": "", "rule_doc": "",
        }
        try:
            cfg = self.client.get_state_event(room_id, CHANNEL_CONFIG_EVENT_TYPE) or {}
            # 本专班任务 RULE（档3）：项目主AI 的缰绳，最高优先级注入（见 _skill_addendum）。
            # 先于 persona 取出，确保两条返回路径都带上它。
            out["task_rule"] = str(cfg.get("taskRule") or "").strip()
            # 频道规则文档(Markdown,负责人需求):整篇工作规范,每轮全文注入。4000 字截断
            # 兜底(前端同上限)——全文注入有 token 成本,别让超长文档挤占对话空间。
            out["rule_doc"] = str(cfg.get("ruleDoc") or "").strip()[:4000]
            # 频道管理「规则」tab 配的规则(负责人报的隐藏缺陷:此前**从未注入**给 AI,配了等于摆设)。
            # 结构 [{label, desc}],拼成一段文本随 addendum 注入。
            rule_items = [
                (str(r.get("label") or "").strip(), str(r.get("desc") or "").strip())
                for r in (cfg.get("rules") or []) if isinstance(r, dict)
            ]
            rule_lines = [
                (f"{lb}:{ds}" if ds else lb) for lb, ds in rule_items if lb or ds
            ]
            out["channel_rules"] = "\n".join(
                f"{i}. {t}" for i, t in enumerate(rule_lines, 1))
            # 本专班绑定的协作 Agent slug（档3b @名路由用）；一并取出避免重复读 state。
            out["worker_slugs"] = [str(s) for s in (cfg.get("agentSlugs") or []) if s]
            # 本频道绑定的知识库来源（组班时"调进频道"的个人/资料库频道/平台库）。
            out["kb_scopes"] = [str(s) for s in (cfg.get("kbScopes") or []) if s]
            # 入驻模板预置的默认工作流 slug（P2）：让本工作区的 AI 知道有哪些现成工作流可跑。
            out["workflow_slugs"] = [str(s) for s in (cfg.get("workflowSlugs") or []) if s]
            persona = cfg.get("persona") or {}
            slug = (persona.get("agentSlug") or "").strip()
            if slug:
                agent = self._find_global_agent(slug)
                if agent:
                    name = agent.get("name") or slug
                    sp = (agent.get("system_prompt") or "").strip()
                    out["persona"] = (
                        f"本群已绑定智能体「{name}」，请始终以下述人设与职责回应：\n{sp}"
                    )
                    out["skill_slugs"] = [str(s) for s in (agent.get("skill_slugs") or [])]
                    # 智能体绑定的工作流：与入驻模板预置的合并（模板给工作区打底，
                    # 智能体带自己的专属能力），按 slug 去重、保持顺序。
                    # **绑定即授权**——这是管理员在后台显式配的，所以下面 _tool_ctx 会
                    # 把它们作为「已授权工作流」传给工具层，在本频道免受 workflow_run 门控。
                    for wf in (agent.get("workflow_slugs") or []):
                        sw = str(wf).strip()
                        if sw and sw not in out["workflow_slugs"]:
                            out["workflow_slugs"].append(sw)
                    out["model"] = (agent.get("model") or "").strip()
                    return out
            # 退回自定义人设（自由文本）。引导按模板写入时，persona 里还可带 model/skill_slugs
            # （不绑全局智能体也能让模板的模型/技能在本群生效——房间级配置用户自己有权限写）。
            free = (persona.get("prompt") or "").strip()
            if free:
                out["persona"] = f"本群人设：\n{free}"
            m = (persona.get("model") or "").strip()
            if m:
                out["model"] = m
            ss = persona.get("skill_slugs")
            if isinstance(ss, list):
                out["skill_slugs"] = [str(s) for s in ss if s]
            return out
        except Exception as e:
            logger.debug("读取本群上下文失败（忽略）：%s", e)
            return out

    @staticmethod
    def _starts_with_word(body: str, token: str) -> bool:
        """body 是否以 token「成词」开头:token 后必须是串尾或非字母数字。

        防日常词乱入(评审 #4):worker 名「设计」——「设计 你好」命中,
        「设计稿我下午传给你」不命中(后跟汉字/字母=只是词头,不是点名)。
        """
        if not token or not body.startswith(token):
            return False
        rest = body[len(token):]
        return (not rest) or (not rest[0].isalnum())

    def _match_routable_agent(
        self, worker_slugs: List[str], sender: str, body: str,
        mentioned_ids: Optional[List[str]] = None, for_trigger: bool = True,
    ) -> Optional[Tuple[str, Dict[str, Any], str]]:
        """在「可路由智能体」集合里找这条消息点名的那一个——**单一事实源**。

        触发判定(_agent_mention_hit,要不要应答)与人设路由(_apply_worker_routing,
        以谁应答)都消费本函数。此前两处各写一套候选枚举+命中规则,且路由拿到的是
        剥过句首 @ 的文本,导致「触发了却路由不到、落回主 AI 人设」(评审 #1);
        统一后两边输入相同,且 trigger 规则 ⊆ route 规则,触发命中必能路由到。

        候选(按优先级):worker_slugs(本频道绑定,由调用方传入——触发侧读 room state,
        路由侧直接用 gctx 里现成的,免重复读) → 发起人自建 → 发起人商城已获取。
        命中规则:
          - m.mentions / 正文里出现傀儡 MXID(@guduu-ai-<slug>:域):最明确,直接命中;
          - @slug / @名字(正文任意位置):显式点名,命中;
          - slug/名字 成词开头(_starts_with_word):仅 worker/自建;已获取不认开头
            (名字常是「文案」这类日常词,商城指引本来就是"@ 它");
          - for_trigger=False(路由模式)额外放宽 worker/自建:正文**包含** slug/名字
            也算——消息已因 @ 主 AI 被应答,保留档3b"提到谁就以谁的人设答"的旧行为。
        返回 (slug, agent定义, 'global'|'mine');未命中/异常返回 None(绝不阻断)。
        """
        body = (body or "").strip()
        low = body.lower()
        # ⓪ 方案B 最短路径:m.mentions 里直接 @ 了某个傀儡账号(现代客户端 pill,
        # 正文里可能只有显示名——这正是评审 #1 的 mention pill 场景)
        try:
            for uid in (mentioned_ids or []):
                slug = self._worker_slug_of(uid)
                if not slug:
                    continue
                agent = self._find_global_agent(slug)
                if agent:
                    return slug, agent, "global"
        except Exception:
            logger.debug("按 m.mentions 匹配傀儡失败(忽略)", exc_info=True)
        if not body:
            return None

        def _hit(slug: str, name: str, kind: str) -> bool:
            """单个候选的命中判定(kind: worker/mine/acquired)。"""
            if self._worker_user_id(slug) in body:
                return True  # 正文里出现傀儡 MXID(@pill 的 fallback 形态)
            slug_l = (slug or "").strip().lower()
            name = (name or "").strip()
            if slug_l and f"@{slug_l}" in low:
                return True
            if name and f"@{name}" in body:
                return True
            if kind != "acquired":  # worker/自建:成词开头也算点名
                if self._starts_with_word(low, slug_l) or self._starts_with_word(body, name):
                    return True
                if not for_trigger:  # 路由模式再放宽:正文包含(档3b 旧行为)
                    if (slug_l and slug_l in low) or (name and name in body):
                        return True
            return False

        try:
            # ① 本频道绑定的专班 worker(非专班频道列表为空、开销即止)
            for slug in (worker_slugs or []):
                agent = self._find_global_agent(str(slug))
                if agent and _hit(str(slug), str(agent.get("name") or ""), "worker"):
                    return str(slug), agent, "global"
            # ② 发起人自建智能体(工坊承诺"任意频道点它的名字就由它应答")
            for m in self._my_agent_items(sender):
                if _hit(str(m.get("slug") or ""), str(m.get("name") or ""), "mine"):
                    return str(m.get("slug") or ""), m, "mine"
            # ③ 发起人商城「已获取」的全局智能体(商城指引"在频道里 @它")——只认 @点名。
            # ⚠️ access 必须**每次实时校验**(评审 #2):获取那一刻的校验只保证当时解锁,
            # 会员到期回落/管理员事后收紧 access 后,已获取记录仍在——不查就成了
            # "获取一次终身可用",付费门控被架空。(worker=管理员显式绑进频道的授权、
            # mine=用户自己的,均不查,与资源权限既有口径一致。)
            for slug in self._acquired_agent_slugs(sender):
                agent = self._find_global_agent(slug)
                if not agent or not self._resource_visible(agent, sender):
                    continue
                if _hit(slug, str(agent.get("name") or ""), "acquired"):
                    return slug, agent, "global"
            # ④ 发起人商城已获取的**创作者 Agent**（P2 创作者商城）——同"已获取"口径只认
            # @点名；在售/定义有效性已在 _acquired_cagent_items 内实时校验（下架即失效）。
            for it in self._acquired_cagent_items(sender):
                if _hit(str(it.get("slug") or ""), str(it.get("name") or ""), "acquired"):
                    return str(it.get("slug") or ""), it, "cagent"
        except Exception:
            logger.debug("可路由智能体匹配失败(忽略)", exc_info=True)
        return None

    def _apply_worker_routing(
        self, text: str, gctx: Dict[str, Any], sender: str = "",
        mentioned_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """档3b：消息点名了某个可路由智能体(专班 worker/自建/已获取)时,改用它的
        人设/技能/模型回这条;**任务 RULE 不变**。没点名 → 原样返回 lead 的 gctx。

        ⚠️ text 必须传**原始正文**(与触发判定同一输入,别传 _strip_mention 后的——
        句首 @ 被剥会让「@文案 …」路由不到,评审 #1);匹配逻辑见 _match_routable_agent。
        """
        match = self._match_routable_agent(
            gctx.get("worker_slugs") or [], sender, text,
            mentioned_ids=mentioned_ids, for_trigger=False,
        )
        if not match:
            return gctx
        slug, agent, kind = match
        name = str(agent.get("name") or "").strip()
        out = dict(gctx)
        label = (
            "用户自建智能体" if kind == "mine"
            else "创作者智能体" if kind == "cagent"
            else "协作智能体"
        )
        out["persona"] = (
            f"本条由你以{label}「{name or slug}」的身份回应，"
            f"请按下述人设履职：\n{(agent.get('system_prompt') or '').strip()}"
        )
        out["skill_slugs"] = [str(s) for s in (agent.get("skill_slugs") or [])]
        out["model"] = (agent.get("model") or "").strip()
        if kind == "global":
            # 方案B:回复以该 AI 同事的傀儡账号身份发(账号建不了则留空=主 AI 兜底);
            # 自建智能体是用户私有的,不建全局傀儡(评审 #10:同名 slug 会跨用户共享)。
            out["as_user"] = self._ensure_worker_account(slug)
        elif kind == "cagent":
            # 创作者商城 Agent（P2）：把按次计费三要素带给回复路径（前拦 + 成功后分账）。
            # 不建傀儡（listing 是跨用户共享的引用，建全局傀儡会与全局 slug 空间打架）。
            out["cagent_listing"] = int(agent.get("_listing_id") or 0)
            out["cagent_price"] = int(agent.get("_price") or 0)
            out["cagent_creator"] = str(agent.get("_creator") or "")
        return out

    def _agent_for_model(self, model: str) -> Agent:
        """按「本群模型覆盖」拿一个 Agent：没覆盖或与当前一致 → 用 self.agent；
        否则用**同 provider、换 model**构建一个并缓存（人设走 addendum、不在此设）。
        构建失败回退 self.agent，绝不阻断回复。"""
        model = (model or "").strip()
        provider, applied_model, applied_sys, _ = self._applied_sig
        if not model or model == applied_model:
            return self.agent
        cached = self._model_agents.get(model)
        if cached is not None:
            return cached
        try:
            secure: Dict[str, Any] = {}
            try:
                from cosmac.node_settings import runtime_ai

                secure = runtime_ai()
            except Exception:
                logger.debug("按群模型读取节点 AI 密钥失败，回退 env", exc_info=True)
            llm = build_provider(
                provider, api_key=str(secure.get("api_key") or ""), model=model,
                system_prompt=applied_sys, base_url=str(secure.get("base_url") or ""),
                allow_env_fallback=(
                    not bool(secure)
                    and not bool(os.environ.get("COSMAC_OEM_KEY", "").strip())
                ),
            )
            ag = Agent(llm=llm, toolbox=self.toolbox, system_prompt=applied_sys)
            self._model_agents[model] = ag
            logger.info("按群模型构建 Agent: provider=%s model=%s", provider, model)
            return ag
        except Exception:
            logger.exception("按群模型 %s 构建失败，回退默认模型", model)
            return self.agent

    def _run_agent_engine(
        self, agent, user_text, tool_ctx, extra_system, history, model_override="",
        stream_cb=None,
    ):
        """按 COSMAC_AGENT_ENGINE 选执行引擎跑一条消息，返回 (回复文本, 模型输出 token 数)。

        模型输出量用于 Token 经济计费（见 cosmac/wallet.py）：SDK 引擎读 ResultMessage.usage、
        legacy 读 Agent 累计的 last_usage_tokens。取不到=0（不计费）。回退/异常路径也带 0。

        - claude_sdk:Claude Agent SDK(Claude Code 同款 harness),env 可插拔(P1,
          见 cosmac/ai/engine.py 模块注释)。模型端点由 COSMAC_SDK_* 决定——测试用
          DeepSeek 的 Anthropic 兼容端点,生产可一键切 Claude。
        - 默认(开关没开):legacy 现有循环,行为与部署零变化。
        SDK 引擎**任何失败都回退 legacy**:它是增强,绝不能把 AI 问答搞挂。
        每次新建引擎实例(无状态轻对象):避免并发线程间 system_prompt 串味。
        """
        from cosmac.ai.engine import ClaudeSdkEngine, sdk_engine_enabled
        # 执行过程可见(Claude Code 式):工具调用滚动展示在一条可编辑的状态消息里。
        reporter = _ProgressReporter(self.client, tool_ctx.room_id)
        if sdk_engine_enabled():
            try:
                # 群级模型联动:群绑定的智能体模型传给 SDK 引擎(与 legacy 的 _agent_for_model 同语义)
                eng = ClaudeSdkEngine(
                    self.toolbox, lambda: agent.system_prompt, model_override=model_override
                )
                reply = eng.run(
                    user_text, tool_ctx, extra_system=extra_system, history=history,
                    progress_cb=reporter, stream_cb=stream_cb,   # 流式:边生成边显示
                )
                reporter.finish()
                return reply, int(getattr(eng, "last_usage_tokens", 0) or 0)
            except Exception as exc:
                logger.exception("Claude SDK 引擎执行失败,本条回退 legacy 引擎")
                # 回退不能是无声的:欠费/CLI 坏了会让引擎一直默默回退,没人发现"高级引擎"
                # 早就没在跑。向控制室发告警(1 小时最多一条),管理员能第一时间看到。
                # 例外:"达到最大轮数"是**可预期的能力边界**(任务太复杂,非故障)——静默回退
                # legacy 即可,别当故障告警惊动管理员(否则一条复杂任务就误报"引擎挂了/余额不足")。
                if "maximum number of turns" not in str(exc).lower():
                    self._alert_engine_fallback(exc)
                # #8：SDK 引擎若**已执行过工具**(reporter.steps 非空 → 建群/邀人/派单等副作用已
                # 落地、teams 等终身配额已扣),绝不能回退 legacy 从头重跑——那会重复建房、重复
                # 派单、配额二次扣。reporter 每轮新建,steps 只反映本次。只有一个工具都没跑
                # (通常首个 LLM 调用就失败;尤其触顶 max_turns 时步骤最多、重跑破坏最大)时，回退
                # 才无副作用。已动过手就停下、如实告知，让用户决定是否接着做。
                if reporter.steps:
                    reporter.finish()
                    # 已产生副作用才停：带上 SDK 已累计的模型输出量结算。
                    return (
                        "⚠️ 我在执行过程中已经做了部分操作，但随后遇到故障。为避免重复建群/"
                        "重复派单，这条先停在这里。请看下已完成的部分，需要我接着把剩下的做完就说一声。"
                    ), int(getattr(eng, "last_usage_tokens", 0) or 0)
        try:
            reply = agent.run(
                user_text, tool_ctx, extra_system=extra_system, history=history,
                progress_cb=reporter,
            )
        finally:
            # legacy 引擎抛异常时也要定格"正在执行"卡片，否则它永久卡在"⏳ 正在执行"（#7 连带）。
            # finish() 自带 event_id/steps 守卫并自兜异常，任何时候调用都安全。
            reporter.finish()
        return reply, int(getattr(agent, "last_usage_tokens", 0) or 0)

    def _alert_engine_fallback(self, exc: Exception) -> None:
        """SDK 引擎回退时向控制室发告警(节流:1 小时最多一条)。

        best-effort:告警本身失败(控制室不在/网络抖动)只记日志,绝不影响用户那条回复。
        常见根因提示直接写进消息,管理员不用翻文档。
        """
        import time as _time
        now = _time.time()
        if now - self._engine_alert_ts < 3600:
            return
        self._engine_alert_ts = now
        try:
            room = self.client.resolve_alias(self.config.control_room_alias)
            if not room:
                return
            self.client.send_text(
                room,
                "⚠️ AI 高级引擎(Claude SDK)执行失败,已自动回退旧引擎,用户无感但请尽快排查。\n"
                f"错误摘要: {type(exc).__name__}: {str(exc)[:180]}\n"
                "常见原因: ① DeepSeek 账户余额不足 ② 服务器 claude CLI/Node 异常 ③ 端点网络不通\n"
                "（注:『达到最大轮数』属任务过复杂的正常边界、非故障，已不在此告警）。\n"
                "排查: journalctl -u guduu-bot | grep 引擎。(本提醒 1 小时内不再重复)",
            )
        except Exception:
            logger.debug("发送引擎回退告警失败(忽略)", exc_info=True)

    def _find_global_agent(self, slug: str) -> Optional[Dict[str, Any]]:
        """按 slug 找一个**启用**的全局智能体（含内置预置库 + 控制室配置）；找不到返回 None。

        走 _global_agent_items（已合并预置+控制室），这样 @预置Agent / 绑定预置Agent 都能解析。
        """
        try:
            for a in self._global_agent_items():
                if a.get("slug") == slug:
                    return a
            return None
        except Exception as e:
            logger.debug("查找全局智能体失败（忽略）：%s", e)
            return None  # 当作没找到

    def _skill_library(self) -> List[Dict[str, Any]]:
        """全部**可绑定**技能(启用的)= 内置预置技能库打底 + 控制室配置覆盖/追加。

        与 _global_skill_items 的区别(关键):
          · _global_skill_items(只读控制室)= **每轮全局注入**的技能,数量受 6000 字符预算约束,
            所以预置技能**不进这里**,免得撑爆上下文;
          · _skill_library(预置 + 控制室)= **供 Agent 绑定解析**的全集——预置技能靠对应预置
            Agent 绑定、被 @/指派时才随该 Agent 激活(_agent_skill_items),平时零注入。
        合并规则同 _global_agent_items:预置打底,控制室**同 slug 覆盖**、新 slug 追加。
        """
        # 20 秒缓存(评审 #3,与 _global_agent_items 同款):绑定解析在应答路径反复调,
        # 此前每次 resolve_alias+get_state_event 两次 HTTP。
        items, ts = self._skills_items_cache
        if time.monotonic() - ts < 20:
            return list(items)
        from cosmac.ai.preset_skills import preset_skills

        merged: Dict[str, Dict[str, Any]] = {s["slug"]: s for s in preset_skills()}
        try:
            ctrl = self.client.resolve_alias(self.config.control_room_alias)
            if ctrl:
                ev = self.client.get_state_event(ctrl, SKILLS_EVENT_TYPE) or {}
                for s in (ev.get("skills") or []):
                    if isinstance(s, dict) and s.get("slug"):
                        merged[str(s["slug"])] = s
        except Exception as e:
            logger.debug("读取控制室技能失败(仅用预置技能库):%s", e)
        items = [s for s in merged.values() if s.get("enabled", True)]
        self._skills_items_cache = (items, time.monotonic())
        return list(items)

    def _agent_skill_items(self, slugs: List[str]) -> List[Dict[str, Any]]:
        """把「智能体绑定的技能 slug」解析成技能字典——从**技能库**(预置+控制室)里 slug 命中的启用项。

        用 _skill_library 而非 _global_skill_items:让预置技能(不进全局注入)也能被 Agent 绑定激活。
        """
        if not slugs:
            return []
        want = set(slugs)
        return [s for s in self._skill_library() if str(s.get("slug")) in want]

    def _global_agent_items(self, for_user: str = "") -> List[Dict[str, Any]]:
        """全局智能体列表（启用的）= **内置预置库打底 + 控制室配置覆盖/追加**。给能力名册/绑群用。

        内置预置 Agent（presets.preset_agents）让零配置租户也有一队"AI 同事"可派/可 @；管理员在
        后台配的同 slug 覆盖预置、新 slug 追加、把 enabled 设 false 可停用某个（含覆盖掉预置的）。
        for_user 非空时按资源「可用范围」(access 字段)过滤——能力名册等"以发起人身份看资源"
        的场景传它;绑群解析等"管理员显式配置"的场景不传(绑定即授权)。
        """
        # 20 秒缓存(评审 #3):本函数在每条群消息的点名判定/路由/名册里被反复调,
        # 此前每次 resolve_alias+get_state_event 两次 HTTP。缓存**未过滤**的合并列表
        # (for_user 过滤便宜、在缓存之上做);TTL 与后台「保存后约 20 秒热生效」同口径。
        items, ts = self._agents_items_cache
        if time.monotonic() - ts >= 20:
            from cosmac.ai.presets import preset_agents

            # 预置打底：slug → item
            merged: Dict[str, Dict[str, Any]] = {a["slug"]: a for a in preset_agents()}
            # 控制室配置覆盖/追加（不论 enabled，先并进来，最后按 enabled 过滤——这样后台可停用预置）
            try:
                ctrl = self.client.resolve_alias(self.config.control_room_alias)
                if ctrl:
                    ev = self.client.get_state_event(ctrl, AGENTS_EVENT_TYPE) or {}
                    for a in (ev.get("agents") or []):
                        if isinstance(a, dict) and a.get("slug"):
                            merged[str(a["slug"])] = a
            except Exception as e:
                logger.debug("读取全局智能体列表失败（仅用预置）：%s", e)
            items = [a for a in merged.values() if a.get("enabled", True)]
            self._agents_items_cache = (items, time.monotonic())
        if for_user:
            return [a for a in items if self._resource_visible(a, for_user)]
        return list(items)

    def _user_template(self, user_id: str) -> str:
        """查某用户注册引导时选的入驻模板 slug(资源「指定模板可用」据此判定)。

        读 cosmac DB(引导完成时 /cosmac/onboarding/select 端点写入);带 5 分钟缓存——
        名册/技能注入每条消息都要判,不能每次打 DB。没选过/无 DB 返回空串。
        """
        now = time.monotonic()
        cached = self._user_template_cache.get(user_id)
        if cached and now - cached[1] < 300:
            return cached[0]
        slug = ""
        try:
            from cosmac.db import session_scope
            from cosmac.db.user_template_repo import get_user_template

            with session_scope() as s:
                slug = get_user_template(s, user_id) or ""
        except Exception:
            logger.debug("读取用户模板失败（忽略）", exc_info=True)
        self._user_template_cache[user_id] = (slug, now)
        if len(self._user_template_cache) > 5000:
            self._user_template_cache.clear()
        return slug

    def _acquired_agent_slugs(self, user_id: str) -> Set[str]:
        """某用户从商城「已获取」的智能体 slug 集合(能力名册标注/排序用)。

        读 cosmac DB(market_repo);带 5 分钟缓存——名册每条消息都可能建,不能每次打 DB。
        获取端点(handle_market_acquire)写入时会主动 pop 本人缓存,做到"获取完下条消息就生效"。
        无 DB/查询失败返回空集(名册只是少了优先标注,绝不阻断)。
        """
        now = time.monotonic()
        cached = self._acquired_cache.get(user_id)
        if cached and now - cached[1] < 300:
            return cached[0]
        slugs: Set[str] = set()
        try:
            from cosmac.db import session_scope
            from cosmac.db.market_repo import acquired_agent_slugs

            with session_scope() as s:
                slugs = acquired_agent_slugs(s, user_id)
        except Exception:
            logger.debug("读取已获取智能体失败（忽略）", exc_info=True)
        self._acquired_cache[user_id] = (slugs, now)
        if len(self._acquired_cache) > 5000:
            self._acquired_cache.clear()
        return slugs

    def _acquired_cskill_items(self, user_id: str) -> List[Dict[str, Any]]:
        """某用户**已买断的创作者技能**（P4），每轮对话注入用。

        每条：获取记录 kind='cskill'、slug=listing id；listing 必须仍在售(on)、创作者的
        user-scope Skill 定义仍存在且启用——下架/删除即失效（已付费不退，但内容归创作者，
        他下架就没了；商城页会标"已下架"）。slug 用 ``cs<listing_id>`` 避免与他人技能撞名。
        5 分钟缓存（注入路径每条消息都走），获取/审核变更时主动失效。
        """
        if not user_id:
            return []
        cached = self._acquired_cskill_cache.get(user_id)
        if cached and time.monotonic() - cached[1] < 300:
            return cached[0]
        items: List[Dict[str, Any]] = []
        try:
            from cosmac.db import listing_repo, session_scope
            from cosmac.db.market_repo import list_acquired
            from cosmac.db.models import SCOPE_USER
            from cosmac.db.repo import get_skill

            with session_scope() as s:
                ids = [
                    slug for kind, slug in list_acquired(s, user_id) if kind == "cskill"
                ]
                for sid in ids:
                    try:
                        listing = listing_repo.get_listing(s, int(sid))
                    except (TypeError, ValueError):
                        continue
                    if listing is None or listing.status != "on":
                        continue
                    src = get_skill(s, SCOPE_USER, listing.creator, listing.agent_slug)
                    if src is None or not src.enabled:
                        continue
                    items.append({
                        "slug": f"cs{listing.id}",
                        "name": listing.name or src.name,
                        "description": listing.description or src.description,
                        "instructions": src.instructions,
                    })
        except Exception:
            logger.debug("读取已买断创作者技能失败（忽略）", exc_info=True)
        self._acquired_cskill_cache[user_id] = (items, time.monotonic())
        if len(self._acquired_cskill_cache) > 5000:
            self._acquired_cskill_cache.clear()
        return items

    def _acquired_cagent_items(self, user_id: str) -> List[Dict[str, Any]]:
        """某用户从商城「已获取」的**创作者 Agent**（P2 创作者商城），点名路由用。

        已获取记录 kind='cagent'、slug=listing id。每条：listing 必须仍在售(on)、
        创作者的 user-scope Agent 定义仍存在且启用——否则跳过(下架/删除即失效)。
        返回项与 _my_agent_items 同构(name/system_prompt/model/skill_slugs)，另带
        路由计费用的 _listing_id/_price/_creator；slug 用 ``c<listing_id>``(全网唯一、
        不与全局/自建 slug 冲突)。5 分钟缓存，获取端点写入时主动失效。
        """
        if not user_id:
            return []
        cached = self._acquired_cagent_cache.get(user_id)
        if cached and time.monotonic() - cached[1] < 300:
            return cached[0]
        items: List[Dict[str, Any]] = []
        try:
            from cosmac.db import listing_repo, session_scope
            from cosmac.db.market_repo import list_acquired
            from cosmac.db.models import SCOPE_USER
            from cosmac.db.repo import get_agent

            with session_scope() as s:
                ids = [
                    slug for kind, slug in list_acquired(s, user_id) if kind == "cagent"
                ]
                for sid in ids:
                    try:
                        listing = listing_repo.get_listing(s, int(sid))
                    except (TypeError, ValueError):
                        continue
                    if listing is None or listing.status != "on":
                        continue
                    # 人设实时读创作者的 user-scope Agent（创作者改人设即全网生效）
                    src = get_agent(s, SCOPE_USER, listing.creator, listing.agent_slug)
                    if src is None or not src.enabled:
                        continue
                    items.append({
                        "slug": f"c{listing.id}",
                        "name": listing.name or src.name,
                        "description": listing.description or src.description,
                        "system_prompt": src.system_prompt,
                        "model": src.model,
                        "skill_slugs": [],  # 创作者的个人技能不跨用户注入（权属隔离）
                        "_listing_id": int(listing.id),
                        "_price": int(listing.price_tokens or 0),
                        "_creator": listing.creator,
                    })
        except Exception:
            logger.debug("读取已获取创作者 Agent 失败（忽略）", exc_info=True)
        self._acquired_cagent_cache[user_id] = (items, time.monotonic())
        if len(self._acquired_cagent_cache) > 5000:
            self._acquired_cagent_cache.clear()
        return items

    # ═══ 方案B:AI 同事傀儡账号(每个协作 Agent 一个独立 Matrix 账号) ═══
    # 命名 @guduu-ai-<slug>:<域>——落在 appservice namespace(@guduu.*)内,注册文件无需改。
    # 傀儡像真成员一样出现在频道成员列表,消息以它自己的名字/头像发,@ 它即由它应答。

    _PUPPET_PREFIX = "guduu-ai-"

    def _worker_user_id(self, slug: str) -> str:
        """协作 Agent slug → 傀儡账号完整 MXID(仅拼名,不保证已注册)。"""
        return f"@{self._PUPPET_PREFIX}{slug}:{self.config.server_name}"

    def _worker_slug_of(self, user_id: str) -> str:
        """反解:MXID 是本产品的 AI 傀儡账号则返回其 agent slug,否则空串。"""
        uid = str(user_id or "")
        prefix = f"@{self._PUPPET_PREFIX}"
        if not uid.startswith(prefix):
            return ""
        return uid[len(prefix):].split(":", 1)[0]

    def _ensure_worker_account(self, slug: str) -> str:
        """确保某协作 Agent 的傀儡账号存在(注册幂等)并设好显示名;返回 MXID,失败空串。

        结果按 slug 缓存(进程生命周期):注册/设名只做一次,失败也缓存空串防止每条
        消息都重试打爆 Synapse——bot 重启后自然重试。
        """
        cached = self._worker_account_cache.get(slug)
        if cached is not None:
            return cached
        uid = ""
        try:
            if self.client.register_appservice_user(f"{self._PUPPET_PREFIX}{slug}"):
                uid = self._worker_user_id(slug)
                agent = self._find_global_agent(slug) or {}
                name = str(agent.get("name") or slug)
                # 显示名失败不阻断(profiles 表缺行的 Synapse bug 见 memory,重启可重试)
                self.client.set_displayname_as(uid, name)
        except Exception:
            logger.exception("确保 AI 同事账号失败 slug=%s", slug)
            uid = ""
        self._worker_account_cache[slug] = uid
        return uid

    def _ensure_worker_in_room(self, room_id: str, slug: str) -> str:
        """把某协作 Agent 的傀儡账号拉进频道(注册→邀请→join,全幂等)。

        assemble_team 建专班时逐个调用,让 AI 同事**真的出现在成员列表里**(方案B);
        应答/交付以傀儡身份发送前也要调(评审 #7:不在房 send_text_as 必 403——
        普通频道 @ 已获取智能体、方案B上线前建的旧专班都属此列)。
        「已在房」按 (room, slug) 缓存,后续调用零 HTTP。
        返回傀儡 MXID;任一步失败返回空串(退回主 AI 身份兜底,不阻断)。
        """
        uid = self._ensure_worker_account(slug)
        if not uid:
            return ""
        if (room_id, slug) in self._worker_in_room_cache:
            return uid
        try:
            self.client.invite_user(room_id, uid)  # 已在房/重复邀请由 join 兜底
        except Exception:
            logger.debug("邀请傀儡 %s 进 %s 失败(继续尝试 join)", uid, room_id, exc_info=True)
        try:
            if self.client.join_room_as(room_id, uid):
                self._worker_in_room_cache.add((room_id, slug))
                if len(self._worker_in_room_cache) > 20000:
                    self._worker_in_room_cache.clear()
                return uid
        except Exception:
            logger.exception("傀儡 %s join %s 失败", uid, room_id)
        return ""

    # ═══ AI 任务自动执行(负责人需求:任务派给 AI 同事后要真的被执行) ═══

    # 一轮自动执行最多跑几个 AI 任务(防模型拆出超长清单把 LLM 额度烧穿;超出的留看板可 @ 手动要)
    _AUTO_EXEC_MAX = 8

    def _auto_execute_agent_tasks(
        self, room_id: str, sender: str, task_ids: List[int], task_rule: str = ""
    ) -> None:
        """assemble_team / update_task 注入的自动执行入口:起后台 daemon 线程逐个执行,不阻塞回复。"""
        def _guarded() -> None:
            # daemon 线程里未捕获的异常只会打到 stderr、且随容器重建丢失——包一层如实记 exception,
            # 否则"执行器一起就崩"这种问题事后完全查不到(负责人实报的正是这类静默失败)。
            try:
                self._run_agent_tasks(room_id, sender, list(task_ids), task_rule)
            except Exception:
                logger.exception("自动执行:后台线程异常终止 room=%s 任务=%s", room_id, task_ids)

        threading.Thread(
            target=_guarded, daemon=True, name="agent-task-runner",
        ).start()

    def _run_agent_tasks(
        self, room_id: str, sender: str, task_ids: List[int], task_rule: str
    ) -> None:
        """按拆解顺序逐个执行「派给 AI 同事」的任务:worker 人设+任务内容 → LLM 产出 →
        发进专班频道 → 回填任务看板(done/进度/result)。

        设计取舍(方案A 单 bot 多人设,够用即止):
        - **纯生成、不带工具**:自动执行只产出交付物文本,不给建群/发消息等工具——防后台
          线程里的自动循环做出不可控操作;要动手的活仍由用户在频道里指挥主 AI。
        - **链式上下文**:把此前任务的产出摘要传给后续任务(如"风险分析"能基于"规则文档"),
          按拆解顺序天然满足常见依赖;失败的跳过、不阻断后面的任务。
        - **失败兜底**:单个任务 LLM 失败 → 看板留 todo + result 记原因 + 频道提示可 @ 重试。
        """
        # 可观测性(负责人实报"AI Agent 执行完任务没更新看板/没发频道",而线上日志随容器重建丢失、
        # 成功路径又多是 debug 级 → 事后无从查):这里起一条 INFO,后台线程崩在开头也留痕。
        logger.info("自动执行:线程启动 room=%s 任务=%s", room_id, task_ids[: self._AUTO_EXEC_MAX])
        done_n = 0
        quota_stopped = False
        prior: List[str] = []  # 已完成任务的产出摘要(喂给后续任务当上下文)
        for tid in task_ids[: self._AUTO_EXEC_MAX]:
            # 配额(评审 #5):每个任务的 LLM 生成计入发起人的当日 AI 对话额度——
            # 否则自动执行成了不计量的 LLM 消费通道(一次组班后台烧 8 次生成)。
            # 先查不扣(成功产出后才 consume,与对话路径"成功才扣"同口径);超额即停,
            # 剩余任务留看板可明日再跑或 @ 对应 AI 手动执行。
            try:
                if self._rate_quota_blocked(sender, "ai_msg_daily", consume=False):
                    quota_stopped = True
                    break
            except Exception:
                logger.debug("自动执行:配额检查失败(放行)", exc_info=True)
            title, goal, slug, reviewer = "", "", "", ""
            try:
                from cosmac.db import session_scope
                from cosmac.db.task_repo import get_task, update_task

                with session_scope() as s:
                    t = get_task(s, tid)
                    if not t or t.executor_kind != "agent" or t.status == "done":
                        continue
                    title, goal, slug = t.title, t.goal, t.executor_ref
                    reviewer = str(t.reviewer_ref or "").strip()
                    update_task(s, tid, status="doing", progress=10)
            except Exception:
                logger.exception("自动执行:读取任务 #%s 失败", tid)
                continue
            # 执行者解析(评审 #10):先查全局库;查不到再查**发起人自建**(模型会把任务派给
            # 名册里"我的·"智能体)——用其真实人设执行,但不建全局傀儡(私有资源,同名 slug
            # 会跨用户共享账号)。两处都没有 → 不执行,留看板并如实提示,绝不拿空人设硬跑。
            agent_def = self._find_global_agent(slug) or {}
            is_global = bool(agent_def)
            if not agent_def:
                try:
                    agent_def = next(
                        (m for m in self._my_agent_items(sender)
                         if str(m.get("slug") or "") == str(slug)), {},
                    )
                except Exception:
                    agent_def = {}
            if not agent_def:
                try:
                    from cosmac.db import session_scope
                    from cosmac.db.task_repo import update_task

                    with session_scope() as s:
                        update_task(
                            s, tid, status="todo", progress=0,
                            result=f"自动执行跳过:执行者「{slug}」不在智能体库(可能已删除/写错)",
                        )
                except Exception:
                    logger.debug("自动执行:未知执行者状态回填失败", exc_info=True)
                try:
                    self.client.send_text(
                        room_id,
                        f"⚠️ 任务#{tid}《{title}》的执行者「{slug}」不在智能体库，已留在看板。"
                        "可到任务看板改派，或让管理员在后台补建该智能体。",
                    )
                except Exception:
                    pass
                continue
            name = str(agent_def.get("name") or slug)
            out = ""
            err = "模型无输出"
            try:
                sp = str(agent_def.get("system_prompt") or "").strip()
                system = (
                    f"你是专班协作智能体「{name}」。你的人设与职责:\n{sp}\n\n"
                    + (f"本专班任务约束(RULE,必须遵守):\n{task_rule}\n\n" if task_rule else "")
                    + "现在独立完成下述任务,直接输出**可交付的最终成果**"
                    "(不要寒暄、不要提问;信息不足时按合理假设完成并在文末注明假设)。"
                )
                user = f"专班目标:{goal}\n你的任务:{title}"
                if prior:
                    user += "\n\n此前同事已交付的成果(供你衔接,不要重复):\n" + "\n---\n".join(prior[-3:])
                llm = self._agent_for_model(str(agent_def.get("model") or "").strip()).llm
                out = (llm.complete([
                    Message(role="system", content=system),
                    Message(role="user", content=user),
                ]) or "").strip()
            except Exception as e:
                logger.exception("自动执行:任务 #%s LLM 生成失败", tid)
                out = ""
                err = str(e)[:120]
            if out:
                try:
                    # 方案B:产出以该 AI 同事的傀儡账号身份发(时间线显示它的名字/头像);
                    # 傀儡不可用(账号建不了/不在房)退回主 AI 代打署名,绝不丢产出。
                    # 自建智能体(非 global)不建傀儡(评审 #10),直接主 AI 署名。
                    puppet = ""
                    if is_global:
                        try:
                            puppet = self._ensure_worker_in_room(room_id, slug)
                        except Exception:
                            puppet = ""
                    sent = None
                    if puppet:
                        sent = self.client.send_text_as(
                            room_id, f"📦 交付任务#{tid}《{title}》：\n\n{out}", puppet
                        )
                    if not sent:
                        self.client.send_text(
                            room_id, f"🤖【{name}】交付任务#{tid}《{title}》：\n\n{out}"
                        )
                except Exception:
                    logger.debug("自动执行:产出发频道失败(看板照常回填)", exc_info=True)
                try:
                    from cosmac.db import session_scope
                    from cosmac.db.task_repo import update_task

                    with session_scope() as s:
                        # AI 产出是“已交付”而不是“已验收”。新任务必须进入
                        # review/pending，保留给指定真人的最后质量闸；无审核人的
                        # 存量旧任务仍按旧口径 done，避免上线后把旧数据卡死。
                        next_status = "review" if reviewer else "done"
                        next_review = "pending" if reviewer else "none"
                        update_task(
                            s,
                            tid,
                            status=next_status,
                            progress=100,
                            result=out[:2000],
                            review_status=next_review,
                        )
                    done_n += 1
                    prior.append(f"《{title}》({name}):{out[:500]}")
                    if reviewer:
                        try:
                            self.client.send_text(
                                room_id,
                                f"{reviewer} 任务#{tid}《{title}》已由 AI 交付，"
                                "请在任务看板审核通过或打回。",
                            )
                        except Exception:
                            logger.debug(
                                "自动执行:通知审核人失败 reviewer=%s",
                                reviewer,
                                exc_info=True,
                            )
                except Exception:
                    logger.exception("自动执行:任务 #%s 回填看板失败", tid)
                # 产出成功才消费配额(评审 #5,与对话路径同口径:失败不扣)
                try:
                    self._rate_quota_blocked(sender, "ai_msg_daily", consume=True)
                except Exception:
                    logger.debug("自动执行:配额消费失败(忽略)", exc_info=True)
            else:
                # 失败:看板退回 todo 并记录原因,频道提示可手动重试——绝不能假装完成
                try:
                    from cosmac.db import session_scope
                    from cosmac.db.task_repo import update_task

                    with session_scope() as s:
                        update_task(
                            s, tid, status="todo", progress=0,
                            result=f"自动执行失败({err}),可在频道 @{name} 重试",
                        )
                except Exception:
                    logger.debug("自动执行:失败状态回填失败", exc_info=True)
                try:
                    self.client.send_text(
                        room_id,
                        f"⚠️ 任务#{tid}《{title}》自动执行失败，已退回待办。"
                        f"可稍后在频道里 @{name} 让它重做，或改派他人。",
                    )
                except Exception:
                    pass
        # 收尾汇报:让频道里的人知道这轮自动执行的整体结果(全部失败也如实说)
        try:
            total = min(len(task_ids), self._AUTO_EXEC_MAX)
            skipped = len(task_ids) - total
            tail = f"(还有 {skipped} 个超出单轮上限,留在看板可 @ 对应 AI 手动执行)" if skipped > 0 else ""
            if quota_stopped:
                tail += "⚠️ 发起人当日 AI 额度已用完,剩余任务留在看板——明日自动恢复额度后可 @ 对应 AI 执行,或升级会员提升额度。"
            self.client.send_text(
                room_id,
                f"📋 AI 同事本轮任务交付完毕：成功 {done_n}/{total}，"
                f"已进入真人审核流程，看板已更新{tail}。",
            )
        except Exception:
            pass

    def _resource_visible(self, item: Dict[str, Any], user_id: str) -> bool:
        """按资源的「可用范围」(access 字段)判定 user_id 是否可用该技能/智能体。

        access 取值(后台「可用范围」下拉写入):
          ''/缺省/'public' = 所有人;'paid'/'creator' = 该会员等级及以上;
          'admin' = 仅平台管理员;'tpl:slugA,slugB' = 仅选了这些入驻模板的用户。
        平台管理员永远可用(与功能门控同一原则);判定出错按可见处理(保守方向=不误伤功能)。
        """
        try:
            access = str(item.get("access") or "").strip()
            if not access or access == "public":
                return True
            if self._is_platform_admin(user_id):
                return True
            if access == "admin":
                return False
            if access.startswith("tpl:"):
                slugs = {t.strip() for t in access[4:].split(",") if t.strip()}
                return self._user_template(user_id) in slugs
            if is_valid_tier(access):
                return tier_level(self.members.get_tier(user_id)) >= tier_level(access)
            return True  # 未知取值当所有人(容错:后台写坏一个值不至于全员失效)
        except Exception:
            logger.debug("资源可用范围判定失败（按可见处理）", exc_info=True)
            return True

    def _people_items(self) -> List[Dict[str, Any]]:
        """读控制室「人员能力名册」(cosmac.people)，返回启用的人员画像列表（失败空）。

        admin 后台登记，每条形如 {user_id,name,role,expertise,note,enabled}。主AI 拆任务时
        据此知道"这条活找谁"。同 _global_skill_items 套路：解析不到/出错都返回空、绝不阻断。
        """
        try:
            ctrl = self.client.resolve_alias(self.config.control_room_alias)
            if not ctrl:
                return []
            ev = self.client.get_state_event(ctrl, PEOPLE_EVENT_TYPE) or {}
            return [
                p for p in (ev.get("people") or [])
                if isinstance(p, dict) and p.get("enabled", True)
            ]
        except Exception as e:
            logger.debug("读取人员能力名册失败（忽略）：%s", e)
            return []

    def _personal_people_items(self, owner: str) -> List[Dict[str, Any]]:
        """读某用户（owner）在前台维护的个人协作人名册（cosmac DB，启用的）。失败/无 DB 返回空。"""
        if not owner:
            return []
        try:
            from cosmac.db import session_scope
            from cosmac.db.person_repo import list_people, to_dict

            with session_scope() as s:
                return [to_dict(p) for p in list_people(s, owner) if p.enabled]
        except Exception:
            logger.debug("读取个人协作人名册失败（忽略）", exc_info=True)
            return []

    _STORAGE_TTL = 60  # 存储用量缓存(秒)——媒体统计要打 Synapse admin API,别每次都查

    @staticmethod
    def _blen(text: Optional[str]) -> int:
        """字符串的 **UTF-8 字节数**（L1：存储配额口径是字节，中文每字 3 字节）。None→0。"""
        return len((text or "").encode("utf-8"))

    @staticmethod
    def _sql_byte_len(session: Any):
        """返回按方言取「文本字节长度」的 SQL 函数（L1）：
        PostgreSQL(生产) 用 octet_length 精确到字节；SQLite(本地开发) 无此函数，回退 length(字符数)
        ——本地不硬核算存储配额，够用。这样生产端媒体字节 + 知识库/自建内容字节口径一致(不再字符/字节混加)。
        """
        from sqlalchemy import func
        name = getattr(getattr(session, "bind", None), "dialect", None)
        name = getattr(name, "name", "") if name is not None else ""
        return func.octet_length if name == "postgresql" else func.length

    def _room_creator(self, room_id: str) -> str:
        """读频道创建者(m.room.create 的 sender)。创建者不变→永久缓存。读不到返回 ""。

        配额口径「频道资源计入建者额度」(负责人拍板)用它:频道知识库文档算给建者。
        """
        cache = getattr(self, "_room_creator_cache", None)
        if cache is None:
            cache = self._room_creator_cache = {}
        if room_id in cache:
            return cache[room_id]
        creator = ""
        try:
            for ev in (self.client.admin_room_state(room_id) or []):
                if ev.get("type") == "m.room.create":
                    creator = str(ev.get("sender") or "")
                    break
        except Exception:
            logger.debug("读频道创建者失败 %s", room_id, exc_info=True)
        cache[room_id] = creator
        return creator

    def _rooms_created_by(self, user_id: str) -> List[str]:
        """列出某用户**创建的频道**(排除工作区/控制室)。带 60s 缓存(用户建群不频繁)。

        「频道资源计入建者额度」的枚举基础:统计/拦截时把这些频道的知识库算进建者名下。
        经管理员 API 拿用户加入的房→逐房看 create.sender==本人。没配 ADMIN_TOKEN→空。
        """
        now = time.time()
        cache = getattr(self, "_created_rooms_cache", None)
        if cache is None:
            cache = self._created_rooms_cache = {}
        hit = cache.get(user_id)
        if hit and now - hit[0] < 60:
            return hit[1]
        out: List[str] = []
        try:
            rooms = self.client.admin_user_joined_rooms(user_id)
            for rid in (rooms or []):
                state = self.client.admin_room_state(rid)
                if not state:
                    continue
                is_creator = is_space = is_ctrl = False
                for ev in state:
                    et = ev.get("type")
                    if et == "m.room.create":
                        is_creator = str(ev.get("sender") or "") == user_id
                        if (ev.get("content") or {}).get("type") == "m.space":
                            is_space = True
                    elif et == "m.room.name":
                        if "控制室" in str((ev.get("content") or {}).get("name") or ""):
                            is_ctrl = True
                if is_creator and not is_space and not is_ctrl:
                    out.append(rid)
        except Exception:
            logger.debug("枚举用户建的频道失败 %s", user_id, exc_info=True)
        cache[user_id] = (now, out)
        return out

    def _kb_docs_used(self, session: Any, user_id: str) -> int:
        """本人 kb_docs 配额已用 = 个人库文档 + **本人建的频道库**文档(负责人口径)。"""
        from cosmac.db import kb
        from cosmac.db.models import SCOPE_ROOM, SCOPE_USER

        used = len(kb.list_docs(session, scope=SCOPE_USER, scope_id=user_id))
        for rid in self._rooms_created_by(user_id):
            used += len(kb.list_docs(session, scope=SCOPE_ROOM, scope_id=rid))
        return used

    def _storage_bytes(self, user_id: str) -> int:
        """本人已用存储字节 = Synapse 媒体(上传的附件/图片/视频) + 个人知识库文本。带 60s 缓存。

        归属口径(负责人定的"每个账号自己的存储空间"):只算能明确归属到个人的——媒体按上传者、
        知识库按 SCOPE_USER。聊天文字与共享频道库不计(共享资源无法归属个人,文字体积可忽略)。
        媒体统计查不到(未配 ADMIN_TOKEN/网络错)按 0 处理——宁可少算,不误拦用户。
        """
        now = time.time()
        cache = getattr(self, "_storage_cache", None)
        if cache is None:
            cache = self._storage_cache = {}
        hit = cache.get(user_id)
        if hit and now - hit[0] < self._STORAGE_TTL:
            return hit[1]
        total = 0
        try:
            from cosmac import registration
            media = registration.get_user_media_bytes(self.config.homeserver_url, user_id)
            total += int(media or 0)
        except Exception:
            logger.debug("查媒体用量失败(按0)", exc_info=True)
        try:
            from sqlalchemy import func, select
            from cosmac.db import session_scope
            from cosmac.db.models import SCOPE_USER, KnowledgeChunk
            with session_scope() as s:
                blen = self._sql_byte_len(s)  # L1：按字节算，与媒体字节口径一致
                n = s.execute(
                    select(func.coalesce(func.sum(blen(KnowledgeChunk.text)), 0))
                    .where(KnowledgeChunk.scope == SCOPE_USER,
                           KnowledgeChunk.scope_id == user_id)
                ).scalar()
                total += int(n or 0)
                # 频道资源计入建者额度(负责人口径):本人建的频道库文本也算本人存储。
                from cosmac.db.models import SCOPE_ROOM
                created = self._rooms_created_by(user_id)
                if created:
                    n2 = s.execute(
                        select(func.coalesce(func.sum(blen(KnowledgeChunk.text)), 0))
                        .where(KnowledgeChunk.scope == SCOPE_ROOM,
                               KnowledgeChunk.scope_id.in_(created))
                    ).scalar()
                    total += int(n2 or 0)
        except Exception:
            logger.debug("查知识库用量失败(按0)", exc_info=True)
        try:
            from sqlalchemy import func, select
            from cosmac.db import session_scope
            from cosmac.db.models import SCOPE_USER, Agent as DbAgent, Skill as DbSkill
            with session_scope() as s:
                blen = self._sql_byte_len(s)
                n1 = s.execute(
                    select(func.coalesce(func.sum(
                        blen(DbSkill.name) + blen(DbSkill.description)
                        + blen(DbSkill.instructions)), 0))
                    .where(DbSkill.scope == SCOPE_USER, DbSkill.scope_id == user_id)
                ).scalar()
                n2 = s.execute(
                    select(func.coalesce(func.sum(
                        blen(DbAgent.name) + blen(DbAgent.description)
                        + blen(DbAgent.system_prompt)), 0))
                    .where(DbAgent.scope == SCOPE_USER, DbAgent.scope_id == user_id)
                ).scalar()
                total += int(n1 or 0) + int(n2 or 0)
        except Exception:
            logger.debug("查自建智能体/技能用量失败(按0)", exc_info=True)
        cache[user_id] = (now, total)
        if len(cache) > 2000:
            cache.clear()  # 粗暴防膨胀:缓存本就 60s 失效,清了顶多多查几次
        return total

    def handle_storage_check(
        self, access_token: str, add_bytes: str
    ) -> Tuple[int, Dict[str, Any]]:
        """上传前的存储空间预检:现用量+本次字节 是否超本人等级上限。需登录。

        附件上传是客户端直连 Synapse 媒体 API,bot 不在链路上——这是**软管控**(前端配合调用);
        「我的额度」照实展示用量,超限者由前端拒绝继续上传。limit=-1 不限;管理员永不受限。
        """
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        try:
            add = max(0, int(add_bytes or 0))
        except (TypeError, ValueError):
            add = 0
        limit_mb = self._quota_limit(user_id, "storage_mb")
        used = self._storage_bytes(user_id)
        used_mb = round(used / 1048576, 1)
        if limit_mb < 0:
            return 200, {"ok": True, "used_mb": used_mb, "limit_mb": -1}
        ok = (used + add) <= limit_mb * 1048576
        out: Dict[str, Any] = {"ok": ok, "used_mb": used_mb, "limit_mb": limit_mb}
        if not ok:
            out["error"] = (
                f"存储空间不足：已用 {used_mb}MB / 上限 {limit_mb}MB。"
                "删除一些附件/知识库文档，或升级会员扩容。"
            )
        return 200, out

    _DEACT_TTL = 120  # 停用账号集缓存有效期（秒）——名册每轮都可能重建，别每次都翻 Synapse 用户列表

    def _deactivated_user_ids(self) -> Optional[set]:
        """本服务器已停用账号的 user_id 集合（带 120s 缓存）。查不到回 None → 调用方不过滤(fail-open)。

        能力名册过滤停用账号用。缓存避免每次建名册都分页拉一遍全量用户；查询失败时**不刷新缓存**、
        回 None，让调用方退回"不过滤"（宁可偶尔多列一个停用者，也不因抖动清空名册）。
        """
        now = time.time()
        cached = getattr(self, "_deact_cache", None)
        if cached is not None and now - cached[0] < self._DEACT_TTL:
            return cached[1]
        from cosmac import registration
        ids = registration.list_deactivated_user_ids(self.config.homeserver_url)
        if ids is not None:
            self._deact_cache = (now, ids)  # 只在成功时更新缓存
        return ids

    def _list_capabilities_for_tool(self, ctx: ToolContext) -> str:
        """能力名册（list_capabilities 工具的执行体，注入 Toolbox.list_capabilities）。

        聚合四类"可调配资源"+各自能力备注，给主AI 拆任务/分配时匹配执行者用：
          真人(cosmac.people) / AI Agent(全局) / Skill(全局) / 知识库(本群+个人文档标题)。
        全程兜异常，任一来源失败只是少列一类、绝不抛出。
        """
        lines: List[str] = []
        # — 真人 —（下达者的个人协作人名册 + admin 全局名册，合并去重）
        # 优先级=**个人记录优先**:与「我的协作人」endpoint(handle_people_list_mine)同口径——
        # 用户给联系人写的能力备注覆盖平台预设。此前这里是"全局优先",导致界面显示个人备注、
        # AI 派单却用平台值,两边不一致(负责人报的"两个入口数据不同步"其中一半根因)。
        try:
            people = list(self._personal_people_items(ctx.sender))
            seen_uid = {str(p.get("user_id") or "") for p in people}
            for p in self._people_items():
                if str(p.get("user_id") or "") not in seen_uid:
                    people.append(p)
        except Exception:
            people = []
        # 【防脏数据】只保留**本服务器**(server_name)域名下的真人——名册里若混进了外域/本地开发
        # 残留的假账号(如 @xulei:guduu.local),AI 会照单派单,任务落到一个不存在的用户身上、谁也
        # 看不到(线上实测踩过)。本产品单 homeserver,真实账号一律 @x:<server_name>,据此过滤。
        try:
            dom = ":" + str(self.config.server_name or "").strip()
            if len(dom) > 1:
                people = [
                    p for p in people
                    if str(p.get("user_id") or "").strip().endswith(dom)
                ]
        except Exception:
            logger.debug("按 server_name 过滤名册失败,退回全量", exc_info=True)
        # 【过滤停用账号】主 AI 不该把任务派给已停用的人——TA 登不进来、任务落下去没人干。
        # 停用集查不到(None)时不过滤(fail-open),别因一次查询抖动把名册清空。
        try:
            deact = self._deactivated_user_ids()
            if deact:
                people = [
                    p for p in people
                    if str(p.get("user_id") or "").strip() not in deact
                ]
        except Exception:
            logger.debug("按停用状态过滤名册失败,退回全量", exc_info=True)
        # 【过滤休假/不可用】admin 在「人员能力」页把某人标记 unavailable(休假/长期不在)——同样别派给他，
        # 否则任务落到不干活的人头上一直挂着、阻塞其他协作者(负责人反馈的场景)。
        try:
            people = [p for p in people if not p.get("unavailable")]
        except Exception:
            logger.debug("按可用状态过滤名册失败,退回全量", exc_info=True)
        # 频道模式(在频道里@AI，非私聊):名册的"真人"只保留**本频道成员**——频道分身只调本群的人。
        # 全局模式(右侧私人会话)不过滤,给全局名册。
        if not ctx.is_dm and ctx.room_id and people:
            try:
                member_ids = {
                    str(m.get("user_id") or "")
                    for m in (self.client.get_members(ctx.room_id) or [])
                }
                if member_ids:
                    people = [p for p in people if str(p.get("user_id") or "") in member_ids]
            except Exception:
                logger.debug("按频道成员过滤名册失败,退回全量", exc_info=True)
        if people:
            lines.append("— 真人（可派单给 TA）—")
            for p in people[:50]:
                uid = str(p.get("user_id") or "").strip()
                name = str(p.get("name") or "").strip()
                meta = " · ".join(
                    x for x in [
                        f"角色:{p.get('role')}" if p.get("role") else "",
                        f"擅长:{p.get('expertise')}" if p.get("expertise") else "",
                        str(p.get("note") or "").strip(),
                    ] if x
                )
                head = uid + (f"（{name}）" if name else "")
                lines.append(f"{head} {meta}".rstrip())
        # — AI Agent —（按发起人的「可用范围」过滤:名册里看不到=主AI 不会派给 TA 用）
        try:
            agents = self._global_agent_items(for_user=ctx.sender)
        except Exception:
            agents = []
        # 本人自建智能体排最前(用户自己训的"私人 AI 同事",优先被派);同 slug 覆盖全局。
        # 名字加「我的·」前缀,让用户与主 AI 一眼分清自建与平台预置。
        mine_slugs: Set[str] = set()
        try:
            mine = [
                dict(m, name=f"我的·{m.get('name') or m['slug']}")
                for m in self._my_agent_items(ctx.sender)
            ]
            if mine:
                mine_slugs = {m["slug"] for m in mine}
                agents = mine + [a for a in agents if str(a.get("slug")) not in mine_slugs]
        except Exception:
            logger.debug("合并个人智能体进名册失败(忽略)", exc_info=True)
        # 商城「已获取」的 AI 同事:排到其余全局项前面(自建仍最前),渲染时标 ★——
        # 让主 AI 知道"这些是用户亲手挑的",同等条件优先派给它们(负责人定的商城闭环)。
        acquired: Set[str] = set()
        try:
            acquired = self._acquired_agent_slugs(ctx.sender)
            if acquired:
                keep = [a for a in agents if str(a.get("slug")) in mine_slugs]
                got = [a for a in agents
                       if str(a.get("slug")) not in mine_slugs
                       and str(a.get("slug")) in acquired]
                rest = [a for a in agents
                        if str(a.get("slug")) not in mine_slugs
                        and str(a.get("slug")) not in acquired]
                agents = keep + got + rest
        except Exception:
            logger.debug("按已获取排序名册失败(忽略)", exc_info=True)
        if agents:
            lines.append("— AI Agent（可绑进专班/派活）—")
            if acquired:
                lines.append("· 标 ★ 的是用户在商城「已获取」的 AI 同事：同等条件优先派给它们")
            # 上限 200(引入 agency 预置后 80+ 个,50 会漏);描述截 60 字防工具输出膨胀——
            # 名册只要"够 AI 选对人",完整人设在被指派/@ 时才注入。
            for a in agents[:200]:
                slug = str(a.get("slug") or "").strip()
                name = str(a.get("name") or "").strip()
                desc = str(a.get("description") or "").strip()
                if len(desc) > 60:
                    desc = desc[:60] + "…"
                skills = a.get("skill_slugs") or []
                seg = ("★" if slug in acquired else "") + f"{slug}" + (f"（{name}）" if name else "")
                if desc:
                    seg += f"：{desc}"
                if skills:
                    seg += f"（技能:{','.join(str(s) for s in skills)}）"
                lines.append(seg)
        # — Skill —（同 Agent:按发起人「可用范围」过滤）
        try:
            skills_items = self._global_skill_items(for_user=ctx.sender)
        except Exception:
            skills_items = []
        if skills_items:
            lines.append("— Skill（可装进专班）—")
            for s in skills_items[:50]:
                slug = str(s.get("slug") or "").strip()
                name = str(s.get("name") or "").strip()
                desc = str(s.get("description") or "").strip()
                seg = slug + (f"（{name}）" if name else "")
                if desc:
                    seg += f"：{desc}"
                lines.append(seg)
        # — 知识库（可"调进"专班,组班时用 assemble_team 的 knowledge 参数绑定）—
        n_user, n_platform = self._kb_bindable_counts(ctx.sender)
        kb_hint: List[str] = []
        if n_user:
            kb_hint.append(f"发起人个人知识库({n_user} 篇)→ 组班传 knowledge=['owner'] 对全班开放")
        if n_platform:
            kb_hint.append(f"平台共享知识库({n_platform} 篇)→ 组班传 knowledge=['platform']")
        kb_hint.append("要把某个资料库频道的知识挂给专班 → knowledge 里给那个频道名")
        try:
            titles = self._kb_doc_titles(ctx.room_id, ctx.sender)
        except Exception:
            titles = []
        if titles or kb_hint:
            lines.append("— 知识库（组班时可「调进」专班,对全频道生效）—")
            for h in kb_hint:
                lines.append("· " + h)
            if titles:
                lines.append("当前可见文档:" + "、".join(f"《{t}》" for t in titles[:20]))
        if not lines:
            return (
                "能力名册暂时是空的：管理员可在后台「人员能力」页登记成员；"
                "Agent/技能/知识库也还没有可用项。"
            )
        return (
            "【可调配资源名册（拆任务/分配时据此选谁来干）】\n" + "\n".join(lines)
        )

    def _kb_bindable_counts(self, sender: str) -> Tuple[int, int]:
        """返回(发起人个人库文档数, 平台共享库文档数)——给能力名册提示"有哪些库可绑进专班"。失败(0,0)。"""
        try:
            from cosmac.db import session_scope
            from cosmac.db.kb import list_docs
            from cosmac.db.models import SCOPE_GLOBAL, SCOPE_USER

            with session_scope() as s:
                n_user = len(list_docs(s, scope=SCOPE_USER, scope_id=sender))
                n_plat = len(list_docs(s, scope=SCOPE_GLOBAL, scope_id=self._PLATFORM_KB_SCOPE))
            return n_user, n_plat
        except Exception:
            return 0, 0

    def _kb_doc_titles(self, room_id: str, sender: str) -> List[str]:
        """列出本群 + 个人知识库的文档标题（给能力名册展示"有哪些库可用"）。失败空。"""
        try:
            from cosmac.db import session_scope
            from cosmac.db.kb import list_docs
            from cosmac.db.models import SCOPE_ROOM, SCOPE_USER

            out: List[str] = []
            with session_scope() as s:
                for d in list_docs(s, scope=SCOPE_ROOM, scope_id=room_id):
                    out.append((d.title or "").strip() or "(无标题)")
                for d in list_docs(s, scope=SCOPE_USER, scope_id=sender):
                    out.append((d.title or "").strip() or "(无标题)")
            return out
        except Exception:
            return []

    def _global_skill_items(self, for_user: str = "") -> List[Dict[str, Any]]:
        """读控制室「全局技能」= **每轮对话注入 system** 的技能(失败返回空)。

        for_user 非空时按「可用范围」(access)过滤——注入对话/能力名册等"以发起人身份用资源"
        的场景传它;资源存在性校验(known_skills)、绑定解析等配置场景不传(全量)。

        ⚠️ **只返回 inject!='agent' 的**:控制室里标记「随 AI 同事激活」(inject='agent')的技能
        (含后台覆盖的预置技能)不每轮全局注入,只在被绑定的 Agent 激活时进(见 _skill_library)——
        否则一堆方法论每轮全塞会撑爆 6000 字符预算。缺省/'global'=全局注入(维持历史行为)。
        """
        try:
            ctrl = self.client.resolve_alias(self.config.control_room_alias)
            if not ctrl:
                return []
            ev = self.client.get_state_event(ctrl, SKILLS_EVENT_TYPE) or {}
            skills = ev.get("skills") or []
            out = [
                s for s in skills
                if isinstance(s, dict) and s.get("enabled", True)
                and str(s.get("inject") or "global") != "agent"
            ]
            if for_user:
                out = [s for s in out if self._resource_visible(s, for_user)]
            return out
        except Exception as e:
            logger.debug("读取全局技能失败（忽略）：%s", e)
            return []

    def _db_skill_items(self, room_id: str, sender: str) -> List[Dict[str, Any]]:
        """从 cosmac DB 读本群/个人启用的技能（聊天命令建的），转成字典列表。

        cosmac.db 懒导入 + 全程兜异常：服务器没装 SQLAlchemy/读失败就返回空。
        """
        try:
            from cosmac.db import session_scope
            from cosmac.db.service import effective_skills

            with session_scope() as s:
                return [
                    {
                        "slug": k.slug,
                        "name": k.name,
                        "description": k.description,
                        "instructions": k.instructions,
                    }
                    for k in effective_skills(s, room_id=room_id, user_id=sender)
                ]
        except Exception as e:
            logger.debug("读取 DB 技能失败（忽略）：%s", e)
            return []

    # —— 控制室成员对齐：把已撤销的管理员降权 + 踢出（浏览器做不到，bot 用 100 权限做）——

    def _reconcile_control_members(
        self, room_id: str, content: Dict[str, Any]
    ) -> None:
        """按「期望管理员集」对齐控制室成员：移除不再是管理员、却仍有写权限的人。

        安全约束（务必守住，否则可能误踢）：
          - **只在确实是控制室时动手**：room_id 必须等于别名解析出的控制室，否则有人
            往任意房间塞这个事件就能借 bot 之手踢人。解析不到/对不上 → 直接不动。
          - **绝不动所有者和 bot 自己**：只移除 power < 100 的成员（owner/bot=100 跳过）。
          - 只“降权 + 踢出”不在期望集里的成员；其余一律不碰。任何异常都不抛、只记日志。
          - 降权/踢出**检查结果**：失败的明确报 error（被撤销者仍有写权限是安全问题），
            绝不无条件报成功；power≥100 的遗留成员 bot 无权移除，单独 warning。
        """
        desired = set(content.get("admins") or [])
        try:
            # 控制室校验：必须是别名解析出的那个房间
            ctrl = self.client.resolve_alias(self.config.control_room_alias)
        except Exception:
            logger.exception("对齐控制室成员：解析控制室别名失败，跳过")
            return
        if not ctrl or ctrl != room_id:
            logger.debug("对齐控制室成员：%s 非控制室，忽略", room_id)
            return

        try:
            pl = self.client.get_state_event(room_id, "m.room.power_levels", "") or {}
        except Exception:
            logger.exception("对齐控制室成员：读 power_levels 失败，跳过")
            return

        bot = self.config.bot_user_id
        users: Dict[str, Any] = dict(pl.get("users") or {})

        # #1 防御：power≥100 且不在期望集的成员——bot(=100) 在 Matrix 里**无法**降权/踢出
        # 同级或更高的人（历史遗留 bug 曾把管理员设成 100 才会出现）。无法自动修，明确告警，
        # 提示需要重建控制室；绝不把他们当 owner 静默跳过。
        stuck = [
            uid
            for uid, lvl in users.items()
            if uid != bot
            and isinstance(lvl, int)
            and lvl >= 100
            and uid not in desired
        ]
        if stuck:
            logger.warning(
                "控制室对齐：成员 %s 权限≥100 且已非管理员，bot 无权移除——"
                "该控制室需重建（早期 bug 把管理员设成了 100）。",
                stuck,
            )

        # 待移除：有显式写权限(50≤power<100) 且不在期望管理员集里的成员。
        # #3：下界 lvl>=50 对齐注释意图——只清理"仍能写控制室配置(≥50)"的旧管理员；power 0-49 的
        # 无写权限、不构成安全风险，不误踢(bot 自身移除人时是回落 users_default、不会显式设 0-49)。
        to_remove = [
            uid
            for uid, lvl in users.items()
            if uid != bot
            and isinstance(lvl, int)
            and 50 <= lvl < 100
            and uid not in desired
        ]
        # 待补齐：期望集里的**新管理员**（在控制室 power<50 或根本不在）。
        # 为什么必须 bot 做"添加"：浏览器里的操作者自己只有 power=50，而发 m.room.power_levels
        # 事件默认要 100——前端"尽力提权"必然静默失败。此前对齐只做移除不做添加，新设的
        # 管理员永远拿不到控制室写权限（QA 实测：新管理员接管频道 403 → 频道技能保存失败）。
        # 判定用 isinstance（与 to_remove 同风格）：power 值畸形(非 int)时按"需要补权"重写为
        # 50 自愈，绝不因 int() 抛异常把整个事务打进重试循环。
        to_add = [
            uid
            for uid in desired
            if isinstance(uid, str) and uid and uid != bot
            and not (isinstance(users.get(uid), int) and users[uid] >= 50)
        ]
        if not to_remove and not to_add:
            return

        # ① 一次性写回 power_levels：移除的降权（回落 users_default=0）+ 新增的提到 50。
        #    #2：检查写入结果——失败说明权限没对齐（被撤销者仍能写/新管理员仍写不了），必须报错。
        new_users = {u: lv for u, lv in users.items() if u not in to_remove}
        for uid in to_add:
            new_users[uid] = 50
        new_pl = {**pl, "users": new_users}
        if not self.client.set_power_levels(room_id, new_pl):
            logger.error(
                "控制室对齐：power_levels 写入失败（移除 %s / 新增 %s 均未生效）",
                to_remove, to_add,
            )
        elif to_add:
            logger.info("控制室对齐：已给新管理员授权 power=50：%s", to_add)
        # ①b 新管理员若还不在控制室，补一张邀请（已在房的会被 Synapse 拒绝，忽略即可；
        #    即便不接受邀请，_is_platform_admin 只看 power_levels，授权已生效）。
        for uid in to_add:
            try:
                if not self.client.is_joined_member(room_id, uid):
                    self.client.invite_user(room_id, uid)
            except Exception:
                logger.debug("控制室对齐：邀请 %s 失败（忽略）", uid, exc_info=True)
        if not to_remove:
            return
        # ② 踢出控制室——逐个检查结果，**只对真正踢成功的报成功**，失败的明确报错
        removed, failed = [], []
        for uid in to_remove:
            if self.client.kick(room_id, uid, "已撤销服务器管理员，移出控制室"):
                removed.append(uid)
            else:
                failed.append(uid)
        if removed:
            logger.info("控制室对齐：已降权并移除非管理员 %s", removed)
        if failed:
            logger.error(
                "控制室对齐：移除失败（权限不足或对方≥bot 权限），仍是控制室成员：%s",
                failed,
            )

    # —— 运行时 AI 配置：管理后台写控制室 state event，bot 读并应用 ——

    def _read_overrides(self) -> Dict[str, Any]:
        """从控制室读取 AI 配置覆盖。带 20s 缓存。

        关键安全语义（修掉"失效开放"）：
          - 读成功且有配置 → 用新配置并缓存；
          - 读成功但控制室没有配置(别名 404 / state 404) → 覆盖确实为空（属正常，
            全工具启用），缓存空；
          - 读失败(403 / 网络错 / 5xx 等) → **保留上次成功的缓存**，绝不因一次抖动
            把管理员设的工具限制/人设清空（client 的 resolve_alias/get_state_event
            现在对这类失败会抛异常，正好走 except 分支）。

        别名每轮都重新解析：控制室被删/重建/重指向后能跟上新 room_id（不再永久缓存）。
        """
        now = time.monotonic()
        if now - self._cfg_cache_ts < 20:
            return self._cfg_cache
        try:
            # 别名→room_id：每轮重解析；404 返回 None（控制室还没建），其它失败抛异常
            room = self.client.resolve_alias(self.config.control_room_alias)
            self._control_room = room  # 仅记录当前解析结果，不再当永久缓存
            overrides: Dict[str, Any] = {}
            if room:
                ev = self.client.get_state_event(room, AI_CONFIG_EVENT_TYPE)
                if isinstance(ev, dict):
                    # 控制室只保存人设和工具开关。provider/model/API key 全部由
                    # “系统设置”中的节点加密数据库负责，历史字段也明确忽略。
                    for k in ("system_prompt", "enabled_tools"):
                        if k in ev:
                            overrides[k] = ev[k]
            # 读成功（含"控制室/配置不存在"这种正常的空）→ 更新缓存
            self._cfg_cache = overrides
            self._cfg_cache_ts = now
            return overrides
        except Exception:  # 读失败：保留上次成功配置，绝不失效开放
            logger.exception("读取运行时 AI 配置失败，沿用上次成功配置")
            self._cfg_cache_ts = now  # 20s 退避，避免每条消息都猛打故障中的服务器
            return self._cfg_cache

    def _apply_runtime_config(self) -> None:
        """把控制室下发的配置应用到 llm/agent/toolbox（按需热重建，幂等）。

        控制室只下发人设/工具开关；provider/model/API key 统一来自节点系统设置。
        非 OEM 本地开发仍可使用启动环境变量，官方 OEM 节点绝不回退旧 .env。
        """
        ov = self._read_overrides()
        secure: Dict[str, Any] = {}
        try:
            from cosmac.node_settings import runtime_ai

            secure = runtime_ai()
        except Exception:
            logger.debug("节点 AI 设置暂不可读，回退启动配置", exc_info=True)
        oem_node = bool(os.environ.get("COSMAC_OEM_KEY", "").strip())
        # provider/model 与 API key 必须来自同一份节点设置。
        provider = secure.get("provider") or ("echo" if oem_node else self.config.llm_provider)
        model = secure.get("model") or ("" if oem_node else self.config.llm_model)
        system_prompt = ov.get("system_prompt") or self.config.system_prompt
        api_key = str(secure.get("api_key") or "")
        base_url = str(secure.get("base_url") or "")
        # 签名只放 key 的哈希前缀，既能在管理员换 key 后触发热重建，又绝不把明文留在内存日志。
        key_sig = hashlib.sha256(api_key.encode()).hexdigest()[:12] if api_key else ""
        secure_sig = (key_sig + "|" + base_url) if (key_sig or base_url) else ""
        sig = (provider, model, system_prompt, secure_sig)
        if sig != self._applied_sig:
            try:
                # API key 来自 node_settings 解密结果；为空时 provider 工厂兼容回退 env。
                self.llm = build_provider(
                    provider, api_key=api_key, model=model,
                    system_prompt=system_prompt, base_url=base_url,
                    allow_env_fallback=not bool(secure) and not oem_node,
                )
                self.agent = Agent(
                    llm=self.llm, toolbox=self.toolbox, system_prompt=system_prompt
                )
                self._applied_sig = sig
                self._model_agents.clear()  # provider/人设变了，按群模型缓存作废
                logger.info(
                    "已应用运行时 AI 配置: provider=%s model=%s 人设已更新",
                    provider, model or "默认",
                )
            except Exception:
                logger.exception("应用运行时 AI 配置失败，沿用当前模型")
        # 工具开关：enabled_tools 是字符串列表 → 只启用这些；缺省/非法 = 全开
        enabled = ov.get("enabled_tools")
        self.toolbox.set_enabled(
            set(enabled) if isinstance(enabled, list) else None
        )

    # —— @ 提及识别：只有被 @ 才响应 ——

    def _bot_localpart(self) -> str:
        """从完整用户 id（如 @guduu:example.invalid）取出 localpart（guduu）。"""
        return self.config.bot_user_id.split(":", 1)[0].lstrip("@")

    def _mention_tokens(self) -> List[str]:
        """所有"算作在叫主 AI"的开头词（大小写不敏感比较）。

        这样用户不用跟 Element 的 @ 弹窗较劲——消息开头直接打 'GuDuu OS' 即可。
        """
        lp = self._bot_localpart()
        return [
            self.config.bot_user_id,        # 例如 @guduu:example.invalid（@pill）
            f"@{lp}",                        # @guduu
            self.config.bot_displayname,     # GuDuu OS
            "GuDuu OS",
            "@GuDuu OS",
            "GuDuu OS",                        # 直接打名字开头就算叫它
        ]

    def _agent_mention_hit(
        self, room_id: str, sender: str, body: str,
        mentioned_ids: Optional[List[str]] = None,
    ) -> bool:
        """群聊补充触发:这条消息是否**点名**了一个可路由的智能体(要不要应答)。

        薄封装:候选枚举与命中规则全在 _match_routable_agent(与人设路由共享同一份
        逻辑,评审 #1 的"触发了却路由不到"由此断根)。worker 列表在这里读 room state
        (路由侧复用 gctx 里现成的,不重读)。异常返回 False=退回"要 @ 主 AI 才应答"。
        """
        try:
            workers = self._group_context(room_id).get("worker_slugs") or []
            return self._match_routable_agent(
                workers, sender, body, mentioned_ids=mentioned_ids, for_trigger=True,
            ) is not None
        except Exception:
            logger.debug("智能体点名判定失败(退回仅 @ 主AI 触发)", exc_info=True)
            return False

    def _is_bot_mentioned(self, content: Dict[str, Any]) -> bool:
        """判断这条消息是否在叫主 AI（被 @ 或以它的名字开头）。"""
        # 1) 现代客户端：标准 m.mentions.user_ids 字段（最可靠）
        mentions = content.get("m.mentions") or {}
        if self.config.bot_user_id in (mentions.get("user_ids") or []):
            return True
        body = (content.get("body") or "").strip()
        low = body.lower()
        # 2) 以 bot 名字 / @ 开头 = 在叫它
        if any(low.startswith(t.lower()) for t in self._mention_tokens()):
            return True
        # 3) 正文里出现完整用户 id（@pill）
        return self.config.bot_user_id in body

    def _strip_mention(self, text: str) -> str:
        """去掉开头的"叫它"前缀（@pill / 名字），留下真正的指令文本。"""
        text = text.strip()
        low = text.lower()
        for token in self._mention_tokens():
            if low.startswith(token.lower()):
                text = text[len(token):]
                break
        return text.lstrip(" :：,，@")

    # —— 主 AI 的"手"：把指令落成真实的 IM 操作 ——
    # 第一步用确定性的斜杠命令验证"建群+拉人+发富卡"全链路；
    # 第二步会换成 LLM 工具调用，让自然语言自动触发这些动作。

    def _try_handle_command(
        self, room_id: str, sender: str, text: str, event_id: str = ""
    ) -> bool:
        """识别并执行 IM 控制命令。命中返回 True，否则 False（交回对话处理）。

        目前支持（注意不要用 / 开头，否则会被 Element 当成它自己的客户端命令拦截）：
            建专班 <名字> / 专班 <名字>   → 新建专班群、拉发起人进去、发一张派单富卡
            技能 列表/添加/删除/停用/启用  → 管理本群（或私聊=个人）的技能
        （也兼容 /专班、/技能，万一用户在 Element 里点了"作为消息发送"）
        """
        text = text.strip()
        # 「建专班/专班 <名字>」**不再走演示派单卡**(负责人实报:AI 同事没进频道、少了
        # RULE)——那张卡(_launch_campaign)是硬编码 mock:选题/文案/数据 Agent 全是假文本,
        # 不拉真傀儡进群、不派真任务、不写 RULE。改为**门控通过后交回 AI**,由 assemble_team
        # 工具真编排:拆任务、选真 Agent、把傀儡拉进专班、写任务 RULE。门控/配额工具层
        # (execute 的 gate_check/quota_check)也有,这里只做被命令拦下时的快速前拦提示。
        for prefix in ("建专班", "/专班", "专班"):
            if text.startswith(prefix):
                if not self._gate_allows(sender, "create_room"):
                    self.client.send_text(room_id, self._gate_denied_text("create_room"))
                    return True
                if not self._gate_allows(sender, "assemble_team"):
                    self.client.send_text(room_id, self._gate_denied_text("assemble_team"))
                    return True
                over = self._rate_quota_blocked(sender, "teams", consume=False)
                if over:
                    self.client.send_text(room_id, over)
                    return True
                return False  # 交回 AI 对话,走 assemble_team 真编排(拉 Agent 进群+RULE)
        # 技能管理命令：先用不连 DB 的前缀闸判断，命中再执行（DB 不可用则提示未启用）。
        # 自定义技能是付费功能（custom_skill 门控）：低于门槛提示升级。
        if self._is_skill_command(text):
            if not self._gate_allows(sender, "custom_skill"):
                self.client.send_text(room_id, self._gate_denied_text("custom_skill"))
                return True
            self.client.send_text(room_id, self._run_skill_command(room_id, sender, text))
            return True
        # 知识库管理命令（同套路）
        if self._is_kb_command(text):
            self.client.send_text(room_id, self._run_kb_command(room_id, sender, text))
            return True
        # 工作流连接器命令（列表/跑外部 n8n/Make 等）
        if self._is_wf_command(text):
            source_key = f"event:{event_id}:cmd:wf" if event_id else ""
            self.client.send_text(
                room_id,
                self._run_wf_command(room_id, sender, text, source_key=source_key),
            )
            return True
        # 会员等级命令（自查 / 管理员设置）
        if self._is_member_command(text):
            self.client.send_text(room_id, self._run_member_command(sender, text))
            return True
        return False

    # —— 会员等级（账号权限分层）命令 ——

    def _is_member_command(self, text: str) -> bool:
        """是不是「会员」命令——纯字符串判断。"""
        t = text.strip()
        low = t.lower()
        return (
            t.startswith("会员")
            or t.startswith("我的会员")
            or t.startswith("/会员")
            or low == "member"
            or low.startswith("member ")
            or low.startswith("/member")
        )

    # 中文等级词 → slug（命令里允许用中文或直接用 slug）
    _TIER_ALIASES = {
        "免费": "free", "免费会员": "free",
        "付费": "paid", "付费会员": "paid",
        "创作者": "creator", "创作者会员": "creator", "创作": "creator",
    }

    def _resolve_tier_word(self, word: str) -> Optional[str]:
        """把命令里的等级词（中文别名或 slug）解析成合法 slug；无法识别返回 None。"""
        w = (word or "").strip()
        if is_valid_tier(w):
            return w
        return self._TIER_ALIASES.get(w)

    def _run_member_command(self, sender: str, text: str) -> str:
        """执行会员命令。

        任何人可查自己：``会员`` / ``我的会员``。
        平台管理员（控制室 power≥50）可管理（同工作流的授权口径——会员等级是付费门槛，
        不能让普通人自封）：
          ``会员 列表``            —— 列出所有非免费会员
          ``会员 设置 @user 付费``  —— 设/调某人等级（免费=撤销）
          ``会员 撤销 @user``       —— 回落到免费
        全程兜异常，绝不抛。
        """
        # 去前缀，留下参数体
        body = text.strip()
        for p in ("我的会员", "会员", "/会员", "/member", "member"):
            if body.lower().startswith(p.lower()):
                body = body[len(p):]
                break
        body = body.strip()

        # 无参 / 帮助：当作"查自己"（最常用），并附管理员用法提示
        if not body or body in ("帮助", "help", "?", "？"):
            mine = tier_label(self.members.get_tier(sender))
            tip = ""
            if self._is_platform_admin(sender):
                tip = (
                    "\n（管理员可用：会员 列表 / 会员 设置 @用户 付费 / 会员 撤销 @用户）"
                )
            return f"👤 你当前是「{mine}」。{tip}"

        # —— 以下是管理命令：先验平台管理员 ——
        if not self._is_platform_admin(sender):
            return "只有平台管理员能管理会员等级。你可以发「会员」查看自己的等级。"

        if body.startswith(("列表", "list", "ls")):
            mp = self.members.get_all()
            if not mp:
                return "目前没有付费/创作者会员（所有人默认免费会员）。"
            lines = [f"👥 非免费会员（{len(mp)} 人）："]
            for uid, rec in mp.items():
                src = rec.get("source") or "admin"
                lines.append(f"  · {uid} —— {tier_label(rec.get('tier'))}（来源:{src}）")
            return "\n".join(lines)

        if body.startswith(("设置", "set", "授予")):
            parts = body.split()
            # 形如：设置 @user 付费 —— parts[0]=动词, parts[1]=@user, parts[2]=等级
            if len(parts) < 3:
                return "用法：会员 设置 @用户 <免费|付费|创作者>"
            target, tier_word = parts[1], parts[2]
            tier = self._resolve_tier_word(tier_word)
            if not tier:
                tiers = "/".join(t["label"] for t in MEMBER_TIERS)
                return f"未知等级「{tier_word}」。可选：{tiers}（或 slug）。"
            if self.members.grant(target, tier, source="admin"):
                return f"✅ 已把 {target} 设为「{tier_label(tier)}」。"
            return "⚠️ 设置失败（控制室不存在或写入失败），请稍后再试。"

        if body.startswith(("撤销", "revoke", "取消")):
            parts = body.split()
            if len(parts) < 2:
                return "用法：会员 撤销 @用户"
            target = parts[1]
            if self.members.revoke(target):
                return f"✅ 已把 {target} 撤销为「免费会员」。"
            return "⚠️ 撤销失败（控制室不存在或写入失败），请稍后再试。"

        return "没听懂。发「会员」查看自己的等级；管理员发「会员 帮助」看用法。"

    def grant_member_tier(
        self, user_id: str, tier: str, source: str = "purchase"
    ) -> bool:
        """【预留接口】授予会员等级——给未来模块4（交易系统）支付成功后调用。

        本期不接真实支付：把数据模型(控制室 cosmac.members)和这个服务端入口先立起来，
        模块4 在支付回调里调本方法把用户提到对应等级即可。source 默认 'purchase' 以便审计
        区分「买来的」与「管理员手动给的」。成功返回 True。
        """
        return self.members.grant(user_id, tier, source=source)

    def _is_wf_command(self, text: str) -> bool:
        """是不是「工作流」命令——纯字符串判断。"""
        t = text.strip()
        low = t.lower()
        return (
            t.startswith("工作流")
            or t.startswith("/工作流")
            or low == "wf"
            or low.startswith("wf ")
            or low.startswith("/wf")
        )

    def _workflow_defs(self) -> List[Dict[str, Any]]:
        """读控制室「工作流连接器」定义（启用的）。失败返回空。"""
        try:
            ctrl = self.client.resolve_alias(self.config.control_room_alias)
            if not ctrl:
                return []
            ev = self.client.get_state_event(ctrl, WORKFLOWS_EVENT_TYPE) or {}
            return [
                w for w in (ev.get("workflows") or [])
                if isinstance(w, dict) and w.get("slug") and w.get("enabled", True)
            ]
        except Exception as e:
            logger.debug("读取工作流连接器失败（忽略）：%s", e)
            return []

    def _preset_workflows_text(self, slugs: List[str]) -> str:
        """本频道可直接调用的工作流：渲染成一段引导，让 AI 知道有现成工作流可跑。

        两个来源合并而来（见 _group_context_uncached）：入驻模板给工作区预置的 +
        本频道绑定的智能体自带的。二者都是管理员显式配置，因此**绑定即授权**——
        这批 slug 会随 ToolContext.authorized_workflows 下发，在本频道免受
        workflow_run 门控（与「群绑定技能不按发起人过滤」同一原则）。
        未列入的工作流仍按原门槛裁决。

        把 slug 解析成名字更友好；解析不到的 slug 跳过（可能已被后台删）。
        失败返回空，绝不阻断回复。
        """
        if not slugs:
            return ""
        try:
            by_slug = {str(w.get("slug")): w for w in self._workflow_defs()}
            lines: List[str] = []
            for sl in slugs:
                w = by_slug.get(str(sl))
                if not w:
                    continue  # 模板引用的工作流已不存在/被停用，跳过
                name = str(w.get("name") or sl).strip()
                lines.append(f"- {name}（slug：{sl}）")
            if not lines:
                return ""
            return (
                "【本频道可直接调用的工作流】：以下工作流已由管理员配置给本频道"
                "（入驻模板预置 / 频道绑定的智能体自带），需要时用 run_workflow 直接调用，"
                "无需再申请权限：\n" + "\n".join(lines)
            )
        except Exception as e:
            logger.debug("渲染预置工作流失败（忽略）：%s", e)
            return ""

    def _run_wf_command(
        self, room_id: str, sender: str, text: str, source_key: str = ""
    ) -> str:
        """执行工作流命令：`工作流 列表` / `工作流 跑 <slug> <输入>`。

        连接器定义读控制室 state event；运行同步调外部 webhook；结果尽力落库(DB 可用时)。
        全程兜异常，绝不抛。
        """
        # 去前缀
        body = text.strip()
        for p in ("工作流", "/工作流", "/wf", "wf"):
            if body.lower().startswith(p.lower()):
                body = body[len(p):]
                break
        body = body.strip()
        defs = self._workflow_defs()

        if not body or body in ("帮助", "help", "?", "？"):
            return (
                "🔗 工作流命令：\n"
                "  工作流 列表\n"
                "  工作流 跑 <编号> <输入>\n"
                "（连接器在「管理后台 → 工作流」配置，对接 n8n/Make 等）"
            )
        if body.startswith(("列表", "list", "ls")):
            if not defs:
                return "还没有可用的工作流连接器。请在「管理后台 → 工作流」添加。"
            lines = [f"🔗 可用工作流（{len(defs)} 个）："]
            for w in defs:
                hint = f" —— {w.get('input_hint')}" if w.get("input_hint") else ""
                lines.append(f"  · {w.get('slug')}（{w.get('name') or w.get('slug')}）{hint}")
            return "\n".join(lines)
        if body.startswith(("跑", "run", "执行")):
            # #1/#2 越权防护：跑工作流触发付费生成/外部写、用的是**服务端共享凭据**。
            # 授权走「workflow_run」门控（后台可配；默认「仅平台管理员」＝维持原行为，
            # 管理员可下调到付费/创作者）。不分 DM/群（否则任何人和 bot 开个两人 DM 就能跑）。
            # 普通成员只能「工作流 列表」查看。
            if not self._gate_allows(sender, "workflow_run"):
                return self._gate_denied_text("workflow_run") + " 你可以用「工作流 列表」查看可用工作流。"
            # 用量配额（workflow_runs，每月）：与 AI 工具 run_workflow 同 metric，命令入口也要计量，
            # 否则门控放行的付费用户走「工作流 跑」可无限次运行、配额形同虚设（M5）。先只查不扣，
            # 真正提交成功后再消费（失败/池满不扣，与工具路径「成功才扣」同口径）。
            over = self._rate_quota_blocked(sender, "workflow_runs", consume=False)
            if over:
                return over
            rest = body.split(maxsplit=1)
            arg = rest[1].strip() if len(rest) > 1 else ""
            parts = arg.split(maxsplit=1)
            slug = parts[0] if parts else ""
            user_input = parts[1].strip() if len(parts) > 1 else ""
            if not slug:
                return "用法：工作流 跑 <编号> <输入>（编号见「工作流 列表」）"
            conn = next((w for w in defs if w.get("slug") == slug), None)
            if conn is None:
                return f"没找到工作流「{slug}」。用「工作流 列表」看可用的。"
            name = conn.get("name") or slug
            # 异步连接器（长任务）：登记 pending + 回调 URL，提交后即返回，等平台回调。
            # #3：只有 webhook 家族支持回调；dify/coze/comfyui 即便误存了 async=true 也走后台同步。
            from cosmac.wf import supports_async_callback
            if (conn.get("async") and self.config.public_url
                    and supports_async_callback(conn.get("platform"))):
                out = self._dispatch_async(
                    conn, user_input, room_id, sender, name, source_key
                )
                self._tool_quota_consume(sender, "run_workflow")  # 提交成功才扣 workflow_runs
                return out
            # #4/#5：**所有同步连接器**都放有界后台池跑、立即返回——webhook/dify/coze 也可能
            # 等到 30s、ComfyUI 更到 120s，同步执行会卡住 appservice 事务响应（Synapse 超时重试）。
            # 后台跑完把结果发回本群。池满则提示繁忙。
            if self._run_wf_in_background(
                conn, user_input, room_id, sender, name, source_key
            ):
                self._tool_quota_consume(sender, "run_workflow")  # 提交成功才扣 workflow_runs
                return f"⏳ 工作流「{name}」已开始，完成后结果会自动发到本群。"
            return "⚠️ 任务太多、系统繁忙，请稍后再试。"
        return f"没听懂「{body}」。发「工作流 帮助」看用法。"

    def _run_wf_in_background(
        self, conn, user_input, room_id, sender, name, source_key: str = ""
    ) -> bool:
        """把同步连接器放**有界**后台线程池跑，避免阻塞 appservice 事务（#4/#5）。

        ComfyUI 成功时已自行把图发回房间（不再补文字）；其它平台返回文本→后台发回群。
        失败/异常补一条文字。运行记录尽力落库。池满（在跑+排队超上限）返回 False。
        """
        from cosmac.wf import run_connector, submit_background

        if source_key and not self._reserve_wf_source(
            source_key, conn, user_input, room_id, sender
        ):
            return True

        def work() -> None:
            try:
                result = run_connector(
                    conn, user_input, client=self.client, room_id=room_id
                )
                self._record_wf_run(
                    room_id, sender, conn, user_input, result, source_key=source_key
                )
                if not result.get("ok"):
                    self.client.send_text(
                        room_id, f"⚠️ 工作流「{name}」执行失败：{result.get('error')}"
                    )
                elif conn.get("platform") != "comfyui":
                    out = result.get("output") or "（无返回内容）"
                    self.client.send_text(room_id, f"✅ 工作流「{name}」已完成：\n{out}")
            except Exception:
                logger.exception("后台工作流执行出错：%s", name)

        # ComfyUI 走慢池，避免长生成把快连接器/提交堵在队尾（#5）
        pool = "slow" if conn.get("platform") == "comfyui" else "fast"
        if submit_background(work, pool=pool):
            return True
        # 池满提交失败：回滚刚才的来源预约，否则占位残留、重放误判"已提交"、1h 后误报中断（M8）
        if source_key:
            self._release_wf_source(source_key)
        return False

    def _dispatch_async(
        self, conn, user_input, room_id, sender, name, source_key: str = ""
    ) -> str:
        """异步连接器：建 pending 运行(带一次性 token)+ 回调 URL，提交给平台后即返回。

        平台跑完反向 POST 到 {public_url}/cosmac/wf/callback/<run_id>（URL **不含 token**）。
        token 放进我们发给平台的 payload(callback_token)，平台回传 X-Cosmac-Token 头来鉴权，
        token 从此不进任何 URL/日志。DB 只存哈希、单次用完即废。DB 不可用则退回同步说明。
        """
        import secrets

        from cosmac.wf import run_connector, submit_background

        try:
            from cosmac.db import session_scope
            from cosmac.db.wf_repo import (
                complete_run, create_pending, find_by_source_key, get_run,
                mark_submission_started,
            )

            token = secrets.token_urlsafe(16)
            with session_scope() as s:
                if source_key:
                    old = find_by_source_key(s, source_key)
                    if old is not None:
                        if old.status in ("queued", "pending", "processing"):
                            return f"⏳ 工作流「{name}」已由这条消息提交过（#{old.id}），我不会重复提交。"
                        return f"工作流「{name}」已由这条消息处理过（#{old.id}），不会重复提交。"
                run = create_pending(
                    s, slug=conn.get("slug", ""), platform=conn.get("platform", "webhook"),
                    room_id=room_id, sender=sender, user_input=user_input,
                    token=_token_hash(token),  # #4：DB 只存 token 哈希，不存明文
                    source_key=source_key,
                )
                run_id = run.id
            # #2：回调 URL **不含 token**（路径也会进 nginx 日志）。token 放进我们 POST 给
            # 平台的 payload(callback_token)，平台据此回传 X-Cosmac-Token 头来鉴权——token
            # 从此不进任何 URL/日志。DB 只存哈希、单次用完即废。
            cb = f"{self.config.public_url.rstrip('/')}/cosmac/wf/callback/{run_id}"

            # #3：**提交也放后台**——webhook 提交本身可能等到 30s，同步会卡住 appservice 事务。
            # 提交成功就等平台回调；提交失败则结清 pending + 通知群。
            def _submit() -> None:
                err = ""
                ambiguous = False
                try:
                    # 先持久化“已开始外呼”，再发 HTTP。此后崩溃也保留 token 等合法回调，
                    # 避免外部已接单、本地却把 queued 回收后引发重复扣费。
                    with session_scope() as s2:
                        if not mark_submission_started(s2, run_id):
                            return
                    r = run_connector(
                        conn, user_input, callback_url=cb, callback_token=token
                    )
                    if not r.get("ok"):
                        err = r.get("error") or "提交失败"
                        ambiguous = bool(r.get("ambiguous"))
                except Exception as exc:
                    # worker 已进入 pending 后出现未知异常，外部请求可能已经发出；按结果未知处理，
                    # 保留 token 等回调/超时收口，不能直接提示重试导致重复扣费。
                    logger.exception("异步工作流提交出错：%s", name)
                    err = f"提交异常、结果未知：{exc}"
                    ambiguous = True
                if err:
                    # 平台可能在提交 HTTP 响应返回前就完成回调。若回调线程已结清运行，
                    # 这里必须静默结束，不能再往群里补一条相互矛盾的失败/未知提示。
                    with session_scope() as s2:
                        latest = get_run(s2, run_id)
                        if latest is not None and latest.status in ("ok", "error"):
                            return
                if err and ambiguous:
                    self.client.send_text(
                        room_id,
                        f"⚠️ 工作流「{name}」提交结果未知：{err}。"
                        "系统会继续等待回调，请先到外部平台确认，不要立即重试。",
                    )
                elif err:
                    with session_scope() as s2:
                        complete_run(s2, run_id, error=err)
                    self.client.send_text(
                        room_id, f"⚠️ 工作流「{name}」提交失败：{err}"
                    )

            # #5：异步"提交"走独立 submit 池——绝不被长任务(ComfyUI/同步连接器)堵在队尾，
            # 否则用户已收到"已提交"、提交动作却还排队迟迟发不出去。
            if submit_background(_submit, pool="submit"):
                return f"⏳ 工作流「{name}」已提交（#{run_id}），完成后结果会自动发到本群。"
            # 池满 → 结清这条 pending，提示繁忙
            with session_scope() as s:
                complete_run(s, run_id, error="系统繁忙")
            return "⚠️ 任务太多、系统繁忙，请稍后再试。"
        except Exception as e:
            logger.warning("异步工作流提交失败：%s", e)
            return f"⚠️ 工作流「{name}」提交失败（异步未就绪）。"

    def handle_wf_callback(self, run_id: int, token: str, body: Dict[str, Any]) -> int:
        """处理外部平台的异步回调：校验 token→把结果发回原群→结清运行。返回 HTTP 状态码。

        body 约定：{"output": "..."} 成功 / {"error": "..."} 失败。
        返回 200(成功) / 403(token 不符) / 404(无此 pending 运行) / 500(内部错)。
        """
        try:
            import hmac

            from cosmac.db import session_scope
            from cosmac.db.wf_repo import (
                claim_pending, complete_run, get_run, revert_to_pending,
            )

            with session_scope() as s:
                run = get_run(s, run_id)
                if run is None:
                    return 404
                if run.status in ("ok", "error"):
                    return 200  # 已处理完 → 幂等返回，不重复发/不再结算
                # pending / processing 才往下走（processing 可能是上次半途崩的，靠 claim 判定）
                # #4：比对 token 的哈希（DB 存的是哈希），用 compare_digest 防时序侧信道
                if not token or not hmac.compare_digest(
                    _token_hash(token), run.token or ""
                ):
                    return 403
                room_id = run.room_id
                slug = run.slug
                # #2/#3：原子抢占成 processing。并发回调只有一个抢到；卡死(超时)的可被重抢。
                # 抢不到 = 别的回调正在处理 → 幂等返回 200，绝不重复发/重复结算。
                if not claim_pending(s, run_id):
                    return 200
            # #5：消息正文按字节截断——回调体可达 512KB，整条塞进 Matrix 事件会超事件大小上限
            # 导致 send 持续失败、run 反复回到 pending 无限重试。完整结果在 DB 的 run 记录里。
            output = str(body.get("output") or "")[:_MAX_WF_MSG]
            error = str(body.get("error") or "")[:_MAX_WF_MSG]
            # #6：**先发消息、确认发出去了再结清**。发失败（返回假值或抛异常）就回滚到 pending、
            # 回 500 让平台重试，不会丢结果。
            # #4：用**固定 txn id**(随 run_id)，崩溃恢复后重发同一条会被 Synapse 去重，群里不重复。
            text = (
                f"⚠️ 工作流「{slug}」(#{run_id}) 失败：{error}" if error
                else f"✅ 工作流「{slug}」(#{run_id}) 完成：\n{output or '（无内容）'}"
            )
            try:
                sent = self.client.send_text(room_id, text, txn_id=f"cosmac-wf-{run_id}")
            except Exception:
                logger.exception("工作流回调发消息抛异常 run_id=%s", run_id)
                sent = None
            if not sent:
                logger.warning("工作流回调发消息失败 run_id=%s，回滚 pending 待重试", run_id)
                with session_scope() as s:
                    revert_to_pending(s, run_id)
                return 500
            with session_scope() as s:
                complete_run(s, run_id, output=output, error=error)
            return 200
        except Exception:
            logger.exception("处理工作流回调出错 run_id=%s", run_id)
            return 500

    # —— 模块4 交易系统：前端「升级会员」走这几个端点（前端够不到 cosmac DB）——

    def handle_pay_plans(self) -> List[Dict[str, Any]]:
        """返回**上架**套餐列表（公开读，给前端「升级会员」展示）。只暴露展示必要字段。"""
        out: List[Dict[str, Any]] = []
        for p in self.orders.list_plans():
            if not p.enabled:
                continue
            out.append({
                "slug": p.slug, "name": p.name, "tier": p.tier,
                "period_days": p.period_days, "prices": dict(p.prices),
            })
        return out

    def operating_stats(self) -> Dict[str, Any]:
        """返回当前节点可对账的会员、内容资产和业务运营聚合数据。

        只统计 GuDuu OS 真正拥有的数据：会员和平台能力定义（Matrix 控制室）、
        频道类型（Synapse Admin API），以及自建技能、Agent、知识库、工作流运行和
        订单（cosmac DB）。返回值不包含用户 ID、订单内容或聊天内容，既供节点管理
        看板使用，也可安全地作为 Nexus 心跳聚合指标。每个数据源独立兜底；无法读取
        Synapse 全量房间时会直接缺省该组字段，绝不把部分数据或演示数字当真实统计。
        """
        # 字段只在对应数据源确实读成功后加入。这样数据库或管理员 API 故障时，Nexus
        # 显示「未上报」而不是一个看似可信的 0，严格区分“真实为空”和“暂时读不到”。
        out: Dict[str, Any] = {}
        try:
            mp = self.members.get_all()
            # get_all() 已排除 free 和已过期记录，这里的 total 就是当前有效会员。
            out["members_total"] = len(mp)
            out["members_paid"] = sum(1 for r in mp.values() if r.get("tier") == "paid")
            out["members_creator"] = sum(
                1 for r in mp.values() if r.get("tier") == "creator"
            )
        except Exception:
            logger.debug("统计会员失败", exc_info=True)
        try:
            # 平台可用技能/Agent 是「内置预置 + 控制室覆盖」后的真实启用目录，
            # 与下方 DB 中用户/频道自建资源分开上报，避免把两种来源混为一个数字。
            out["skills_available"] = len(self._skill_library())
            out["agents_available"] = len(self._global_agent_items())
        except Exception:
            logger.debug("统计平台技能和 Agent 目录失败", exc_info=True)
        try:
            ctrl = self.client.resolve_alias(self.config.control_room_alias)
            if ctrl:
                event = self.client.get_state_event(ctrl, WORKFLOWS_EVENT_TYPE) or {}
                workflows = [
                    row for row in (event.get("workflows") or [])
                    if isinstance(row, dict) and row.get("slug")
                ]
                out["workflows_total"] = len(workflows)
                out["workflows_enabled"] = sum(
                    1 for row in workflows if row.get("enabled", True)
                )
        except Exception:
            logger.debug("统计工作流定义失败", exc_info=True)
        try:
            from sqlalchemy import func, select

            from cosmac.db import session_scope
            from cosmac.db.models import (
                Agent,
                KnowledgeChunk,
                KnowledgeDoc,
                Order,
                Skill,
                WorkflowRun,
            )

            with session_scope() as s:
                out["workflow_runs"] = int(
                    s.execute(select(func.count()).select_from(WorkflowRun)).scalar() or 0
                )
                out["orders_paid"] = int(
                    s.execute(
                        select(func.count()).select_from(Order)
                        .where(Order.status == "paid")
                    ).scalar() or 0
                )
                out["kb_docs"] = int(
                    s.execute(select(func.count()).select_from(KnowledgeDoc)).scalar() or 0
                )
                out["kb_chunks"] = int(
                    s.execute(select(func.count()).select_from(KnowledgeChunk)).scalar() or 0
                )
                # 当前没有单独的「知识库」表；一个 scope + scope_id 就是一座真实知识库。
                # 只统计至少已有一篇文档的作用域，标签明确叫「有内容的知识库」。
                out["knowledge_bases_total"] = len(
                    s.execute(
                        select(KnowledgeDoc.scope, KnowledgeDoc.scope_id).distinct()
                    ).all()
                )
                out["skills_custom_total"] = int(
                    s.execute(select(func.count()).select_from(Skill)).scalar() or 0
                )
                out["skills_custom_enabled"] = int(
                    s.execute(
                        select(func.count()).select_from(Skill)
                        .where(Skill.enabled.is_(True))
                    ).scalar() or 0
                )
                out["agents_custom_total"] = int(
                    s.execute(select(func.count()).select_from(Agent)).scalar() or 0
                )
                out["agents_custom_enabled"] = int(
                    s.execute(
                        select(func.count()).select_from(Agent)
                        .where(Agent.enabled.is_(True))
                    ).scalar() or 0
                )
        except Exception:
            logger.debug("统计 DB 指标失败", exc_info=True)
        try:
            room_ids = self.client.admin_list_room_ids()
            if room_ids is not None:
                classified = self._classify_admin_rooms(room_ids)
                kinds = classified["kinds"]
                out["channels_total"] = sum(
                    1 for room_id in room_ids if kinds.get(room_id) == "channel"
                )
                out["spaces_total"] = sum(
                    1 for room_id in room_ids if kinds.get(room_id) == "space"
                )
                out["ai_rooms_total"] = sum(
                    1 for room_id in room_ids if kinds.get(room_id) == "ai"
                )
                out["dm_rooms_total"] = sum(
                    1 for room_id in room_ids if kinds.get(room_id) == "dm"
                )
        except Exception:
            logger.debug("统计 Matrix 房间类型失败", exc_info=True)
        return out

    def handle_stats(self, access_token: str) -> Tuple[int, Dict[str, Any]]:
        """平台**真实运营指标**（给数据看板用），仅平台管理员可读。

        权限校验与统计计算分开：HTTP 请求必须是管理员；节点自身的 Nexus
        心跳不经过用户 HTTP，由进程内部直接调用 :meth:`operating_stats`。
        """
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        if not self._is_platform_admin(user_id):
            return 403, {"error": "仅平台管理员可查看平台运营指标"}
        out = self.operating_stats()
        return 200, out

    def handle_node_settings_get(
        self, access_token: str
    ) -> Tuple[int, Dict[str, Any]]:
        """读取节点系统设置；仅服务器管理员可读，且响应永不包含密钥原文。"""
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        if not self._is_platform_admin(user_id):
            return 403, {"error": "仅平台管理员可配置节点"}
        try:
            from cosmac.node_settings import admin_config

            return 200, admin_config()
        except Exception:
            logger.exception("读取节点系统设置失败")
            return 500, {"error": "读取节点设置失败，请检查数据库与设置主密钥"}

    def handle_node_settings_save(
        self, access_token: str, body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """保存首次部署向导/系统设置；只有服务器管理员可以改。"""
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        if not self._is_platform_admin(user_id):
            return 403, {"error": "仅平台管理员可配置节点"}
        from cosmac.node_settings import NodeSettingsError, save_admin_config
        try:
            payload = save_admin_config(body or {})
            # 清掉 Matrix state 的 20 秒缓存，使新 provider/model 下一轮消息立即生效。
            self._cfg_cache_ts = float("-inf")
            self._apply_runtime_config()
            return 200, payload
        except NodeSettingsError as exc:
            return 400, {"error": str(exc)}
        except Exception:
            logger.exception("保存节点系统设置失败")
            return 500, {"error": "保存失败，请检查数据库与设置主密钥"}

    def handle_node_update_status(
        self, access_token: str, *, user_id: str = ""
    ) -> Tuple[int, Dict[str, Any]]:
        """读取宿主代理缓存的新版本通知；仅管理员可见，不包含镜像凭据或安装命令。"""
        # 批准接口已经完成过一次 whoami 时把结果传进来，既避免重复请求 Synapse，也让
        # “鉴权通过的管理员”与最终写进批准文件的 approved_by 始终是同一个身份。
        user_id = user_id or self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        if not self._is_platform_admin(user_id):
            return 403, {"error": "仅平台管理员可查看节点更新"}
        path = os.environ.get(
            "COSMAC_PENDING_UPDATE_PATH", "/var/lib/cosmac/pending-update.json"
        )
        try:
            with open(path, "r", encoding="utf-8") as handle:
                value = json.load(handle)
            if not isinstance(value, dict):
                raise ValueError("invalid update state")
            return 200, {"update": value}
        except FileNotFoundError:
            return 200, {"update": None}
        except Exception:
            logger.exception("读取节点更新通知失败")
            return 500, {"error": "更新状态文件损坏"}

    def handle_node_update_approve(
        self, access_token: str, body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """批准代理下一轮安装指定版本；浏览器只能批准当前待处理 release_id。"""
        # approved_by 必须来自当前 access token，绝不能信任浏览器 body。旧实现虽然在
        # 状态接口里做过鉴权，却没有把 user_id 带回本函数，随后写文件时触发 NameError。
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        if not self._is_platform_admin(user_id):
            return 403, {"error": "仅平台管理员可批准节点更新"}
        code, current = self.handle_node_update_status(
            access_token, user_id=user_id
        )
        if code != 200:
            return code, current
        update = current.get("update")
        if not isinstance(update, dict):
            return 404, {"error": "当前没有待安装版本"}
        try:
            expected = int(update.get("release_id") or 0)
            requested = int((body or {}).get("release_id") or 0)
        except (TypeError, ValueError):
            return 400, {"error": "版本任务无效"}
        if not expected or requested != expected:
            return 409, {"error": "待安装版本已经变化，请刷新后重新确认"}
        path = os.environ.get(
            "COSMAC_APPROVED_UPDATE_PATH", "/var/lib/cosmac/approved-update.json"
        )
        try:
            from cosmac.node_updates import write_update_approval

            write_update_approval(path, expected, user_id)
            return 200, {"approved": True, "release_id": expected}
        except PermissionError:
            logger.exception(
                "写入节点更新批准文件被拒绝 user=%s release=%s", user_id, expected
            )
            return 500, {"error": "无法通知宿主更新代理，请检查数据目录权限"}
        except OSError:
            logger.exception(
                "写入节点更新批准文件发生系统错误 user=%s release=%s",
                user_id,
                expected,
            )
            return 500, {
                "error": "无法写入宿主更新批准文件，请检查磁盘与共享目录状态"
            }
        except Exception:
            # NameError、TypeError 等代码错误绝不能再伪装成“客户服务器权限问题”；保留
            # 完整 traceback 给技术人员，同时给页面明确的程序异常提示。
            logger.exception(
                "节点更新批准发生程序异常 user=%s release=%s", user_id, expected
            )
            return 500, {
                "error": "节点更新批准失败，服务端程序异常，请联系技术人员并查看 Bot 日志"
            }

    def handle_hr_employees(self, access_token: str) -> Tuple[int, Dict[str, Any]]:
        """人事花名册（给前端「组织/人事」页用）：公司概览 + 部门分组 + 员工列表。

        权限：花名册含薪资/绩效等敏感字段，与 hr_data 门控同口径——**仅平台管理员**可读；
        非管理员回 403，前端据此回退（不报错）。数据来自 cosmac DB 的 cosmac_employee 表
        （由 seed_hr 播种）；读失败/空表都优雅返回，不抛异常。
        """
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        if not self._is_platform_admin(user_id):
            return 403, {"error": "仅平台管理员可查看人事数据"}
        out: Dict[str, Any] = {
            "company": "星澜科技", "summary": {}, "departments": [], "employees": [],
        }
        try:
            from cosmac.db import employee_repo as hr
            from cosmac.db import session_scope

            with session_scope() as s:
                out["summary"] = hr.company_summary(s)
                out["departments"] = out["summary"].get("各部门人数", [])
                rows = hr.list_employees(s, limit=999)
                out["employees"] = [hr.to_api_dict(e) for e in rows]
        except Exception:
            logger.debug("读人事花名册失败", exc_info=True)
        return 200, out

    def handle_kb_room_doc(
        self, access_token: str, room_id: str, doc_id: str
    ) -> Tuple[int, Dict[str, Any]]:
        """读**本频道**某篇知识库文档全文(频道成员可用;右侧「关于此频道」点开文档看内容)。

        鉴权两道:①发起人是该频道成员;②文档确实挂在该频道(scope=room 且 scope_id=room_id)
        ——防止拿着任意 doc_id 跨频道读别家文档。正文=chunks 按序拼接,截 2 万字。
        """
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        room_id = str(room_id or "").strip()
        if not room_id.startswith("!"):
            return 400, {"error": "无效的频道 id"}
        if not self.client.is_joined_member(room_id, user_id):
            return 403, {"error": "你不是该频道成员"}
        try:
            did = int(doc_id)
        except (TypeError, ValueError):
            return 400, {"error": "无效的文档 id"}
        try:
            from cosmac.db import session_scope
            from cosmac.db.models import SCOPE_ROOM, KnowledgeChunk, KnowledgeDoc

            with session_scope() as s:
                doc = s.get(KnowledgeDoc, did)
                if doc is None or doc.scope != SCOPE_ROOM or doc.scope_id != room_id:
                    return 404, {"error": "本频道没有这篇文档(可能已删除)"}
                chunks = (
                    s.query(KnowledgeChunk)
                    .filter(KnowledgeChunk.doc_id == did)
                    .order_by(KnowledgeChunk.id)
                    .all()
                )
                text = "\n".join(str(c.text or "") for c in chunks)
                return 200, {"id": doc.id, "title": doc.title, "text": text[:20000]}
        except Exception:
            logger.exception("读频道知识库文档失败")
            return 500, {"error": "读取失败(数据库不可用?)"}

    # 后台房型判定的进程内缓存(room_id → kind)。建房标记(ai_session/dm/space)终生不变,
    # 永久缓存;第一次全量判定后,后续刷新只有新房走网络。
    _admin_kind_cache: Dict[str, str] = {}
    # 建房时间戳缓存(room_id → m.room.create 的 origin_server_ts,毫秒)。创建时间永不变,
    # 与 kind 同一趟读 state 时顺手取出(零额外请求),供后台「频道管理」按创建时间倒序排。
    _admin_created_cache: Dict[str, int] = {}

    def _classify_admin_rooms(self, room_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """把 Synapse 全量房间按真实 state 标记分类，并返回分类与创建时间。

        这是后台频道管理和 Nexus 节点统计共用的唯一判定口径。调用方负责提供可信的
        全量房间 id；本方法保留永久缓存并并发读取 state，避免两处各写一套规则后漂移。
        """
        ids = [
            str(room_id).strip() for room_id in room_ids
            if str(room_id).strip().startswith("!")
        ]
        todo = [room_id for room_id in ids if room_id not in self._admin_kind_cache]

        def _judge(room_id: str) -> None:
            kind = "channel"
            created = 0
            try:
                state = self.client.admin_room_state(room_id) or []
                for event in state:
                    event_type = event.get("type")
                    # m.room.create 一定存在：既用于判 space，也顺手取永久不变的建房时间。
                    # 不能提前 break，否则普通频道可能拿不到 create 事件的时间。
                    if event_type == "m.room.create":
                        created = int(event.get("origin_server_ts") or 0)
                        if (event.get("content") or {}).get("type") == "m.space":
                            kind = "space"
                    elif event_type == "cosmac.ai_session":
                        kind = "ai"
                    elif event_type == "cosmac.dm":
                        kind = "dm"
            except Exception:
                pass  # 读不出时 fail-open 为 channel，后台不能静默隐藏可能的真频道。
            self._admin_kind_cache[room_id] = kind
            self._admin_created_cache[room_id] = created

        if todo:
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=8, thread_name_prefix="kind") as pool:
                list(pool.map(_judge, todo))
        return {
            "kinds": {
                room_id: self._admin_kind_cache.get(room_id, "channel")
                for room_id in ids
            },
            "created": {
                room_id: self._admin_created_cache.get(room_id, 0)
                for room_id in ids
            },
        }

    def handle_admin_room_kinds(
        self, access_token: str, body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """后台「频道管理」批量判房型(仅平台管理员):{room_id: space|ai|dm|channel}。

        负责人实报:后台把中枢 AI 会话房、用户间私信都当「频道」统计/列出了。
        Synapse admin /rooms 摘要没有这些信息——真相在房间 state 标记里
        (cosmac.ai_session / cosmac.dm / m.room.create.type),bot 用管理员通道
        (admin_room_state,bot 不在的房也能读)批量判定。带永久缓存(标记不变);
        单房读不出按 channel 兜底(宁可多显示,不静默藏房)。并发 8 路控制耗时。
        """
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        if not self._is_platform_admin(user_id):
            return 403, {"error": "仅平台管理员可用"}
        ids = [
            str(room_id).strip()
            for room_id in (body or {}).get("room_ids") or []
            if str(room_id).strip().startswith("!")
        ][:2000]  # HTTP 后台接口保留防滥用上限；节点内部全量统计不截断。
        return 200, self._classify_admin_rooms(ids)

    def handle_admin_room_detail(
        self, access_token: str, room_id: str
    ) -> Tuple[int, Dict[str, Any]]:
        """后台「频道管理·详情」：一次返回某频道的 RULE/知识库/技能/智能体/记忆(仅平台管理员)。

        负责人需求:后台要能看每个频道的 人员/RULE/知识库/Skill/Agent/记忆——人员前端已有
        (Synapse admin API),其余在此聚合。channel_config 优先 bot 视角读(在房),bot 未进驻
        的频道走管理员 API 兜底(admin_room_state);DB 数据(技能/文档/记忆)与在不在房无关。
        全程兜异常:某块读不出就给空,别整个详情打不开。
        """
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        if not self._is_platform_admin(user_id):
            return 403, {"error": "仅平台管理员可查看频道详情"}
        room_id = str(room_id or "").strip()
        if not room_id.startswith("!"):
            return 400, {"error": "无效的频道 id"}
        # ① channel_config(bot 在房直接读;不在房走 admin API 兜底)
        cfg: Dict[str, Any] = {}
        try:
            cfg = self.client.get_state_event(room_id, CHANNEL_CONFIG_EVENT_TYPE) or {}
        except Exception:
            cfg = {}
        if not cfg:
            try:
                for ev in (self.client.admin_room_state(room_id) or []):
                    if ev.get("type") == CHANNEL_CONFIG_EVENT_TYPE \
                            and not ev.get("state_key"):
                        cfg = ev.get("content") or {}
                        break
            except Exception:
                cfg = {}
        rules = [
            {"label": str(r.get("label") or ""), "desc": str(r.get("desc") or "")}
            for r in (cfg.get("rules") or []) if isinstance(r, dict)
        ]
        task_rule = str(cfg.get("taskRule") or "")
        persona = cfg.get("persona") or {}
        # 绑定的智能体:persona.agentSlug(单绑) + agentSlugs(专班协作),解析成名字
        agent_slugs = [str(s) for s in (cfg.get("agentSlugs") or []) if s]
        p_slug = str((persona.get("agentSlug") or "")).strip()
        if p_slug and p_slug not in agent_slugs:
            agent_slugs.insert(0, p_slug)
        agents = []
        for slug in agent_slugs:
            a = None
            try:
                a = self._find_global_agent(slug)
            except Exception:
                a = None
            agents.append({"slug": slug, "name": str((a or {}).get("name") or slug)})
        # 知识库绑定来源(可读标签)
        kb_sources = []
        for src in (cfg.get("kbScopes") or []):
            src = str(src)
            if src == "platform":
                kb_sources.append("平台知识库")
            elif src.startswith("user:"):
                kb_sources.append(f"个人库({src[5:]})")
            elif src.startswith("room:"):
                kb_sources.append(f"频道库({src[5:]})")
        # ② DB:本频道技能 / 已上传文档 / 长期记忆
        skills: List[Dict[str, Any]] = []
        kb_docs: List[Dict[str, Any]] = []
        memory = ""
        try:
            from cosmac.db import kb as kb_mod, session_scope
            from cosmac.db.memory_repo import get_summary
            from cosmac.db.models import SCOPE_ROOM, Skill as DbSkill

            with session_scope() as s:
                for sk in s.query(DbSkill).filter(
                    DbSkill.scope == SCOPE_ROOM, DbSkill.scope_id == room_id,
                ).all():
                    skills.append({
                        "slug": sk.slug, "name": sk.name,
                        "enabled": bool(sk.enabled),
                    })
                for d in kb_mod.list_docs(s, scope=SCOPE_ROOM, scope_id=room_id):
                    kb_docs.append({"id": d.id, "title": d.title, "source": d.source})
                memory = get_summary(s, SCOPE_ROOM, room_id) or ""
        except Exception:
            logger.debug("读频道详情 DB 部分失败", exc_info=True)
        return 200, {
            "rules": rules,
            "task_rule": task_rule,
            "persona": {
                "aiName": str(persona.get("aiName") or ""),
                # 详情就是要看全,给足 2000(人设上限量级);超长再截
                "prompt": str(persona.get("prompt") or "")[:2000],
            },
            "agents": agents,
            "kb_sources": kb_sources,
            "kb_docs": kb_docs,
            "skills": skills,
            "memory": memory[:3000],
        }

    def handle_admin_kb_doc(
        self, access_token: str, doc_id: str
    ) -> Tuple[int, Dict[str, Any]]:
        """后台「频道详情」点开某篇知识库文档看全文(仅平台管理员)。

        正文不存 doc 行、在分块表里——按 chunk id 顺序拼回全文;超长截 2 万字(前端预览
        足够,也别把超大文档一次性打到浏览器)。
        """
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        if not self._is_platform_admin(user_id):
            return 403, {"error": "仅平台管理员可查看"}
        try:
            did = int(doc_id)
        except (TypeError, ValueError):
            return 400, {"error": "无效的文档 id"}
        try:
            from cosmac.db import session_scope
            from cosmac.db.models import KnowledgeChunk, KnowledgeDoc

            with session_scope() as s:
                doc = s.get(KnowledgeDoc, did)
                if doc is None:
                    return 404, {"error": "文档不存在(可能已删除)"}
                chunks = (
                    s.query(KnowledgeChunk)
                    .filter(KnowledgeChunk.doc_id == did)
                    .order_by(KnowledgeChunk.id)
                    .all()
                )
                text = "\n".join(str(c.text or "") for c in chunks)
                return 200, {
                    "id": doc.id, "title": doc.title, "source": doc.source,
                    "scope": doc.scope, "text": text[:20000],
                }
        except Exception:
            logger.exception("读知识库文档全文失败")
            return 500, {"error": "读取失败(数据库不可用?)"}

    def handle_admin_archives(self, access_token: str) -> Tuple[int, Dict[str, Any]]:
        """列全部专班归档记录(管理后台「归档记录」页)。仅平台管理员。

        归档存 cosmac DB `cosmac_project_archive`(archive_project 工具写入),浏览器
        够不到 DB——bot 代读(与 admin/emails 同套路)。时间按产品时区格式化后下发,
        前端直接展示,免时区换算。附任务快照(tasks),前端点开可看每条任务的结果。
        """
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        if not self._is_platform_admin(user_id):
            return 403, {"error": "仅平台管理员可查看归档记录"}
        try:
            from datetime import timezone as _tz

            from cosmac.db import session_scope
            from cosmac.db.archive_repo import list_archives
            from cosmac.tzutil import fmt_ts

            out = []
            with session_scope() as s:
                for r in list_archives(s, room_ids=None, limit=200):
                    # created_at 存的是 naive UTC(TimestampMixin)——补时区再转 epoch
                    try:
                        ts = int(r.created_at.replace(tzinfo=_tz.utc).timestamp())
                        when = fmt_ts(ts, "%Y-%m-%d %H:%M")
                    except Exception:
                        when = ""
                    out.append({
                        "id": r.id,
                        "room_id": r.room_id,
                        "goal": r.goal,
                        "summary": r.summary,
                        "tasks": list(r.tasks or []),
                        "done_count": r.done_count,
                        "total_count": r.total_count,
                        "archived_by": r.archived_by,
                        "archived_at": when,
                    })
            return 200, {"archives": out}
        except Exception:
            logger.exception("读取归档记录失败")
            return 500, {"error": "读取归档记录失败(数据库不可用?)"}

    def handle_admin_emails(self, access_token: str) -> Tuple[int, Dict[str, Any]]:
        """管理后台:列「用户名 localpart → 邮箱」映射(给用户列表显示邮箱)。**仅平台管理员**。

        邮箱是个人敏感信息、且这是全平台一次性拉取(普通用户不该看到别人邮箱),故限管理员;
        非管理员回 403。邮箱只在 cosmac DB 的 RegisteredEmail 里(Synapse 不存),浏览器够不到
        DB,只能经这个 bot 端点拿。读失败不报错、返回空表(前端优雅降级为"不显示邮箱")。
        """
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        if not self._is_platform_admin(user_id):
            return 403, {"error": "仅平台管理员可查看用户邮箱"}
        emails: Dict[str, str] = {}
        try:
            from sqlalchemy import select

            from cosmac.db import session_scope
            from cosmac.db.models import RegisteredEmail

            with session_scope() as s:
                for row in s.execute(select(RegisteredEmail)).scalars():
                    if row.username and row.email:
                        # 键统一用小写 localpart,与前端按 localpart 匹配一致
                        emails[row.username.strip().lower()] = row.email
        except Exception:
            logger.debug("读取邮箱映射失败", exc_info=True)
        return 200, {"emails": emails}

    def handle_channel_claim_admin(
        self, access_token: str, body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """在某频道给调用者授 power=100(用 Synapse make_room_admin),让他能改频道名/配置/技能。

        放行两类人(否则默认 power=0、写不了 m.room.name / cosmac.channel_config 那些 state event)：
          ① **平台管理员**——接管任意频道(bug14:服务器管理员≠房间管理员)。
          ② **无主频道的成员**——bot 建的频道里只有 bot 有权限(创建者就是 bot)，真人主人是 0 级、
             一改名就 403。凡是「除 bot 外没有任何人 ≥50 级」的频道视为**无主**，其成员(通常就是当初
             叫 AI 建这个频道的那个人)可**认领**为主人。已经有真人主人的频道则拒绝，防止普通成员抢权。
        """
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        room_id = str((body or {}).get("room_id") or "").strip()
        if not room_id.startswith("!"):
            return 400, {"error": "无效的频道 id"}

        from cosmac import registration

        # ① 平台管理员：直接接管，不看频道有没有主。
        if self._is_platform_admin(user_id):
            return registration.make_room_admin(
                self.config.homeserver_url, room_id, user_id
            )

        # ② 普通用户：仅当本人是该频道成员、且频道当前「无主」才放行认领。
        if not self.client.is_joined_member(room_id, user_id):
            return 403, {"error": "你不是该频道成员，无法认领"}
        try:
            pl = self.client.get_state_event(room_id, "m.room.power_levels", "") or {}
        except Exception:
            # 读不到权限表(bot 未加入/网络错) → 保守拒绝，别乱授权。
            return 403, {"error": "无法读取该频道权限，暂不能认领"}
        bot = self.config.bot_user_id
        users = pl.get("users") or {}
        for uid, lvl in users.items():
            if uid == bot:
                continue  # bot 自己不算「主人」
            if isinstance(lvl, int) and lvl >= 50:
                # 已有真人管理员：本人就是的话直接放行(幂等)，否则拒绝抢权。
                if uid == user_id:
                    return 200, {"ok": True}
                return 403, {"error": "该频道已有管理员，无法认领"}
        # 无主 → 把本人提成管理员(借 bot 这个本地房间管理员的权限)。
        return registration.make_room_admin(
            self.config.homeserver_url, room_id, user_id
        )

    @staticmethod
    def _is_task_assignee(user_id: str, task: Any) -> bool:
        """user_id 是否是这条任务的**被指派者**（含真人+AI 共同执行）。

        与 handle_tasks_list 的可见性口径**完全一致**：比对 localpart，兼容 executor_ref 存
        全 id / 纯 localpart / 带不带 @。
        —— 这是「看得到 = 改得动」的关键：可见性放行了被指派者，改状态的鉴权也必须同样放行，
        否则被派单的人在看板点「开始」会 403（线上实测）。

        判定规则（前端 LiveView.assignedToMe 是同一份口径，改一处必须同步另一处）：
        - executor_kind=human 且有 ref → 只认 ref 指向本人（不扩权到 assignee，防误伤）；
        - 其余（executor 是 agent/workflow，或旧任务无 ref）→ 从 assignee 文本里提取
          ASCII 词逐个比对本人 localpart。**共同执行者**场景（负责人实报）：专班派单
          把任务派给 agent:social、assignee 写「社媒运营+duxiuzhen01」——AI 执行，但
          挂名真人也必须在自己看板看到并能推进，否则任务对真人"隐身"。
        """
        if not user_id:
            return False
        localpart = user_id.split(":", 1)[0].lstrip("@").lower()
        if not localpart:
            return False

        def _lp(s: str) -> str:
            return str(s or "").strip().lstrip("@").split(":")[0].lower()

        ref = str(getattr(task, "executor_ref", "") or "").strip()
        if getattr(task, "executor_kind", "") == "human" and ref:
            return _lp(ref) == localpart
        # AI/workflow 执行 或 无类型化执行者：assignee 里挂的真人=共同执行者。
        # 按「非 localpart 合法字符」切词(中文角色名/+、/、空格都算分隔)，任一词等于本人即命中；
        # 词内再过 _lp 兼容 @xx:server 全 id 写法。完整词相等、非子串——防 "du" 误配 "duxz"。
        a = str(getattr(task, "assignee", "") or "")
        for w in re.split(r"[^A-Za-z0-9._=@:\-]+", a):
            if w and _lp(w) == localpart:
                return True
        return False

    @staticmethod
    def _is_task_reviewer(user_id: str, task: Any) -> bool:
        """user_id 是否为这条任务指定的真人审核人。

        数据库历史上同时存在完整 Matrix ID 和纯 localpart，因此与执行人
        判定一样忽略「@」与 homeserver 后缀。只做完整 localpart 相等，
        不用子串匹配，避免短用户名误命中其他人。
        """
        reviewer = str(getattr(task, "reviewer_ref", "") or "").strip()
        if not user_id or not reviewer:
            return False

        def _localpart(value: str) -> str:
            """把 Matrix ID/用户名统一成小写 localpart。"""
            return str(value or "").strip().lstrip("@").split(":")[0].lower()

        return bool(_localpart(user_id)) and _localpart(user_id) == _localpart(
            reviewer
        )

    def _can_access_task(self, user_id: str, task: Any) -> bool:
        """判断 user_id 是否有权读/改这条任务。

        授权规则（任一成立即可）：① 平台管理员；② 任务由本人下达（task.sender）；
        ③ 任务**派给本人**（executor_ref/assignee 指向本人）——被指派者要能在看板推进自己的卡；
        ④ 本人是指定审核人；⑤ 本人是任务所属房间(task.room_id)的成员。
        任何不确定一律拒绝（fail-closed），
        防止任意登录用户靠遍历 id 越权读写别人工作区的任务看板。
        """
        if not user_id:
            return False
        if task.sender and task.sender == user_id:
            return True
        # 被指派者可改自己的任务（与看板可见性同口径，修「看得到却点不动 403」）。
        if self._is_task_assignee(user_id, task):
            return True
        # 审核人必须能看到卡片并执行“通过/打回”，即使 TA 不是执行人。
        if self._is_task_reviewer(user_id, task):
            return True
        if self._is_platform_admin(user_id):
            return True
        room_id = task.room_id or ""
        # is_joined_member 自身 fail-closed（查不到/异常都返回 False）。
        return bool(room_id) and self.client.is_joined_member(room_id, user_id)

    def handle_tasks_list(self, access_token: str) -> Tuple[int, Dict[str, Any]]:
        """任务看板：列出真实任务（AI 拆解登记的）。需登录，且只返回本人有权看的任务。"""
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        out: List[Dict[str, Any]] = []
        try:
            from cosmac.db import session_scope
            from cosmac.db.task_repo import list_tasks, list_tasks_for_user

            is_admin = self._is_platform_admin(user_id)
            with session_scope() as s:
                # 可见性(QA:成员看到了专班全部任务,应只看自己的):
                #   管理员=全部;本人下达的(sender)=全部可见(项目负责人要看全貌);
                #   其他人=只看**派给自己的**——executor_kind=human 且 executor_ref 是本人;
                #   旧任务(无类型化执行者)按 assignee 首词==本人 localpart 兜底。
                # 不再按"本人所在房间"放行——被拉进专班≠能看别人的任务。
                if is_admin:
                    visible = list_tasks(s)  # 管理员看全部（内部统计口径）
                else:
                    # #6：先在 DB 层把候选收敛到「本人相关任务」(宽松超集)，再用精确谓词收口——
                    # 避免旧实现「全局取最新 200 条→再按人过滤」在平台任务超 200 后把「派给我的」
                    # 挤出窗口而消失。localpart 与 _is_task_assignee 同一提取口径。
                    localpart = user_id.split(":", 1)[0].lstrip("@").lower()
                    candidates = list_tasks_for_user(
                        s, user_id=user_id, localpart=localpart,
                    )
                    # 可见性 = 本人下达 / 派给本人 / 由本人审核；与
                    # _can_access_task(改状态鉴权)**共用同一口径**
                    # (_is_task_assignee),保证「看得到 == 改得动」,不再各写一份而悄悄跑偏(线上踩过)。
                    visible = [
                        t for t in candidates
                        if (t.sender and t.sender == user_id)
                        or self._is_task_assignee(user_id, t)
                        or self._is_task_reviewer(user_id, t)
                    ]
                for t in visible:
                    out.append({
                        "id": t.id, "title": t.title, "assignee": t.assignee,
                        "status": t.status, "progress": t.progress,
                        "goal": t.goal, "result": t.result,
                        # 类型化执行者（档2）：看板据此显示"派给谁/什么"
                        "executor_kind": t.executor_kind, "executor_ref": t.executor_ref,
                        # 指定真人审核人及审核流程状态；前端用它显示
                        # “待谁审核”，不再把 AI 的交付误当成已完成。
                        "reviewer_ref": t.reviewer_ref,
                        "review_status": t.review_status,
                        # 所属频道：前端"删频道前提醒未完成任务"用它按房间统计
                        "room_id": t.room_id or "",
                        # 所属工作区：前端任务看板据此按工作区过滤（空=存量无归属，各处显示）
                        "space_id": getattr(t, "space_id", "") or "",
                        # 下达人：前端按工作区过滤时，"我下达的"(sender==本人)即便派给别人、且归属
                        # 工作区我进不去，也要显示——否则会弄丢（L11）。
                        "sender": t.sender or "",
                        # 截止时间（epoch 秒，可空）：看板据它显示"还剩几天/已逾期"。
                        "due_ts": t.due_ts,
                    })
        except Exception:
            logger.debug("读取任务失败", exc_info=True)
        return 200, {"tasks": out}

    def handle_task_update(
        self, access_token: str, body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """改任务状态/进度（看板手动拖卡）。需登录，且只能改本人有权的任务。"""
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        try:
            task_id = int(body.get("id"))
        except (TypeError, ValueError):
            return 400, {"error": "无效任务 id"}
        # 状态白名单 + 同义词归一化（M6）：非法 status 曾被 task_repo 静默丢弃，若同时给了别的
        # 字段就"假成功"，只给非法 status 则误报 404「任务不存在」（任务其实存在）。这里先拦。
        from cosmac.ai.tools import _normalize_task_status, _TASK_STATUSES
        status = _normalize_task_status(body.get("status"))
        if status is not None and status not in _TASK_STATUSES:
            return 400, {"error": "任务状态非法（只能是 待办/进行中/待审核/已完成）"}
        # 改期(负责人报:逾期提醒让去看板改期,看板却不支持)——due 语义:
        # 字段缺失=不动;空串=清除截止;'YYYY-MM-DD[ HH:MM]'=设置(解析失败给明确 400)。
        due_kwargs: Dict[str, Any] = {}
        if "due" in (body or {}):
            raw_due = str(body.get("due") or "").strip()
            if not raw_due:
                due_kwargs["due_ts"] = None  # 显式清除截止时间
            else:
                from cosmac.ai.tools import _parse_due_to_epoch

                ep = _parse_due_to_epoch(raw_due)
                if ep is None:
                    return 400, {"error": "截止时间格式无效(用 YYYY-MM-DD 或 YYYY-MM-DD HH:MM)"}
                due_kwargs["due_ts"] = ep
        try:
            from cosmac.db import session_scope
            from cosmac.db.task_repo import get_task, update_task

            with session_scope() as s:
                task = get_task(s, task_id)
                if task is None:
                    return 404, {"error": "任务不存在"}
                # 先校验归属再改，堵住「遍历 id 篡改全平台任务」。
                if not self._can_access_task(user_id, task):
                    return 403, {"error": "无权操作此任务"}
                reviewer = str(task.reviewer_ref or "").strip()
                review_status: Optional[str] = None
                message = ""
                # 看板上执行人原来的“完成”按钮不能再跳过审核。
                # 为了兼容旧客户端，非审核人仍发 done 时服务端不直接报错，
                # 而是安全转成 review/pending，并把真实状态返回给 UI。
                if status == "done" and reviewer:
                    if self._is_task_reviewer(user_id, task):
                        review_status = "approved"
                        message = "真人审核已通过"
                    else:
                        status = "review"
                        review_status = "pending"
                        message = f"已提交给 {reviewer} 审核"
                elif status == "review" and reviewer:
                    review_status = "pending"
                    message = f"已提交给 {reviewer} 审核"
                elif (
                    status == "doing"
                    and task.status == "review"
                    and reviewer
                    and self._is_task_reviewer(user_id, task)
                ):
                    review_status = "changes"
                    message = "已打回修改"
                ok = update_task(
                    s, task_id,
                    status=status,
                    progress=body.get("progress"),
                    result=body.get("result"),
                    review_status=review_status,
                    **due_kwargs,
                )
        except Exception:
            logger.exception("更新任务失败 id=%s", task_id)
            return 500, {"error": "更新失败"}
        # 任务确实存在（上面已 get 到）：ok=False 只能是「没有可更新字段」→ 400 而非误导性 404。
        return (
            (200, {
                "ok": True,
                "status": status,
                "review_status": review_status,
                "message": message,
            })
            if ok
            else (400, {"error": "没有可更新的内容"})
        )

    # —— 图文教程（全局图文内容，类公众号）：页面树 CRUD ——
    # 改版后是**全平台一份**(不分工作区)：所有页面存在固定的 _GLOBAL_DOC_ROOM 作用域下。
    # 鉴权：读 = 付费会员(门控 doc_read，默认 paid)；写 = 平台管理员(后台编辑)。服务端强制。
    _GLOBAL_DOC_ROOM = "__cosmac_global_docs__"
    # 平台级共享知识库(阶段2)的固定作用域(SCOPE_GLOBAL)。管理员后台维护、任何专班可绑
    # (channel_config.kbScopes 含 'platform')；与图文教程分开(那是"给人读的文章",这是"喂 AI 的资料")。
    _PLATFORM_KB_SCOPE = "__cosmac_platform_kb__"

    def _doc_can_read(self, user_id: str) -> bool:
        """能否查看图文教程：过 doc_read 门控（默认付费会员；平台管理员永远放行）。"""
        return self._gate_allows(user_id, "doc_read")

    def _doc_can_write(self, user_id: str) -> bool:
        """能否编辑图文教程：仅平台管理员（全局内容，统一在后台编辑）。"""
        return self._is_platform_admin(user_id)

    def handle_doc_tree(self, access_token: str) -> Tuple[int, Dict[str, Any]]:
        """列出全局图文页面树（不含正文，省流量）。需付费会员可读。"""
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        if not self._doc_can_read(user_id):
            return 403, {"error": self._gate_denied_text("doc_read", ui=True), "locked": True}
        can_write = self._doc_can_write(user_id)
        try:
            from cosmac.db import session_scope
            from cosmac.db.doc_repo import list_pages, page_to_dict

            with session_scope() as s:
                # 后台编辑(可写)能看草稿；前台只读用户只看已发布。
                rows = list_pages(
                    s, self._GLOBAL_DOC_ROOM, published_only=not can_write
                )
                pages = [page_to_dict(p) for p in rows]
        except Exception:
            logger.exception("读取图文树失败")
            return 500, {"error": "读取失败"}
        return 200, {"pages": pages, "can_write": can_write}

    def handle_doc_page(
        self, access_token: str, page_id: int
    ) -> Tuple[int, Dict[str, Any]]:
        """读单页（含正文 Markdown）。需付费会员可读。"""
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        if not self._doc_can_read(user_id):
            return 403, {"error": self._gate_denied_text("doc_read", ui=True), "locked": True}
        can_write = self._doc_can_write(user_id)
        try:
            from cosmac.db import session_scope
            from cosmac.db.doc_repo import get_page, page_to_dict

            with session_scope() as s:
                page = get_page(s, page_id)
                # 只暴露全局图文里的页面（防越权读到别处遗留的 room 数据）
                if page is None or page.room_id != self._GLOBAL_DOC_ROOM:
                    return 404, {"error": "页面不存在"}
                # 草稿只有可编辑者(管理员)能看；前台读者看不到未发布的。
                if not page.published and not can_write:
                    return 404, {"error": "页面不存在"}
                data = page_to_dict(page, with_content=True)
        except Exception:
            logger.exception("读取图文页失败 id=%s", page_id)
            return 500, {"error": "读取失败"}
        data["can_write"] = can_write
        return 200, data

    def handle_doc_create(
        self, access_token: str, body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """新建页面（写进全局图文）。仅平台管理员。"""
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        if not self._doc_can_write(user_id):
            return 403, {"error": "仅平台管理员可编辑图文教程"}
        room_id = self._GLOBAL_DOC_ROOM
        try:
            from cosmac.db import session_scope
            from cosmac.db.doc_repo import create_page, page_to_dict

            with session_scope() as s:
                page = create_page(
                    s, room_id=room_id,
                    title=str(body.get("title") or ""),
                    parent_id=body.get("parent_id"),
                    content_md=str(body.get("content_md") or ""),
                    cover=str(body.get("cover") or ""),
                    updated_by=user_id,
                )
                if page is None:
                    return 400, {"error": "新建失败（父页面非法或页面数超限）"}
                data = page_to_dict(page, with_content=True)
        except Exception:
            logger.exception("新建图文页失败")
            return 500, {"error": "新建失败"}
        # 新建页默认是草稿，不进知识库；发布(handle_doc_update published=true)时才入库。
        return 200, data

    def _doc_write_op(
        self, access_token: str, page_id_raw: Any
    ) -> Tuple[Optional[str], Optional[int], str, Optional[Tuple[int, Dict[str, Any]]]]:
        """改/删/移动的公共前置：验明身份(平台管理员) + 取页面 + 校验属于全局图文。

        成功返回 (user_id, page_id, room_id, None)；失败返回 (None, None, "", (状态码, body))。
        """
        user_id = self.client.whoami(access_token)
        if not user_id:
            return None, None, "", (401, {"error": "登录已失效，请重新登录"})
        if not self._doc_can_write(user_id):
            return None, None, "", (403, {"error": "仅平台管理员可编辑图文教程"})
        try:
            page_id = int(page_id_raw)
        except (TypeError, ValueError):
            return None, None, "", (400, {"error": "无效页面 id"})
        from cosmac.db import session_scope
        from cosmac.db.doc_repo import get_page

        with session_scope() as s:
            page = get_page(s, page_id)
            if page is None or page.room_id != self._GLOBAL_DOC_ROOM:
                return None, None, "", (404, {"error": "页面不存在"})
            room_id = page.room_id
        return user_id, page_id, room_id, None

    # —— 文档页 ↔ 知识库 同步（P2 AI 答疑：把教学文档喂进 KB，按工作区 room 作用域）——

    def _doc_sync_kb(self, room_id: str, page_id: int, title: str, content: str) -> None:
        """把一个文档页同步进知识库：先按 source 清旧、再重灌（best-effort，失败不影响保存）。"""
        try:
            from cosmac.db import session_scope
            from cosmac.db.kb import delete_by_source, ingest_document
            from cosmac.db.models import SCOPE_ROOM

            src = f"docpage:{page_id}"
            with session_scope() as s:
                delete_by_source(s, scope=SCOPE_ROOM, scope_id=room_id, source=src)
                if (content or "").strip():
                    ingest_document(
                        s, scope=SCOPE_ROOM, scope_id=room_id,
                        title=title or "未命名页面", source=src, text=content,
                    )
        except Exception:
            logger.debug("文档页同步知识库失败（忽略） page=%s", page_id, exc_info=True)

    def _doc_remove_kb(self, room_id: str, page_ids: List[int]) -> None:
        """删页面后，从知识库移除对应文档（best-effort）。"""
        try:
            from cosmac.db import session_scope
            from cosmac.db.kb import delete_by_source
            from cosmac.db.models import SCOPE_ROOM

            with session_scope() as s:
                for pid in page_ids:
                    delete_by_source(
                        s, scope=SCOPE_ROOM, scope_id=room_id, source=f"docpage:{pid}"
                    )
        except Exception:
            logger.debug("文档页从知识库移除失败（忽略）", exc_info=True)

    def handle_doc_update(
        self, access_token: str, body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """改页面标题/正文。需该频道 power≥50。"""
        user_id, page_id, room_id, err = self._doc_write_op(access_token, body.get("id"))
        if err:
            return err
        try:
            from cosmac.db import session_scope
            from cosmac.db.doc_repo import page_to_dict, update_page

            with session_scope() as s:
                page = update_page(
                    s, page_id,
                    title=body.get("title"),
                    content_md=body.get("content_md"),
                    cover=body.get("cover"),
                    published=body.get("published"),
                    updated_by=user_id,
                )
                if page is None:
                    return 404, {"error": "页面不存在"}
                data = page_to_dict(page, with_content=True)
        except Exception:
            logger.exception("更新文档页失败 id=%s", page_id)
            return 500, {"error": "更新失败"}
        # 知识库随发布状态同步：已发布→入库(供 AI 答疑)；草稿→从库移除。
        if data.get("published"):
            self._doc_sync_kb(room_id, data["id"], data["title"], data.get("content_md") or "")
        else:
            self._doc_remove_kb(room_id, [data["id"]])
        return 200, data

    def handle_doc_delete(
        self, access_token: str, body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """删页面（连同其子树）。需该频道 power≥50。"""
        _user_id, page_id, room_id, err = self._doc_write_op(access_token, body.get("id"))
        if err:
            return err
        try:
            from cosmac.db import session_scope
            from cosmac.db.doc_repo import delete_page

            with session_scope() as s:
                deleted = delete_page(s, page_id)
        except Exception:
            logger.exception("删除文档页失败 id=%s", page_id)
            return 500, {"error": "删除失败"}
        self._doc_remove_kb(room_id, deleted)  # 同步从知识库移除被删页面
        return 200, {"ok": True, "deleted": deleted}

    def handle_doc_move(
        self, access_token: str, body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """移动页面到新父级/改排序（拖拽）。需该频道 power≥50。"""
        _user_id, page_id, _room_id, err = self._doc_write_op(access_token, body.get("id"))
        if err:
            return err
        try:
            from cosmac.db import session_scope
            from cosmac.db.doc_repo import move_page, page_to_dict

            with session_scope() as s:
                page = move_page(
                    s, page_id,
                    parent_id=body.get("parent_id"),
                    sort=body.get("sort"),
                )
                if page is None:
                    return 400, {"error": "移动失败（目标非法或会形成循环）"}
                data = page_to_dict(page)
        except Exception:
            logger.exception("移动文档页失败 id=%s", page_id)
            return 500, {"error": "移动失败"}
        return 200, data

    def handle_doc_draft(
        self, access_token: str, body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """让 AI 按主题写一篇图文草稿（Markdown），返回给后台编辑器填入。仅平台管理员。"""
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        if not self._doc_can_write(user_id):
            return 403, {"error": "仅平台管理员可用"}
        topic = str(body.get("topic") or "").strip()[:2000]
        if not topic:
            return 400, {"error": "请填写文章主题"}
        existing = str(body.get("existing") or "").strip()[:8000]
        # 用后台下发的运行时模型（provider/model 热配置）
        self._apply_runtime_config()
        sys = (
            "你是专业的公众号图文作者。根据用户给的主题写一篇结构清晰、可读性强的中文文章，"
            "用 Markdown 输出：以 # 一级标题开头，配 ## 小标题、要点列表、必要的示例/代码块。"
            "排版利落、信息密度高；只输出文章正文本身，不要寒暄、不要额外说明。"
        )
        user = f"主题：{topic}"
        if existing:
            user += f"\n\n请在以下已有内容基础上改进/续写（保留有用部分）：\n{existing}"
        try:
            from cosmac.ai.base import Message
            out = self.llm.complete(
                [Message(role="system", content=sys), Message(role="user", content=user)]
            )
        except Exception:
            logger.exception("AI 写图文草稿失败")
            return 502, {"error": "AI 生成失败，请稍后重试"}
        md = (out or "").strip()
        if not md:
            return 502, {"error": "AI 没有返回内容，请重试"}
        return 200, {"markdown": md}

    def handle_ruledoc_draft(
        self, access_token: str, body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """「AI 一键写」频道规则文档:按频道上下文生成 Markdown 工作规范草稿(负责人需求)。

        权限:该频道管理员(power≥50)或平台管理员——与"谁能写规则"同口径。
        生成不落库:返回给前端填进编辑区,用户可改,保存走既有自动保存。
        上下文喂给 AI:频道名/简介/人设/条目规则/绑定智能体/知识库文档标题——让规范贴合
        这个频道的真实用途,而不是通用模板。
        """
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        room_id = str((body or {}).get("room_id") or "").strip()
        if not room_id.startswith("!"):
            return 400, {"error": "无效的频道 id"}
        # 频道管理员 或 平台管理员
        allowed = self._is_platform_admin(user_id)
        if not allowed:
            try:
                pl = self.client.get_state_event(room_id, "m.room.power_levels", "") or {}
                users = pl.get("users") or {}
                allowed = int(users.get(user_id, pl.get("users_default", 0)) or 0) >= 50
            except Exception:
                allowed = False
        if not allowed:
            return 403, {"error": "需要本频道管理员权限"}
        if not self._gate_allows(user_id, "ai_chat"):
            return 403, {"error": self._gate_denied_text("ai_chat", ui=True)}
        notes = str(body.get("notes") or "").strip()[:1000]
        existing = str(body.get("existing") or "").strip()[:4000]
        # 频道上下文(每块兜异常,拿不到就少喂)
        ctx_lines: List[str] = []
        try:
            name_ev = self.client.get_state_event(room_id, "m.room.name") or {}
            if name_ev.get("name"):
                ctx_lines.append(f"频道名:{name_ev['name']}")
            topic_ev = self.client.get_state_event(room_id, "m.room.topic") or {}
            if topic_ev.get("topic"):
                ctx_lines.append(f"频道简介:{topic_ev['topic']}")
        except Exception:
            pass
        try:
            gctx = self._group_context(room_id)
            if gctx.get("persona"):
                ctx_lines.append(f"AI 人设:{str(gctx['persona'])[:400]}")
            if gctx.get("channel_rules"):
                ctx_lines.append(f"现有条目规则:\n{gctx['channel_rules']}")
            if gctx.get("worker_slugs"):
                ctx_lines.append("绑定智能体:" + "、".join(gctx["worker_slugs"]))
        except Exception:
            pass
        try:
            from cosmac.db import kb as kb_mod, session_scope
            from cosmac.db.models import SCOPE_ROOM

            with session_scope() as s:
                titles = [d.title for d in kb_mod.list_docs(
                    s, scope=SCOPE_ROOM, scope_id=room_id)][:10]
            if titles:
                ctx_lines.append("频道知识库文档:" + "、".join(titles))
        except Exception:
            pass
        self._apply_runtime_config()
        sys = (
            "你是企业 AI 协作平台的规范撰写专家。为一个频道撰写「频道规则文档」——"
            "该文档会每轮全文注入这个频道的 AI,相当于它的工作宪法。"
            "用 Markdown 输出,结构建议:# 标题、## 身份与定位、## 工作流程、## 输出规范、"
            "## 禁区与边界。内容必须贴合下面给出的频道上下文,具体、可执行,不写空话。"
            "**全文严格控制在 3500 字以内**。只输出文档正文,不要寒暄或额外说明。"
        )
        user = "频道上下文:\n" + ("\n".join(ctx_lines) or "(无,按通用协作频道写)")
        if notes:
            user += f"\n\n负责人补充要求:{notes}"
        if existing:
            user += f"\n\n在以下已有文档基础上改进(保留有用部分):\n{existing}"
        try:
            from cosmac.ai.base import Message
            out = self.llm.complete(
                [Message(role="system", content=sys), Message(role="user", content=user)]
            )
        except Exception:
            logger.exception("AI 写频道规则文档失败")
            return 502, {"error": "AI 生成失败，请稍后重试"}
        md = (out or "").strip()[:4000]
        if not md:
            return 502, {"error": "AI 没有返回内容，请重试"}
        return 200, {"markdown": md}

    def handle_pay_me(self, access_token: str) -> Tuple[int, Dict[str, Any]]:
        """查"我当前的会员状态"（升级弹窗顶部展示）。验明身份 → 返回当前生效等级 + 到期。"""
        from cosmac.members import active_tier, tier_label

        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        rec = self.members.get_record(user_id)
        tier = active_tier(rec)
        # 已过期回落 free 时，不再返回旧 expires_ts——否则前端显示"免费会员，到期 <过去日期>"
        # 这种自相矛盾的组合（审查 bug#13）。
        exp = int(rec.get("expires_ts") or 0) if (rec and tier != "free") else 0
        return 200, {"tier": tier, "tier_label": tier_label(tier), "expires_ts": exp}

    def handle_lifetime_activate(
        self, access_token: str, body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """兑换当前 OEM 节点的终身会员激活码。

        Nexus 先原子冻结“码 → 用户”；若 Matrix state 短暂写失败，
        同一用户重试是幂等的，不会把码转给其他账号。
        """
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        activation_code = str((body or {}).get("activation_code", "")).strip()
        if not activation_code:
            return 400, {"error": "请输入终身会员激活码"}
        try:
            from cosmac import nexus_link

            result = nexus_link.activate_lifetime_membership(
                activation_code,
                user_id,
                str((body or {}).get("device_id", "")),
            )
        except nexus_link.LifetimeActivationError as exc:
            return 400, {"error": str(exc)}
        except Exception:
            logger.exception("终身会员激活请求失败 user=%s", user_id)
            return 503, {"error": "激活服务暂时不可用，请稍后重试"}
        if not self.members.grant(
            user_id, "paid", source="oem_lifetime_code", expires_ts=0
        ):
            return 503, {
                "error": "激活码已绑定当前账号，但会员状态写入失败；请重试即可补写",
                "retryable": True,
            }
        return 200, {
            "ok": True,
            "tier": "paid",
            "tier_label": "付费会员",
            "expires_ts": 0,
            "already_activated": bool(result.get("already_activated")),
        }

    # —— Token 钱包端点（模块4 Token 经济 1c/1d：前端够不到 cosmac DB，经 bot 读写）——

    def handle_wallet_me(self, access_token: str) -> Tuple[int, Dict[str, Any]]:
        """查"我的 token 钱包"：余额 + 今日免费额度 + 公开配置 + 充值包（钱包面板一次拉全）。

        总开关关着也返回（enabled=false），前端据此隐藏/置灰入口——不用另设探测端点。
        """
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        cfg = self.wallet.config()
        try:
            balance = self.wallet.balance(user_id)
            free = self.wallet.free_daily_status(user_id)
        except Exception:
            logger.exception("读钱包失败 user=%s", user_id)
            return 500, {"error": "读取钱包失败，请稍后再试"}
        return 200, {
            "enabled": bool(cfg.get("enabled")),
            "balance": balance,
            "free_daily": free,
            "tokens_per_yuan": int(cfg.get("tokens_per_yuan") or 1000),
            # 管理员豁免只覆盖平台内置 AI 用量；创作者付费商品仍按审核标价结算。
            "exempt": self._is_platform_admin(user_id),
            "packages": [
                {"slug": p["slug"], "name": p["name"], "tokens": p["tokens"],
                 "prices": p["prices"]}
                for p in self.wallet.packages()
            ],
        }

    def handle_wallet_ledger(
        self, access_token: str, limit: int = 50, offset: int = 0
    ) -> Tuple[int, Dict[str, Any]]:
        """查"我的 token 流水"（新→旧分页）——收支明细就是"钱花哪了"的答案。"""
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        try:
            items = self.wallet.ledger(user_id, limit=limit, offset=offset)
        except Exception:
            logger.exception("读流水失败 user=%s", user_id)
            return 500, {"error": "读取流水失败，请稍后再试"}
        return 200, {"items": items}

    def handle_wallet_checkout(
        self, access_token: str, body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """token 充值下单：验明身份 → 建 token 订单 → 返回支付方式（与会员下单同骨架）。"""
        from cosmac.trading.service import OrderError

        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        if not self.wallet.enabled():
            return 400, {"error": "token 充值暂未开放"}
        package_slug = str(body.get("package_slug") or "")
        currency = str(body.get("currency") or "cny")
        provider = str(body.get("provider") or "manual")
        try:
            res = self.orders.create_token_order(
                user_id=user_id, package_slug=package_slug,
                currency=currency, provider=provider,
            )
        except OrderError as e:
            return 400, {"error": str(e)}
        except Exception:
            logger.exception("token 下单失败 user=%s pkg=%s", user_id, package_slug)
            return 500, {"error": "下单失败，请稍后再试"}
        co = res["checkout"]
        return 200, {
            "order_no": res["order_no"], "amount_cents": res["amount_cents"],
            "currency": res["currency"], "tokens": res["tokens"],
            "checkout": {"kind": co.kind, "url": co.url, "address": co.address,
                         "extra": co.extra},
        }

    def handle_wallet_admin_adjust(
        self, access_token: str, body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """管理员手动加/减某用户 token（后台「Token 经济」页用）。服务端强制管理员身份。"""
        operator = self.client.whoami(access_token)
        if not operator:
            return 401, {"error": "登录已失效，请重新登录"}
        if not self._is_platform_admin(operator):
            return 403, {"error": "仅平台管理员可操作"}
        target = str(body.get("user_id") or "").strip()
        if not target.startswith("@") or ":" not in target:
            return 400, {"error": "请填写完整用户 ID（@user:域名）"}
        target_error = self._validate_wallet_target(target)
        if target_error is not None:
            return target_error
        try:
            delta = int(body.get("delta"))
        except (TypeError, ValueError):
            return 400, {"error": "调整数量必须是整数（正=加、负=减）"}
        if delta == 0:
            return 400, {"error": "调整数量不能为 0"}
        note = str(body.get("note") or "")[:200]
        try:
            new_bal = self.wallet.adjust(target, delta, note=note, operator=operator)
        except Exception:
            logger.exception("管理员调整 token 失败 target=%s delta=%s", target, delta)
            return 500, {"error": "调整失败，请稍后再试"}
        if new_bal is None:
            return 400, {"error": "对方余额不足，无法扣减该数量"}
        logger.info("管理员 %s 调整 %s token %+d，新余额 %s", operator, target, delta, new_bal)
        return 200, {"ok": True, "user_id": target, "balance": new_bal}

    def handle_wallet_admin_balance(
        self, access_token: str, target: str
    ) -> Tuple[int, Dict[str, Any]]:
        """管理员查某用户余额 + 最近流水（后台调整前先看一眼）。"""
        operator = self.client.whoami(access_token)
        if not operator:
            return 401, {"error": "登录已失效，请重新登录"}
        if not self._is_platform_admin(operator):
            return 403, {"error": "仅平台管理员可操作"}
        t = str(target or "").strip()
        if not t.startswith("@") or ":" not in t:
            return 400, {"error": "请填写完整用户 ID（@user:域名）"}
        target_error = self._validate_wallet_target(t)
        if target_error is not None:
            return target_error
        try:
            return 200, {
                "user_id": t,
                "balance": self.wallet.balance(t),
                "items": self.wallet.ledger(t, limit=20),
            }
        except Exception:
            logger.exception("管理员查钱包失败 target=%s", t)
            return 500, {"error": "查询失败，请稍后再试"}

    def _validate_wallet_target(
        self, target: str
    ) -> Optional[Tuple[int, Dict[str, Any]]]:
        """校验后台钱包目标是当前节点中真实存在的本地账号。

        旧逻辑只看字符串里有没有 ``@``/``:``，因此 ``@duxz03:dev-cs`` 这类写错账号域
        的 ID 也会直接建钱包、记流水。真实用户以完整 Matrix ID 登录，两个字符串对应
        两只不同钱包，就会出现“后台 200、用户 0”。这里在任何写账/查询前同时校验账号域
        和 Synapse 用户存在性；Synapse 暂时不可达时 fail-closed，宁可稍后重试也不写错账。

        参数：
            target: 管理员输入的完整 Matrix ID。
        返回：
            合法时返回 ``None``；非法时返回可直接作为 HTTP 响应的 ``(状态码, JSON)``。
        """
        localpart, sep, server = target[1:].partition(":")
        expected_server = str(self.config.server_name or "").strip().lower()
        if not sep or not localpart or not server:
            return 400, {"error": "请填写完整用户 ID（@user:域名）"}
        if expected_server and server.lower() != expected_server:
            expected = f"@{localpart}:{self.config.server_name}"
            return 400, {
                "error": f"账号域不属于当前节点，请填写完整用户 ID，例如 {expected}"
            }
        exists = self.client.user_exists(target)
        if exists is False:
            return 404, {"error": f"用户不存在：{target}，请从用户列表复制完整 ID"}
        if exists is None:
            return 503, {"error": "暂时无法核验用户，请稍后重试；本次没有调整余额"}
        return None

    def handle_register_request_code(
        self, body: Dict[str, Any], client_ip: str = ""
    ) -> Tuple[int, Dict[str, Any]]:
        """自建邮箱注册：给邮箱发验证码（公开端点，无 token——用户还没账号）。限频在 registration 内强制。"""
        from cosmac import node_activation
        if not node_activation.allows_public_access():
            return 423, {"error": "节点尚未激活，暂不开放注册"}
        from cosmac import registration
        b0 = body or {}
        return registration.request_code(
            str(b0.get("email") or ""),
            client_ip=client_ip,
            turnstile=str(b0.get("turnstile") or ""),
            referral_code=str(b0.get("referral_code") or ""),
        )

    def handle_register_verify(
        self, body: Dict[str, Any], client_ip: str = ""
    ) -> Tuple[int, Dict[str, Any]]:
        """自建邮箱注册：验码 + 用共享密钥建号（公开端点）。成功回 {user_id, access_token...}。"""
        from cosmac import node_activation
        if not node_activation.allows_public_access():
            return 423, {"error": "节点尚未激活，暂不开放注册"}
        from cosmac import registration
        b = body or {}
        return registration.verify_and_register(
            b.get("email", ""),
            b.get("code", ""),
            b.get("username", ""),
            b.get("password", ""),
            hs_url=self.config.homeserver_url,
            client_ip=client_ip,
            referral_code=str(b.get("referral_code") or ""),
        )

    def handle_reset_request_code(
        self, body: Dict[str, Any], client_ip: str = ""
    ) -> Tuple[int, Dict[str, Any]]:
        """找回密码：给邮箱发验证码（公开端点；防枚举：未注册也回成功但不发信）。"""
        from cosmac import registration
        b0 = body or {}
        return registration.reset_request_code(
            b0.get("email", ""), client_ip=client_ip, turnstile=b0.get("turnstile", ""),
        )

    def handle_reset_verify(
        self, body: Dict[str, Any], client_ip: str = ""
    ) -> Tuple[int, Dict[str, Any]]:
        """找回密码：验码 + 用管理员令牌重置密码（公开端点）。成功回 {ok}。"""
        from cosmac import registration
        b = body or {}
        return registration.reset_verify(
            b.get("email", ""), b.get("code", ""), b.get("password", ""),
            hs_url=self.config.homeserver_url, server_name=self.config.server_name,
            client_ip=client_ip,
        )

    def handle_login_email(
        self, body: Dict[str, Any], client_ip: str = ""
    ) -> Tuple[int, Dict[str, Any]]:
        """邮箱登录：反查用户名 → 登 Synapse → 返回登录响应（公开端点）。"""
        from cosmac import registration
        from cosmac import node_activation
        b = body or {}
        # 受限态只允许安装时配置的 bootstrap 管理员邮箱进入激活页。
        if not node_activation.allows_public_access() and str(b.get("email") or "").strip().lower() != os.environ.get("COSMAC_ADMIN_EMAIL", "").strip().lower():
            return 423, {"error": "节点尚未激活，请由首次管理员完成激活"}
        return registration.login_email(
            str(b.get("email") or ""), str(b.get("password") or ""),
            hs_url=self.config.homeserver_url, client_ip=client_ip,
            code=str(b.get("code") or ""),   # 阶段2:异地二次验证的邮箱验证码(第二步才带)
            server_name=self.config.server_name,  # 停用检测要用它拼 @user:server_name
        )

    def handle_login_account(
        self, body: Dict[str, Any], client_ip: str = ""
    ) -> Tuple[int, Dict[str, Any]]:
        """账号（用户名+密码）登录**收口**：经后端代理 Synapse 登录 + IP 限频 + 记审计（公开端点）。
        原来前端直连 Synapse，后端看不到登录；收口后账号登录与邮箱登录同一道防线。"""
        from cosmac import registration
        from cosmac import node_activation
        b = body or {}
        bootstrap = os.environ.get("COSMAC_ADMIN_USER", "admin").strip().lower()
        identifier = str(b.get("username") or "").strip().lower()
        if not node_activation.allows_public_access() and identifier not in (
            bootstrap,
            f"@{bootstrap}:{self.config.server_name}".lower(),
        ):
            return 423, {"error": "节点尚未激活，请由首次管理员完成激活"}
        # str() 归一:JSON 里 username 传成数字/对象时,registration 端的 .strip() 会 AttributeError
        # → 连接被掐(无响应)。这里统一成字符串(低⑤)。
        return registration.login_account(
            str(b.get("username") or ""), str(b.get("password") or ""),
            hs_url=self.config.homeserver_url, client_ip=client_ip,
            code=str(b.get("code") or ""),   # 阶段2:异地二次验证的邮箱验证码(第二步才带)
            server_name=self.config.server_name,  # 停用检测要用它拼 @user:server_name
        )

    def handle_node_activation_status(self) -> Tuple[int, Dict[str, Any]]:
        """返回不含授权码的节点激活状态，登录页据此决定是否跳转激活页。"""
        from cosmac import node_activation
        return 200, node_activation.status()

    def handle_node_activate(self, access_token: str) -> Tuple[int, Dict[str, Any]]:
        """仅 bootstrap 管理员可触发服务器代办激活，KEY 永不经过浏览器。"""
        user_id = self.client.whoami(access_token)
        expected = "@%s:%s" % (
            os.environ.get("COSMAC_ADMIN_USER", "admin").strip(),
            self.config.server_name,
        )
        if user_id != expected:
            return 403, {"error": "仅首次管理员可以激活此节点"}
        from cosmac import node_activation
        try:
            return 200, node_activation.activate(self.config)
        except RuntimeError as error:
            return 503, {"error": str(error)}

    def handle_kb_list_mine(self, access_token: str) -> Tuple[int, Dict[str, Any]]:
        """列出本人**个人知识库**文档（标题）。给 AI 侧栏「项目文件」展示真实知识库用。需登录。"""
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        docs: List[Dict[str, Any]] = []
        try:
            from cosmac.db import kb, session_scope
            from cosmac.db.models import SCOPE_USER

            with session_scope() as s:
                for d in kb.list_docs(s, scope=SCOPE_USER, scope_id=user_id):
                    # id 给「知识库管理」UI 删除用；title/source 给展示用
                    docs.append({"id": d.id, "title": d.title, "source": d.source})
        except Exception:
            logger.debug("列知识库失败", exc_info=True)
        return 200, {"docs": docs}

    def handle_onboard_ingest_kb(
        self, access_token: str, body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """入驻引导：把模板预置文档灌进**本人个人知识库**(scope=USER)。需登录。

        个人库 → bot 在该用户任何房间检索 RAG 时都会带上，所以模板知识全工作区可用。
        best-effort：DB/embedder 出问题也回 200、不阻断引导（前端只当少灌了几篇）。
        """
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        docs = (body or {}).get("docs")
        if not isinstance(docs, list):
            return 400, {"error": "docs 无效"}
        # 安全（#3）：本端点全信客户端传的 docs，正常引导与恶意刷库无法从请求上区分，故必须套用
        # 与 handle_kb_add **完全一致**的服务端硬闸——知识库门控 + 单篇字数上限 + 篇数会员配额
        # + 存储空间配额，否则免费用户可绕开所有闸往个人库灌满 200 篇、每篇近 512KB 的文档。
        # best-effort：任一道闸拦下只是少灌/不灌，一律回 200 不打断引导（前端本就忽略结果）。
        if not self._gate_allows(user_id, "knowledge"):
            return 200, {"ingested": 0}  # 知识库门控未过 → 静默不灌，不用 403 打断引导
        from cosmac.db.kb_cmd import MAX_DOC_CHARS, MAX_DOCS_PER_SCOPE

        kb_limit = self._quota_limit(user_id, "kb_docs")       # 篇数会员配额（-1=不限）
        st_limit = self._quota_limit(user_id, "storage_mb")    # 存储空间配额 MB（-1=不限）
        used_bytes = self._storage_bytes(user_id)              # 起始已用存量（媒体+个人库）
        ingested = 0
        try:
            from cosmac.db import kb, session_scope
            from cosmac.db.models import SCOPE_USER

            with session_scope() as s:
                count = len(kb.list_docs(s, scope=SCOPE_USER, scope_id=user_id))
                for d in docs[:50]:  # 一次最多灌 50 篇，防滥用
                    # 篇数：会员配额与系统硬上限双闸，任一到顶即停
                    if kb_limit >= 0 and count >= kb_limit:
                        break
                    if count >= MAX_DOCS_PER_SCOPE:
                        break
                    title = str((d or {}).get("title") or "").strip()
                    text = str((d or {}).get("content") or "").strip()
                    if not title or not text:
                        continue
                    if len(text) > MAX_DOC_CHARS:  # 单篇超长：跳过（不截断，避免灌半截脏数据）
                        continue
                    # 存储配额：加这篇会超上限就停（与 handle_kb_add 同口径，本地累加不吃缓存）
                    if st_limit >= 0 and used_bytes + self._blen(text) > st_limit * 1048576:
                        break
                    kb.ingest_document(
                        s, scope=SCOPE_USER, scope_id=user_id,
                        title=title, source="onboarding", text=text,
                    )
                    used_bytes += self._blen(text)
                    count += 1
                    ingested += 1
        except Exception:
            logger.exception("入驻知识库入库失败")
        if ingested:
            self._storage_cache = {}  # 存量变了，作废 60s 缓存（与 handle_my_* 一致）
        return 200, {"ingested": ingested}

    def handle_kb_add(
        self, access_token: str, body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """「知识库管理」UI：把一篇文档(标题+正文)加进**本人个人知识库**。需登录 + knowledge 门控。

        与入驻批量灌库不同，这是用户在 UI 里逐篇添加，要返回真实成功/失败与数量上限提示。
        """
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        # 知识库门控：与「知识」命令、RAG 同一道 knowledge 闸（低等级用户被挡时给升级提示）
        if not self._gate_allows(user_id, "knowledge"):
            return 403, {"error": self._gate_denied_text("knowledge", ui=True)}
        title = str((body or {}).get("title") or "").strip()
        content = str((body or {}).get("content") or "").strip()
        if not content:
            return 400, {"error": "正文不能为空"}
        from cosmac.db.kb_cmd import MAX_DOC_CHARS, MAX_DOCS_PER_SCOPE

        if len(content) > MAX_DOC_CHARS:
            return 400, {"error": f"正文太长（{len(content)} 字），上限 {MAX_DOC_CHARS} 字，请拆成多篇"}
        # 用量配额（变现第二步）：知识库文档数按会员等级限。-1=不限；硬上限 MAX_DOCS_PER_SCOPE 兜底。
        # 存储空间配额(字节):个人库入库走服务端,这里硬管控(附件那条链路只能前端软管控)。
        st_limit = self._quota_limit(user_id, "storage_mb")
        if st_limit >= 0 and self._storage_bytes(user_id) + self._blen(content) > st_limit * 1048576:
            return 400, {"error": f"存储空间不足（上限 {st_limit}MB）。删除一些内容或升级会员扩容。"}
        kb_limit = self._quota_limit(user_id, "kb_docs")
        try:
            from cosmac.db import kb, session_scope
            from cosmac.db.models import SCOPE_USER

            with session_scope() as s:
                # 同名=覆盖更新(与频道库同口径,负责人实报重复上传不去重)
                replaced = kb.delete_docs_by_title(
                    s, scope=SCOPE_USER, scope_id=user_id, title=title)
                # kb_docs 口径含本人建的频道库(负责人:频道资源计入建者额度)——
                # 与「我的额度」展示同源。覆盖同名不算新增,故 replaced>0 时不判满。
                cur = self._kb_docs_used(s, user_id)
                if kb_limit >= 0 and replaced == 0 and cur >= kb_limit:
                    return 400, {"error": f"知识库已满（{cur}/{kb_limit} 篇，含你建的各频道）。升级会员可扩容。"}
                # 系统硬上限是「每作用域」的(防单库爆炸),数个人库本身、不含频道
                if len(kb.list_docs(s, scope=SCOPE_USER, scope_id=user_id)) >= MAX_DOCS_PER_SCOPE:
                    return 400, {"error": f"知识库已达系统上限（{MAX_DOCS_PER_SCOPE} 篇），先删一些再加"}
                doc = kb.ingest_document(
                    s, scope=SCOPE_USER, scope_id=user_id,
                    title=title, source="upload", text=content,
                )
                # 在 session 内取出需要的标量值返回（关闭后惰性加载会报错）
                out = {"ok": True, "id": doc.id, "title": doc.title,
                       "chunks": len(doc.chunks), "replaced": replaced}
            self._storage_cache = {}  # L3：个人库存量变了，作废 60s 缓存（与工坊路径一致）
            return 200, out
        except Exception:
            logger.exception("知识库入库失败（UI 添加）")
            return 500, {"error": "入库失败（数据库不可用？）"}

    def handle_kb_delete(
        self, access_token: str, body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """「知识库管理」UI：删除本人个人知识库里的一篇文档（按 id）。需登录。

        **越权防护**：只能删 scope=user 且 scope_id==本人 的文档，删不到别人的库/群库。
        删自己的数据不设 knowledge 门控（即便门槛被调高，用户也应能清理自己的数据）。
        """
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        try:
            doc_id = int((body or {}).get("id"))
        except (TypeError, ValueError):
            return 400, {"error": "文档 id 无效"}
        try:
            from cosmac.db import kb, session_scope
            from cosmac.db.models import SCOPE_USER, KnowledgeDoc

            with session_scope() as s:
                doc = s.get(KnowledgeDoc, doc_id)
                if doc is None or doc.scope != SCOPE_USER or doc.scope_id != user_id:
                    return 404, {"error": "没找到该文档（或不属于你）"}
                kb.delete_doc(s, doc_id)
            self._storage_cache = {}  # L3：删了个人库内容，作废存量缓存，「我的额度」即时反映
            return 200, {"ok": True}
        except Exception:
            logger.exception("知识库删除失败（UI）")
            return 500, {"error": "删除失败"}

    # —— 频道知识库（SCOPE_ROOM）：频道管理面板「知识库」页上传/列出/删除文档 ——
    # 与个人库的区别：作用域是**频道**(所有成员的 AI 检索都会带上)，故写/删限**频道管理员**(power≥50)，
    # 读限频道成员。上传的文档经 ingest_document 切块入库，本频道 AI 走 RAG 时自动命中(见 _kb_retrieve)。

    def handle_kb_room_list(
        self, access_token: str, room_id: str
    ) -> Tuple[int, Dict[str, Any]]:
        """列出本频道(SCOPE_ROOM)已上传的知识库文档。需登录 + 是该频道成员。"""
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        room_id = str(room_id or "").strip()
        if not room_id.startswith("!"):
            return 400, {"error": "无效的频道 id"}
        # 读也要是频道成员——别让任意登录用户遍历 room_id 拉别人频道的知识库清单。
        if not self.client.is_joined_member(room_id, user_id):
            return 403, {"error": "你不是该频道成员"}
        try:
            from cosmac.db import kb, session_scope
            from cosmac.db.models import SCOPE_ROOM

            docs: List[Dict[str, Any]] = []
            with session_scope() as s:
                for d in kb.list_docs(s, scope=SCOPE_ROOM, scope_id=room_id):
                    docs.append({"id": d.id, "title": d.title, "source": d.source})
            return 200, {"docs": docs}
        except Exception:
            logger.exception("读频道知识库失败")
            return 500, {"error": "读取失败"}

    def handle_kb_room_add(
        self, access_token: str, body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """上传一篇文档进本频道知识库。需登录 + **频道管理员**(power≥50) + knowledge 门控。

        频道 KB 是共享资源、会注入所有成员的检索，故只有频道管理员能改（与改频道配置同口径）。
        前端负责把文本文件读成 content 传上来（PDF/Word 解析暂不支持，见前端提示）。
        """
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        room_id = str((body or {}).get("room_id") or "").strip()
        if not room_id.startswith("!"):
            return 400, {"error": "无效的频道 id"}
        if not self._is_room_admin(room_id, user_id):
            return 403, {"error": "仅频道管理员可上传本频道知识库文档"}
        # 知识库门控：与个人库/RAG 同一道 knowledge 闸。
        if not self._gate_allows(user_id, "knowledge"):
            return 403, {"error": self._gate_denied_text("knowledge", ui=True)}
        title = str((body or {}).get("title") or "").strip()
        content = str((body or {}).get("content") or "").strip()
        if not content:
            return 400, {"error": "文件内容为空（仅支持文本文件）"}
        from cosmac.db.kb_cmd import MAX_DOC_CHARS, MAX_DOCS_PER_SCOPE, clean_upload_text

        # 清洗后再计数/入库(负责人实报:Excel 另存的"空"CSV 满是逗号,原文两万多字
        # 误报"太长";清洗还能避免把分隔符噪音灌进检索)。title 即前端传的文件名。
        content = clean_upload_text(content, filename=title)
        if not content:
            return 400, {"error": "文件内容为空（清洗掉空单元格/空行后没有实际内容）"}
        if len(content) > MAX_DOC_CHARS:
            return 400, {
                "error": f"文件太长（{len(content)} 字），上限 {MAX_DOC_CHARS} 字，请拆分后再传"
            }
        try:
            from cosmac.db import kb, session_scope
            from cosmac.db.models import SCOPE_ROOM

            with session_scope() as s:
                # 同名=覆盖更新(负责人实报:同一文件反复上传堆出一串相同记录)——
                # 先删旧同名篇再入库,篇数上限按删完后的数量判。
                replaced = kb.delete_docs_by_title(
                    s, scope=SCOPE_ROOM, scope_id=room_id, title=title or "未命名文档")
                cur = len(kb.list_docs(s, scope=SCOPE_ROOM, scope_id=room_id))
                if cur >= MAX_DOCS_PER_SCOPE:
                    return 400, {
                        "error": f"本频道知识库已达上限（{MAX_DOCS_PER_SCOPE} 篇），先删一些再传"
                    }
                # 频道资源计入建者额度(负责人口径):频道库文档占**频道创建者**的 kb_docs +
                # storage 额度。覆盖同名不新增净篇数,故仅在"这是新增篇"时判 kb_docs。
                owner = self._room_creator(room_id) or user_id
                kb_limit = self._quota_limit(owner, "kb_docs")
                if kb_limit >= 0 and replaced == 0 and self._kb_docs_used(s, owner) >= kb_limit:
                    return 400, {"error": f"知识库已满（{kb_limit} 篇上限，含创建者名下各频道）。"
                                          "删一些文档或升级会员扩容。"}
                st_limit = self._quota_limit(owner, "storage_mb")
                if st_limit >= 0 and self._storage_bytes(owner) + self._blen(content) > st_limit * 1048576:
                    return 400, {"error": f"存储空间不足（上限 {st_limit}MB，含创建者名下各频道）。"
                                          "删除内容或升级会员扩容。"}
                doc = kb.ingest_document(
                    s, scope=SCOPE_ROOM, scope_id=room_id,
                    title=title or "未命名文档", source="upload", text=content,
                )
                self._storage_cache = {}  # 存量变了,作废缓存
                self._created_rooms_cache = {}
                return 200, {"ok": True, "id": doc.id, "title": doc.title,
                             "chunks": len(doc.chunks), "replaced": replaced}
        except Exception:
            logger.exception("频道知识库入库失败")
            return 500, {"error": "入库失败（数据库不可用？）"}

    def handle_kb_room_delete(
        self, access_token: str, body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """删本频道知识库一篇文档。需登录 + **频道管理员**。越权防护：doc 必须属于该频道。"""
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        room_id = str((body or {}).get("room_id") or "").strip()
        if not room_id.startswith("!"):
            return 400, {"error": "无效的频道 id"}
        if not self._is_room_admin(room_id, user_id):
            return 403, {"error": "仅频道管理员可删除本频道知识库文档"}
        try:
            doc_id = int((body or {}).get("id"))
        except (TypeError, ValueError):
            return 400, {"error": "文档 id 无效"}
        try:
            from cosmac.db import kb, session_scope
            from cosmac.db.models import SCOPE_ROOM, KnowledgeDoc

            with session_scope() as s:
                doc = s.get(KnowledgeDoc, doc_id)
                # 越权防护：只能删属于**本频道**的文档（防遍历 id 删别处的库）。
                if doc is None or doc.scope != SCOPE_ROOM or doc.scope_id != room_id:
                    return 404, {"error": "没找到该文档（或不属于本频道）"}
                kb.delete_doc(s, doc_id)
                return 200, {"ok": True}
        except Exception:
            logger.exception("频道知识库删除失败")
            return 500, {"error": "删除失败"}

    # 注册/登录页「隐私政策 / 帮助中心」的**内置默认稿**——后台没配置时用它,保证页面永远有内容。
    # 后台「页面内容」编辑后写控制室 cosmac.pages,即覆盖此稿。
    _DEFAULT_SITE_PAGES: Dict[str, Dict[str, str]] = {
        "privacy": {
            "title": "隐私政策",
            "md": (
                "GuDuu OS 隐私政策\n\n最后更新：2026年7月\n\n"
                "一、我们收集什么\n"
                "· 账号信息：用户名、邮箱（用于注册验证与找回密码）。\n"
                "· 使用数据：你创建的工作区/频道、发送的消息、上传的文件与知识库文档。\n"
                "· 技术信息：登录 IP、设备与浏览器类型（用于账号安全与异地登录提醒）。\n\n"
                "二、我们如何使用\n"
                "· 提供聊天、协作与 AI 助手服务。\n"
                "· 你与中枢 AI 的对话内容会发送给平台配置的大模型服务商用于生成回复；"
                "我们不会将其用于广告或出售给第三方。\n"
                "· 安全审计：识别异常登录与滥用行为。\n\n"
                "三、存储与安全\n"
                "· 数据存储在我们租用的云服务器，传输全程 HTTPS 加密。\n"
                "· 消息与文件按 Matrix 协议存储；运维人员仅在必要时依规访问。\n\n"
                "四、你的权利\n"
                "· 可随时修改个人资料、删除自己发送的消息。\n"
                "· 可联系管理员导出或删除账号数据、停用账号。\n\n"
                "五、联系我们\n"
                "· 平台内私信管理员，或发邮件至 support@guduu.co。"
            ),
        },
        "help": {
            "title": "帮助中心",
            "md": (
                "帮助中心\n\n"
                "【快速上手】\n"
                "1. 注册登录：邮箱验证码注册；忘记密码点登录页「忘记密码」。\n"
                "2. 创建工作区：首次登录跟随引导即可创建工作区与频道。\n"
                "3. 邀请成员：工作区设置 → 成员与角色 / 公开分享链接；频道内「频道管理 → 人员」可邀请。\n\n"
                "【中枢 AI 怎么用】\n"
                "· 右侧「中枢 AI」面板一句话下达目标，如「帮我建个活动专班并拉人、拆任务」。\n"
                "· 频道里 @ 它提问；它能建频道、派任务、跑工作流、检索知识库。\n\n"
                "【任务看板】\n"
                "· 中枢 AI 拆解的任务出现在「任务看板」，卡片按钮可推进状态（开始/完成/退回）。\n\n"
                "【知识库】\n"
                "· 频道管理 → 知识库可上传文本文档，本频道 AI 回答时自动检索。\n\n"
                "【常见问题】\n"
                "· 登录提示“账号已停用”：请联系管理员恢复。\n"
                "· 收不到验证码：检查垃圾邮件，或稍后重试。\n"
                "· 其它问题：私信管理员或发邮件 support@guduu.co。"
            ),
        },
    }

    def handle_site_page(self, key: str) -> Tuple[int, Dict[str, Any]]:
        """公开读「隐私政策/帮助中心」页面内容(注册/登录页用,**无需登录**)。

        优先级:控制室 cosmac.pages(后台「页面内容」编辑) > 内置默认稿。读不到配置时静默回落
        默认稿——公开页面绝不能因控制室抖动而空白。只认白名单 key,防拿去当任意读接口。
        """
        key = (key or "").strip()
        if key not in self._DEFAULT_SITE_PAGES:
            return 404, {"error": "页面不存在"}
        default = self._DEFAULT_SITE_PAGES[key]
        try:
            ctrl = self.client.resolve_alias(self.config.control_room_alias)
            if ctrl:
                ev = self.client.get_state_event(ctrl, "cosmac.pages") or {}
                page = ev.get(key) or {}
                md = str(page.get("md") or "").strip()
                if md:
                    return 200, {
                        "title": str(page.get("title") or "").strip() or default["title"],
                        "md": md,
                    }
        except Exception:
            logger.debug("读页面内容配置失败,回落默认稿", exc_info=True)
        return 200, dict(default)

    def handle_space_adopt(
        self, access_token: str, body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """把某频道挂进某工作区(写 Space 的 m.space.child)——bot 代写。

        为什么需要:凭邀请链接加入工作区的普通成员在 Space 里 power=0,写不了 state——
        手动「归入」失败,AI 建专班后的自动挂接也静默失败,频道永远躺在「未归类」(线上实报)。
        放行条件(fail-closed):请求者**同时**是该工作区与该频道的已加入成员——把自己所在的频道
        挂进自己所在的工作区,不能碰别人的房。bot 在 Space 无权限时用 make_room_admin 自提权。
        """
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        space_id = str((body or {}).get("space_id") or "").strip()
        room_id = str((body or {}).get("room_id") or "").strip()
        if not space_id.startswith("!") or not room_id.startswith("!"):
            return 400, {"error": "无效的房间 id"}
        if not self.client.is_joined_member(space_id, user_id):
            return 403, {"error": "你不是该工作区成员"}
        if not self.client.is_joined_member(room_id, user_id):
            return 403, {"error": "你不是该频道成员"}
        content = {"via": [self.config.server_name]}
        ok = self.client.set_state_event(space_id, "m.space.child", content, room_id)
        if not ok:
            # bot 多半不在这个 Space/没权限:用服务器管理 API 借 Space 的本地管理员给 bot 提权
            # (make_room_admin 会顺带邀请),join 后重试一次。
            from cosmac import registration
            code, _ = registration.make_room_admin(
                self.config.homeserver_url, space_id, self.config.bot_user_id
            )
            if code == 200:
                try:
                    self.client.join_room(space_id)
                except Exception:
                    logger.debug("bot 加入工作区失败(可能已在)", exc_info=True)
                ok = self.client.set_state_event(space_id, "m.space.child", content, room_id)
        if not ok:
            return 502, {"error": "挂接失败（服务端权限不足），请联系管理员"}
        return 200, {"ok": True}

    def handle_user_deactivated(
        self, access_token: str, user_id: str
    ) -> Tuple[int, Dict[str, Any]]:
        """查某用户是否已停用。给「私信对方不在场时提示消息可能送不达」用。需登录。

        用 Synapse 管理 API(query_user_deactivated,需 ADMIN_TOKEN)。查不到/未配置令牌 → deactivated=false
        (未知不误报"已停用")。这是组织内工具,同事间可见彼此停用状态,泄露风险低。
        """
        me = self.client.whoami(access_token)
        if not me:
            return 401, {"error": "登录已失效，请重新登录"}
        user_id = str(user_id or "").strip()
        if not user_id.startswith("@"):
            return 400, {"error": "无效用户 id"}
        from cosmac import registration
        d = registration.query_user_deactivated(self.config.homeserver_url, user_id)
        return 200, {"deactivated": bool(d)}  # None(查不了) → false,不误报

    # —— 平台共享知识库（阶段2）：管理员后台维护，任何专班可绑(knowledge=['platform'])——
    # 存 SCOPE_GLOBAL + 固定作用域 _PLATFORM_KB_SCOPE。读/写/删**仅平台管理员**(服务端强制)。

    def handle_platform_kb_list(self, access_token: str) -> Tuple[int, Dict[str, Any]]:
        """列平台共享知识库文档。仅平台管理员(后台页用)。"""
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        if not self._is_platform_admin(user_id):
            return 403, {"error": "仅平台管理员可管理平台知识库"}
        docs: List[Dict[str, Any]] = []
        try:
            from cosmac.db import kb, session_scope
            from cosmac.db.models import SCOPE_GLOBAL

            with session_scope() as s:
                for d in kb.list_docs(s, scope=SCOPE_GLOBAL, scope_id=self._PLATFORM_KB_SCOPE):
                    docs.append({"id": d.id, "title": d.title, "source": d.source})
        except Exception:
            logger.debug("列平台知识库失败", exc_info=True)
        return 200, {"docs": docs}

    def handle_platform_kb_add(
        self, access_token: str, body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """给平台共享知识库加一篇文档。仅平台管理员。"""
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        if not self._is_platform_admin(user_id):
            return 403, {"error": "仅平台管理员可管理平台知识库"}
        title = str((body or {}).get("title") or "").strip()
        content = str((body or {}).get("content") or "").strip()
        if not content:
            return 400, {"error": "正文不能为空"}
        from cosmac.db.kb_cmd import MAX_DOC_CHARS, MAX_DOCS_PER_SCOPE

        if len(content) > MAX_DOC_CHARS:
            return 400, {"error": f"正文太长（{len(content)} 字），上限 {MAX_DOC_CHARS} 字，请拆成多篇"}
        try:
            from cosmac.db import kb, session_scope
            from cosmac.db.models import SCOPE_GLOBAL

            with session_scope() as s:
                cur = len(kb.list_docs(s, scope=SCOPE_GLOBAL, scope_id=self._PLATFORM_KB_SCOPE))
                if cur >= MAX_DOCS_PER_SCOPE:
                    return 400, {"error": f"平台知识库已达上限（{MAX_DOCS_PER_SCOPE} 篇），先删一些"}
                doc = kb.ingest_document(
                    s, scope=SCOPE_GLOBAL, scope_id=self._PLATFORM_KB_SCOPE,
                    title=title, source="platform", text=content,
                )
                return 200, {"ok": True, "id": doc.id, "title": doc.title, "chunks": len(doc.chunks)}
        except Exception:
            logger.exception("平台知识库入库失败")
            return 500, {"error": "入库失败（数据库不可用？）"}

    def handle_platform_kb_delete(
        self, access_token: str, body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """删平台共享知识库一篇文档(按 id)。仅平台管理员;越权防护:只删本作用域的文档。"""
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        if not self._is_platform_admin(user_id):
            return 403, {"error": "仅平台管理员可管理平台知识库"}
        try:
            doc_id = int((body or {}).get("id"))
        except (TypeError, ValueError):
            return 400, {"error": "文档 id 无效"}
        try:
            from cosmac.db import kb, session_scope
            from cosmac.db.models import SCOPE_GLOBAL, KnowledgeDoc

            with session_scope() as s:
                doc = s.get(KnowledgeDoc, doc_id)
                if (doc is None or doc.scope != SCOPE_GLOBAL
                        or doc.scope_id != self._PLATFORM_KB_SCOPE):
                    return 404, {"error": "没找到该文档"}
                kb.delete_doc(s, doc_id)
                return 200, {"ok": True}
        except Exception:
            logger.exception("平台知识库删除失败")
            return 500, {"error": "删除失败"}

    # —— 个人协作人能力名册（模块3.5：普通用户在前台维护，按 owner=本人 隔离）——

    def _onboarding_template_by_key(self, key: str) -> Optional[Dict[str, Any]]:
        """从控制室读入驻模板，按 key 找一个**已上架(enabled)**的；找不到/读失败返回 None。

        供 handle_onboarding_select 做 tier 门控（M1）。bot 是控制室成员、恒可读；返回 None 表示
        该 key 不是后台已上架模板（内置模板 / 未知 slug / 控制室无配置），调用方据此放行不校验。
        """
        key = (key or "").strip()
        if not key:
            return None
        try:
            ctrl = self.client.resolve_alias(self.config.control_room_alias)
            if not ctrl:
                return None
            ev = self.client.get_state_event(ctrl, ONBOARDING_TEMPLATES_EVENT_TYPE) or {}
        except Exception:
            logger.debug("读取入驻模板失败（tier 校验按放行）", exc_info=True)
            return None
        for t in (ev.get("templates") if isinstance(ev, dict) else []) or []:
            if (isinstance(t, dict)
                    and str(t.get("key") or "").strip() == key
                    and t.get("enabled") is not False):
                return t
        return None

    def handle_onboarding_templates(
        self, access_token: str
    ) -> Tuple[int, Dict[str, Any]]:
        """列出后台配置的**已上架**入驻模板，供首次引导读取。需登录。

        #9：模板存**私有控制室** state event，普通用户读控制室必 403 → 旧前端直接读控制室失败、
        静默回退内置硬编码模板，后台精心配的模板对真实注册用户永不生效。这里由 bot（控制室成员）
        代读并只返回 ``enabled`` 的模板。best-effort：控制室不存在/读失败一律返回空列表（前端据此
        回退内置模板，不报错打断引导）。返回字段与前端 OnboardingTemplateDef 对齐。
        """
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        try:
            ctrl = self.client.resolve_alias(self.config.control_room_alias)
            if not ctrl:
                return 200, {"templates": []}
            ev = self.client.get_state_event(ctrl, ONBOARDING_TEMPLATES_EVENT_TYPE) or {}
        except Exception:
            logger.debug("读取入驻模板失败（按空处理）", exc_info=True)
            return 200, {"templates": []}
        raw = ev.get("templates") if isinstance(ev, dict) else None
        out: List[Dict[str, Any]] = []
        for t in (raw or []):
            if not isinstance(t, dict):
                continue
            if t.get("enabled") is False:  # 只给引导已上架的模板
                continue
            key = str(t.get("key") or "").strip()
            label = str(t.get("label") or "").strip()
            if not key or not label:  # 缺关键字段的脏数据丢弃
                continue
            kb_docs = []
            for d in (t.get("kbDocs") or []):
                if isinstance(d, dict):
                    kb_docs.append({
                        "title": str(d.get("title") or ""),
                        "content": str(d.get("content") or ""),
                    })
            out.append({
                "key": key,
                "label": label,
                "icon": str(t.get("icon") or "🧩"),
                "desc": str(t.get("desc") or ""),
                "model": str(t.get("model") or ""),
                "persona": str(t.get("persona") or ""),
                "rules": str(t.get("rules") or ""),
                "skillSlugs": [str(x) for x in (t.get("skillSlugs") or [])],
                "kbDocs": kb_docs,
                "channels": [str(x) for x in (t.get("channels") or [])],
                "workflowSlugs": [str(x) for x in (t.get("workflowSlugs") or [])],
                "tier": str(t.get("tier") or "free"),
                "enabled": True,
            })
        return 200, {"templates": out}

    def handle_onboarding_select(
        self, access_token: str, body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """记录本人注册引导选择的入驻模板(user→template 映射,资源「可用范围」判定用)。

        需登录;只能写**自己的**映射(user_id 从 token 反查,body 里不收用户名——防替别人改)。
        幂等:重复上报/换模板就地覆盖。失败不阻断引导流程(前端 best-effort 调用)。
        """
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        slug = str((body or {}).get("template") or "").strip()
        if not slug or len(slug) > 128:
            return 400, {"error": "模板标识无效"}
        # tier 门控（M1）：若选的是**后台已上架模板**，必须满足其会员等级门槛，否则免费用户 POST
        # 一个付费模板 slug 就能白得所有 access=tpl:<slug> 的技能/智能体使用权（tpl 门控被绕过）。
        # 前端 templateLocked 只是 UX，服务端必须强制。内置/未知 slug 不关联任何后台 tpl 资源，
        # 记录映射无授权风险 → 放行（保住无后台模板时的内置引导流程）。
        tpl = self._onboarding_template_by_key(slug)
        if tpl is not None:
            need = str(tpl.get("tier") or "free")
            if tier_level(self.members.get_tier(user_id)) < tier_level(need):
                return 403, {"error": "该模板需要更高的会员等级，请先升级会员后再选择。"}
        try:
            from cosmac.db import session_scope
            from cosmac.db.user_template_repo import set_user_template

            with session_scope() as s:
                set_user_template(s, user_id=user_id, template_slug=slug)
            self._user_template_cache.pop(user_id, None)  # 立即生效,不等缓存过期
            return 200, {"ok": True}
        except Exception:
            logger.exception("记录用户入驻模板失败")
            return 500, {"error": "记录失败"}

    # ── 用户自建 智能体/技能(scope=user,归属本人账号,计入存储空间;负责人需求) ──
    _MY_ITEMS_MAX = 50          # 每人 智能体/技能 各最多 50 个(与聊天命令建技能同上限)
    _MY_PROMPT_MAX = 4000       # 个人智能体人设上限(字符)
    _MY_INSTR_MAX = 2000        # 个人技能正文上限(与 skill_cmd 一致)

    @staticmethod
    def _valid_slug(slug: str) -> bool:
        import re as _re
        return bool(_re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", slug or ""))

    def _my_storage_guard(self, user_id: str, add_chars: int) -> Optional[str]:
        """自建内容入库前的存储空间硬管控(与个人知识库同口径)。超限返回提示文案。"""
        limit_mb = self._quota_limit(user_id, "storage_mb")
        if limit_mb < 0:
            return None
        if self._storage_bytes(user_id) + add_chars > limit_mb * 1048576:
            return f"存储空间不足（上限 {limit_mb}MB）。删除一些内容或升级会员扩容。"
        return None

    def handle_my_agents_list(self, access_token: str) -> Tuple[int, Dict[str, Any]]:
        """列本人自建智能体。需登录。"""
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        try:
            from cosmac.db import session_scope
            from cosmac.db.models import SCOPE_USER
            from cosmac.db.repo import list_agents

            with session_scope() as s:
                out = [{
                    "slug": a.slug, "name": a.name, "description": a.description,
                    "system_prompt": a.system_prompt, "model": a.model,
                    "workflow_slugs": list(a.workflow_slugs or []),
                    "source_url": a.source_url or "",
                    "enabled": a.enabled,
                } for a in sorted(
                    list_agents(s, scope=SCOPE_USER, scope_id=user_id),
                    # 工坊按「新增时间倒序」展示(负责人建议:刚建的排最前,不用往下翻)。
                    # 共用 repo 的默认 slug 排序不动——名册注入等处依赖它的稳定顺序。
                    # created_at 相同(同秒批量建)时用 id 兜底,保证顺序确定。
                    key=lambda x: (x.created_at, x.id), reverse=True,
                )]
            return 200, {"agents": out}
        except Exception:
            logger.exception("列个人智能体失败")
            return 500, {"error": "读取失败"}

    def handle_my_import_preview(
        self, access_token: str, body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """从 GitHub 等处取回 manifest 并**只做预览**，绝不落库。

        分两步（preview / confirm）而不是一步导入，是因为第三方人设会作为系统提示注入
        给主 AI，而主 AI 手里有建群/发消息/查知识库等工具——静默导入等于把一部分控制权
        交给素未谋面的作者。必须让用户先看到人设全文再决定。

        返回的 sha256 是给 confirm 用的锁：预览与确认之间隔着用户读文本的几十秒，
        攻击者可以在这中间把仓库文件换掉（TOCTOU），confirm 会重新拉取并比对。
        """
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        from cosmac.manifest import fetch_manifest, parse_manifest, review_notes

        data, digest, err = fetch_manifest(str((body or {}).get("url") or ""))
        if err:
            return 400, {"error": err}
        item, perr = parse_manifest(data or {})
        if perr:
            return 400, {"error": perr}
        # 门控在**预览阶段**就查一次：让用户早点知道"这功能要付费"，
        # 而不是读完长长的人设、点了确认才被拒。confirm 会再查一次（真正的闸）。
        gate = "custom_agent" if item["kind"] == "agent" else "custom_skill"
        if not self._gate_allows(user_id, gate):
            return 403, {"error": self._gate_denied_text(gate, ui=True)}
        return 200, {
            "item": item,
            "sha256": digest,
            "notes": review_notes(item),
            # 引用了但用户没有的技能/工作流：注入侧对缺失是静默跳过的，
            # 不在这里挑明，用户会装完才发现"这 Agent 怎么不好使"。
            "missing": self._missing_deps(user_id, item),
            # 同 slug 已存在 → 前端提示"将覆盖"，避免用户误以为是新增
            "exists": self._my_item_exists(user_id, item["kind"], item["slug"]),
        }

    def _missing_deps(self, user_id: str, item: Dict[str, Any]) -> Dict[str, List[str]]:
        """找出 manifest 引用了、但这个用户手上**并没有**的技能 / 工作流。

        为什么必须提前告诉用户：注入侧对解析不到的 slug 是**静默跳过**的
        （_agent_skill_items / _preset_workflows_text 都如此，这本身是对的——
        资源被删了不该让整条回复崩）。但副作用是：装了一个引用 3 个技能的 Agent、
        实际一个都没有，用户毫不知情，只会觉得"这 Agent 怎么不好使"。
        所以在**导入前**就把缺口摆出来，让用户知道自己装的是不完整的东西。

        返回 {"skills": [...], "workflows": [...]}，都缺不到就是两个空列表。
        """
        out: Dict[str, List[str]] = {"skills": [], "workflows": []}
        try:
            want_sk = [str(x) for x in (item.get("skill_slugs") or [])]
            want_wf = [str(x) for x in (item.get("workflow_slugs") or [])]
            if want_sk:
                # 用户实际能用到的技能 = 他可见的全局技能 + 他自己的个人技能
                have = {str(s.get("slug")) for s in self._global_skill_items(for_user=user_id)}
                try:
                    from cosmac.db import session_scope
                    from cosmac.db.models import SCOPE_USER
                    from cosmac.db.repo import list_skills

                    with session_scope() as s:
                        have |= {
                            k.slug for k in list_skills(s, scope=SCOPE_USER, scope_id=user_id)
                        }
                except Exception:
                    logger.debug("读个人技能失败（按缺处理）", exc_info=True)
                out["skills"] = [x for x in want_sk if x not in have]
            if want_wf:
                have_wf = {str(w.get("slug")) for w in self._workflow_defs()}
                out["workflows"] = [x for x in want_wf if x not in have_wf]
        except Exception:
            logger.debug("检查依赖失败（忽略，不阻断导入）", exc_info=True)
        return out

    def _my_item_exists(self, user_id: str, kind: str, slug: str) -> bool:
        """本人名下是否已有同 slug 的技能/智能体（导入前提示"将覆盖"用）。"""
        try:
            from cosmac.db import session_scope
            from cosmac.db.models import SCOPE_USER
            from cosmac.db.repo import get_agent, get_skill

            with session_scope() as s:
                if kind == "agent":
                    return get_agent(s, SCOPE_USER, user_id, slug) is not None
                return get_skill(s, SCOPE_USER, user_id, slug) is not None
        except Exception:
            logger.debug("查重失败（忽略，按不存在处理）", exc_info=True)
            return False

    def handle_my_import_confirm(
        self, access_token: str, body: Dict[str, Any], *, user_id: str = ""
    ) -> Tuple[int, Dict[str, Any]]:
        """用户确认后真正落库。

        ⚠️ **重新拉取并比对 sha256**，绝不采信前端回传的内容：
          ① 防 TOCTOU——预览后仓库被换成恶意版本；
          ② 防前端被篡改后直接投喂任意内容（预览展示的和落库的必须是同一份）。
        """
        # user_id 显式传入 = 主 AI 工具调用路径（工具侧只有 ctx.sender，拿不到用户 token）；
        # 否则走 HTTP 入口，用 access_token 反查。
        user_id = user_id or self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        from cosmac.manifest import fetch_manifest, parse_manifest

        expect = str((body or {}).get("sha256") or "").strip().lower()
        if not expect:
            return 400, {"error": "缺少校验值，请重新预览"}
        data, digest, err = fetch_manifest(str((body or {}).get("url") or ""))
        if err:
            return 400, {"error": err}
        if digest != expect:
            return 409, {"error": "文件内容在你确认期间发生了变化，请重新预览并核对后再导入"}
        item, perr = parse_manifest(data or {})
        if perr:
            return 400, {"error": perr}
        # 记来源：存用户给的原始地址（而非规整后的 CDN 直链）——用户认得出自己粘的是什么，
        # 日后要核对/重装也是回 GitHub 那个页面，不是 jsdelivr。
        src_url = str((body or {}).get("url") or "").strip()[:500]

        # 复用工坊的保存端点：门控、条数上限、存储配额、字段清洗全都走同一套，
        # 不另写一份规则——否则导入会成为绕过配额与门控的后门。
        if item["kind"] == "agent":
            return self.handle_my_agents_save(access_token, {
                "slug": item["slug"], "name": item["name"],
                "description": item["description"],
                "system_prompt": item["system_prompt"], "model": item.get("model", ""),
                # 引用的工作流照搬 slug；个人绑定本就不提权（见 handle_my_agents_save），
                # 所以即使 manifest 里写了一堆，也拿不到额外权限。
                "workflow_slugs": item.get("workflow_slugs") or [],
                "enabled": True, "source_url": src_url,
            }, user_id=user_id)
        return self.handle_my_skills_save(access_token, {
            "slug": item["slug"], "name": item["name"],
            "description": item["description"],
            "instructions": item["instructions"], "enabled": True,
            "source_url": src_url,
        }, user_id=user_id)

    # ── AI 会话标题：让左侧会话列表显示「这段在聊什么」而不是首句原文 ──
    # 此前标题是前端把首句砍前 24 字，用户粘个链接进来，列表里就是一串 URL
    # （负责人实报「没有识别任务内容归类一个任务名」）。这里在**首轮回复之后**
    # 让模型概括一句，写进会话标记 state，前端优先读它。
    #
    # 几个刻意的取舍：
    #   · 只在首轮做一次（房里已有标题就跳过）——标题是"这段会话干嘛的"，
    #     不该随聊天漂移，也避免每轮都多烧一次模型调用。
    #   · 失败一律静默：标题是锦上添花，绝不能因为它拖慢或打断回复。
    #   · 写的是 cosmac.ai_session 这个既有标记（加个 title 字段），不动 m.room.name
    #     ——房名改了会影响 Element 等其它客户端的显示。

    _SESSION_TITLE_MAX = 16

    def _maybe_name_ai_session(self, room_id: str, user_text: str, reply_text: str) -> None:
        """AI 会话房首轮结束后，生成并写入一个短标题（失败静默）。"""
        try:
            if not self._is_ai_session_room(room_id):
                return
            ev = self.client.get_state_event(room_id, "cosmac.ai_session") or {}
            if str(ev.get("title") or "").strip():
                return   # 已有标题：只在首轮定一次
            prompt = (
                "用一个不超过 12 个字的短语概括下面这段对话在做什么，作为会话标题。\n"
                "要求：只输出标题本身，不要引号、句号、前缀或任何解释；"
                "用中文；抓住用户的目的而不是复述他贴的链接或原文。\n\n"
                f"用户说：{(user_text or '').strip()[:300]}\n"
                f"助手答：{(reply_text or '').strip()[:300]}"
            )
            raw = self.llm.complete([Message(role="user", content=prompt)]) or ""
            # 模型偶尔会加引号/句号/换行，统一清掉；太长再截断兜底
            title = raw.strip().split("\n")[0].strip().strip("\"'“”「」。.：:")
            title = title[: self._SESSION_TITLE_MAX]
            if not title:
                return
            self.client.set_state_event(
                room_id, "cosmac.ai_session", {**ev, "title": title},
            )
        except Exception:
            logger.debug("生成会话标题失败（忽略，前端会回退到截断首句）", exc_info=True)

    # ── 主 AI 侧的 manifest 导入（工具回调） ──────────────────────
    # 与工坊界面走的是同一套 manifest 解析与落库逻辑，只是入口不同：
    # 界面上是用户自己粘地址，这里是用户在对话里让 AI 代劳。
    # ⚠️ 落库前的"人工确认"由工具描述强制 AI 先展示正文 + 调 ask_user_choice；
    # 服务端这一侧则守住：必须带预览时的 sha256（等于强制看过内容）、内容变了就拒绝。

    def _manifest_preview_for_tool(self, url: str, ctx: "ToolContext") -> str:
        """给 preview_skill_import 用：取回并渲染成给模型读的文本。"""
        from cosmac.manifest import fetch_manifest, parse_manifest, review_notes

        data, digest, err = fetch_manifest(url)
        if err:
            return f"读取失败：{err}"
        item, perr = parse_manifest(data or {})
        if perr:
            return f"这个文件不是有效的 GuDuu manifest：{perr}"
        gate = "custom_agent" if item["kind"] == "agent" else "custom_skill"
        if not self._gate_allows(ctx.sender, gate):
            return self._gate_denied_text(gate, ui=False)
        kind_cn = "智能体" if item["kind"] == "agent" else "技能"
        body = item.get("system_prompt") or item.get("instructions") or ""
        exists = self._my_item_exists(ctx.sender, item["kind"], item["slug"])
        lines = [
            f"读到一个{kind_cn}定义：{item['name']}（标识 {item['slug']}）",
            f"用途：{item['description']}",
            f"作者：{item.get('author') or '未标注'}；许可：{item.get('license') or '未标注'}",
            f"校验值 sha256：{digest}",
        ]
        if exists:
            lines.append(f"⚠️ 用户已有同标识的{kind_cn}，安装会覆盖它。")
        for n in review_notes(item):
            lines.append(f"提醒：{n}")
        miss = self._missing_deps(ctx.sender, item)
        if miss["skills"] or miss["workflows"]:
            parts = []
            if miss["skills"]:
                parts.append("技能 " + "、".join(miss["skills"]))
            if miss["workflows"]:
                parts.append("工作流 " + "、".join(miss["workflows"]))
            lines.append(
                "⚠️ 缺依赖：它引用了 " + "；".join(parts)
                + "，而用户手上没有这些。装了也用不上这部分能力——"
                "请如实告诉用户这个缺口，让他决定还要不要装。"
            )
        lines.append(f"—— 以下是完整{'人设' if item['kind'] == 'agent' else '正文'}，请原样展示给用户 ——")
        lines.append(body)
        lines.append(
            "—— 以上 ——\n"
            "接下来你**必须**：把上面的正文原样展示给用户、指出风险，"
            "再用 ask_user_choice 征求同意；用户同意后才调 import_skill_from_url"
            f"（url 与本次相同，sha256 填 {digest}）。"
        )
        return "\n".join(lines)

    def _manifest_import_for_tool(self, url: str, sha256: str, ctx: "ToolContext") -> str:
        """给 import_skill_from_url 用：复用 confirm 端点，保证与界面导入同一套规则。"""
        code, payload = self.handle_my_import_confirm(
            "", {"url": url, "sha256": sha256}, user_id=ctx.sender,
        )
        if code == 200:
            # 明确告诉用户**怎么用**：个人智能体不需要绑频道——它会进主 AI 的派单名册
            # （标「我的·」），在任意频道输入它的名字即可点名它应答。
            return (
                "已安装到该用户的工坊。请告诉用户三件事："
                "① 它已进入主 AI 的派单名册（显示为「我的·<名称>」）；"
                "② 在任意频道直接输入它的名字就能点名它应答，**不需要额外绑定频道**；"
                "③ 想改人设或删除，去「我的AI工坊」。"
            )
        return f"安装失败：{payload.get('error') or code}"

    def handle_my_workflows_list(self, access_token: str) -> Tuple[int, Dict[str, Any]]:
        """列出可绑定的工作流连接器（给工坊的「绑定工作流」勾选框用）。需登录。

        ⚠️ **只下发 slug / name / 输入提示**——url、cred（凭据名）、graph 一律不出网。
        连接器定义存在控制室 state event，普通用户本来就读不到；这里由 bot 代读并**裁剪**，
        绝不能顺手把整条定义回传（那等于把内网 webhook 地址和凭据名广播给所有登录用户）。

        只回 enabled 的：停用的连接器没有绑定价值，列出来只会让人绑了个跑不动的。
        """
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        try:
            out = [
                {
                    "slug": str(w.get("slug") or ""),
                    "name": str(w.get("name") or ""),
                    "input_hint": str(w.get("input_hint") or ""),
                }
                for w in self._workflow_defs()
                if w.get("slug")
            ]
            return 200, {"workflows": out}
        except Exception:
            logger.exception("列可绑定工作流失败")
            return 500, {"error": "读取失败"}

    def handle_my_agents_save(
        self, access_token: str, body: Dict[str, Any], *, user_id: str = ""
    ) -> Tuple[int, Dict[str, Any]]:
        """新建/更新本人自建智能体。校验:slug 规范、字段长度、每人 50 个、存储空间。"""
        # user_id 显式传入 = 主 AI 工具调用路径（工具侧只有 ctx.sender，拿不到用户 token）；
        # 否则走 HTTP 入口，用 access_token 反查。
        user_id = user_id or self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        # 自建智能体是付费功能(custom_agent 门控,与自建技能 custom_skill 对称)——此前
        # 这里没有闸,免费用户可随意建(负责人报的"有部分内容没加权限")。删自己的不设门控。
        if not self._gate_allows(user_id, "custom_agent"):
            return 403, {"error": self._gate_denied_text("custom_agent", ui=True)}
        slug = str((body or {}).get("slug") or "").strip().lower()
        if not self._valid_slug(slug):
            return 400, {"error": "标识(slug)需为小写字母/数字/中划线,64 字符内"}
        name = str(body.get("name") or "").strip()[:80]
        description = str(body.get("description") or "").strip()[:300]
        prompt = str(body.get("system_prompt") or "").strip()
        model = str(body.get("model") or "").strip()[:128]
        enabled = body.get("enabled") is not False
        # 绑定的工作流：**只存不授权**。个人智能体的绑定不进 ToolContext.authorized_workflows，
        # 跑不跑得动仍由 workflow_run 门控裁决——否则用户自建一个 Agent 绑上去就绕过了门槛，
        # 等于自助提权。这里只做格式清洗与条数上限，不校验 slug 是否存在
        # （连接器可能后建/被停用，运行期 _preset_workflows_text 会自动跳过解析不到的）。
        wf_slugs = [
            str(x).strip().lower()[:128]
            for x in (body.get("workflow_slugs") or [])
            if str(x).strip()
        ][:20]
        if not name or not description or not prompt:
            return 400, {"error": "名称、备注(它是干嘛的)与人设都不能为空——主 AI 靠备注理解何时派给它"}
        if len(prompt) > self._MY_PROMPT_MAX:
            return 400, {"error": f"人设过长（上限 {self._MY_PROMPT_MAX} 字符）"}
        try:
            from cosmac.db import session_scope
            from cosmac.db.models import SCOPE_USER
            from cosmac.db.repo import get_agent, list_agents, upsert_agent

            with session_scope() as s:
                existing = get_agent(s, SCOPE_USER, user_id, slug)
                if existing is None and len(list_agents(s, scope=SCOPE_USER, scope_id=user_id)) >= self._MY_ITEMS_MAX:
                    return 400, {"error": f"自建智能体已达上限（{self._MY_ITEMS_MAX} 个），先删一些"}
                add_chars = self._blen(name) + self._blen(description) + self._blen(prompt)
                if existing is not None:  # 更新=净增量
                    add_chars -= (self._blen(existing.name) + self._blen(existing.description)
                                  + self._blen(existing.system_prompt))
                err = self._my_storage_guard(user_id, max(0, add_chars))
                if err:
                    return 400, {"error": err}
                upsert_agent(
                    s, SCOPE_USER, user_id, slug,
                    name=name, description=description, system_prompt=prompt,
                    model=model, workflow_slugs=wf_slugs, enabled=enabled,
                    # 来源:只有导入路径会带,界面新建为空(=自建)。
                    # 每次保存都写,这样"从导入改成手写"后标记会自然消失。
                    source_url=str(body.get("source_url") or "").strip()[:500],
                )
            self._storage_cache = {}  # 内容变了,存量缓存作废
            self._my_agents_cache.pop(user_id, None)  # 自建列表缓存失效,点名路由立即感知
            return 200, {"ok": True}
        except Exception:
            logger.exception("保存个人智能体失败")
            return 500, {"error": "保存失败"}

    def handle_my_agents_delete(
        self, access_token: str, body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """删除本人自建智能体(只能删自己的,定位键含 owner,天然越权隔离)。"""
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        slug = str((body or {}).get("slug") or "").strip().lower()
        try:
            from cosmac.db import session_scope
            from cosmac.db.models import SCOPE_USER
            from cosmac.db.repo import delete_agent

            with session_scope() as s:
                ok = delete_agent(s, SCOPE_USER, user_id, slug)
            self._storage_cache = {}
            self._my_agents_cache.pop(user_id, None)  # 同保存:删除也立即生效
            return (200, {"ok": True}) if ok else (404, {"error": "没有这个智能体"})
        except Exception:
            logger.exception("删除个人智能体失败")
            return 500, {"error": "删除失败"}

    def handle_my_skills_list(self, access_token: str) -> Tuple[int, Dict[str, Any]]:
        """列本人自建技能(含聊天命令「技能 添加」建的——同一份数据)。需登录。"""
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        try:
            from cosmac.db import session_scope
            from cosmac.db.models import SCOPE_USER
            from cosmac.db.repo import list_skills

            with session_scope() as s:
                out = [{
                    "slug": k.slug, "name": k.name, "description": k.description,
                    "instructions": k.instructions, "source_url": k.source_url or "",
                    "enabled": k.enabled,
                } for k in sorted(
                    list_skills(s, scope=SCOPE_USER, scope_id=user_id),
                    key=lambda x: (x.created_at, x.id), reverse=True,  # 同上:新增在最前
                )]
            return 200, {"skills": out}
        except Exception:
            logger.exception("列个人技能失败")
            return 500, {"error": "读取失败"}

    def handle_my_skills_save(
        self, access_token: str, body: Dict[str, Any], *, user_id: str = ""
    ) -> Tuple[int, Dict[str, Any]]:
        """新建/更新本人自建技能。个人技能会注入本人每轮对话——单条与总量都有上限。"""
        # user_id 显式传入 = 主 AI 工具调用路径（工具侧只有 ctx.sender，拿不到用户 token）；
        # 否则走 HTTP 入口，用 access_token 反查。
        user_id = user_id or self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        # 自建技能是付费功能（custom_skill 门控）：与聊天命令「技能」同一道闸、服务端强制——否则
        # 免费用户绕开命令、换工坊 HTTP 端点照建不误（M3）。删自己的不设门控（见 delete 端点）。
        if not self._gate_allows(user_id, "custom_skill"):
            return 403, {"error": self._gate_denied_text("custom_skill", ui=True)}
        slug = str((body or {}).get("slug") or "").strip().lower()
        if not self._valid_slug(slug):
            return 400, {"error": "标识(slug)需为小写字母/数字/中划线,64 字符内"}
        name = str(body.get("name") or "").strip()[:80]
        description = str(body.get("description") or "").strip()[:300]
        instructions = str(body.get("instructions") or "").strip()
        enabled = body.get("enabled") is not False
        if not instructions:
            return 400, {"error": "技能正文不能为空"}
        if len(instructions) > self._MY_INSTR_MAX:
            return 400, {"error": f"技能正文过长（上限 {self._MY_INSTR_MAX} 字符）"}
        try:
            from cosmac.db import session_scope
            from cosmac.db.models import SCOPE_USER
            from cosmac.db.repo import get_skill, list_skills, upsert_skill

            with session_scope() as s:
                existing = get_skill(s, SCOPE_USER, user_id, slug)
                if existing is None and len(list_skills(s, scope=SCOPE_USER, scope_id=user_id)) >= self._MY_ITEMS_MAX:
                    return 400, {"error": f"自建技能已达上限（{self._MY_ITEMS_MAX} 个），先删一些"}
                add_chars = self._blen(name) + self._blen(description) + self._blen(instructions)
                if existing is not None:
                    add_chars -= (self._blen(existing.name) + self._blen(existing.description)
                                  + self._blen(existing.instructions))
                err = self._my_storage_guard(user_id, max(0, add_chars))
                if err:
                    return 400, {"error": err}
                upsert_skill(
                    s, SCOPE_USER, user_id, slug,
                    name=name, description=description,
                    instructions=instructions, enabled=enabled,
                    # 同 agent：只有导入路径会带，界面新建为空(=自建)
                    source_url=str(body.get("source_url") or "").strip()[:500],
                )
            self._storage_cache = {}
            return 200, {"ok": True}
        except Exception:
            logger.exception("保存个人技能失败")
            return 500, {"error": "保存失败"}

    def handle_my_skills_delete(
        self, access_token: str, body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """删除本人自建技能。"""
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        slug = str((body or {}).get("slug") or "").strip().lower()
        try:
            from cosmac.db import session_scope
            from cosmac.db.models import SCOPE_USER
            from cosmac.db.repo import delete_skill

            with session_scope() as s:
                ok = delete_skill(s, SCOPE_USER, user_id, slug)
            self._storage_cache = {}
            return (200, {"ok": True}) if ok else (404, {"error": "没有这个技能"})
        except Exception:
            logger.exception("删除个人技能失败")
            return 500, {"error": "删除失败"}

    def _my_agent_items(self, owner: str) -> List[Dict[str, Any]]:
        """本人自建且启用的智能体(名册/@ 路由用)。失败返回空,绝不阻断。

        5 分钟缓存(评审 #3):点名判定每条群消息都调,不能每条打一次 DB——口径同
        _acquired_agent_slugs;工坊保存/删除端点写入时主动失效(改完立即生效)。
        """
        if not owner:
            return []
        cached = self._my_agents_cache.get(owner)
        if cached and time.monotonic() - cached[1] < 300:
            return cached[0]
        items = self._my_agent_items_uncached(owner)
        self._my_agents_cache[owner] = (items, time.monotonic())
        if len(self._my_agents_cache) > 5000:
            self._my_agents_cache.clear()
        return items

    def _my_skill_items(self, owner: str) -> List[Dict[str, Any]]:
        """本人自建且启用的技能（P4 上架校验用；不进注入路径，故不做缓存）。"""
        if not owner:
            return []
        try:
            from cosmac.db import session_scope
            from cosmac.db.models import SCOPE_USER
            from cosmac.db.repo import list_skills

            with session_scope() as s:
                return [{
                    "slug": k.slug, "name": k.name, "description": k.description,
                } for k in list_skills(
                    s, scope=SCOPE_USER, scope_id=owner, enabled_only=True
                )]
        except Exception:
            logger.debug("读取个人技能失败(忽略)", exc_info=True)
            return []

    def _my_agent_items_uncached(self, owner: str) -> List[Dict[str, Any]]:
        """_my_agent_items 的真实 DB 读取体(缓存壳见上)。"""
        try:
            from cosmac.db import session_scope
            from cosmac.db.models import SCOPE_USER
            from cosmac.db.repo import list_agents

            with session_scope() as s:
                return [{
                    "slug": a.slug, "name": a.name, "description": a.description,
                    "system_prompt": a.system_prompt, "model": a.model,
                    "skill_slugs": list(a.skill_slugs or []),
                    # 个人智能体绑定的工作流：只用于「告诉 AI 它该用哪些」，**不构成授权**
                    # （不进 authorized_workflows）——能不能跑仍由 workflow_run 门控裁决。
                    "workflow_slugs": list(a.workflow_slugs or []),
                } for a in list_agents(s, scope=SCOPE_USER, scope_id=owner, enabled_only=True)]
        except Exception:
            logger.debug("读取个人智能体失败(忽略)", exc_info=True)
            return []

    def handle_preset_agents(self, access_token: str) -> Tuple[int, Dict[str, Any]]:
        """列出**内置预置 Agent 库**(原生班底+agency 引入,给后台「智能体」页展示)。

        需登录。代码内置、前端读控制室看不到它们;后台想改/停用某个 → 同 slug 在「智能体」页
        新建一条即可覆盖(合并规则见 _global_agent_items)。带 division 供分组展示。
        """
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        from cosmac.ai.presets import preset_agents

        return 200, {"agents": preset_agents()}

    def handle_preset_skills(self, access_token: str) -> Tuple[int, Dict[str, Any]]:
        """列出**内置预置技能库**(给后台技能库页展示;代码内置,前端读控制室看不到它们)。

        需登录(管理员后台用)。每项附:preset=true(标识来源)+ agents(绑了它的预置 AI 同事名,
        前端显示"随【文案】激活")+ inject='agent'(它们不全局注入,只随 Agent 激活)。
        """
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        from cosmac.ai.preset_skills import preset_skills
        from cosmac.ai.presets import preset_agents

        by_skill: Dict[str, List[str]] = {}
        for a in preset_agents():
            for slug in a.get("skill_slugs", []):
                by_skill.setdefault(slug, []).append(a.get("name") or a.get("slug"))
        out = [
            {**s, "preset": True, "inject": "agent", "agents": by_skill.get(s["slug"], [])}
            for s in preset_skills()
        ]
        return 200, {"skills": out}

    def _market_catalog_items(
        self, user_id: str, is_admin: bool, only_kind: str = ""
    ) -> List[Dict[str, Any]]:
        """构建「AI Agent 商城」目录条目(handle_market_catalog 的主体,抽出来供
        acquire 校验/已获取列表回显复用——三处必须看到同一份货架)。

        四类平台真实资源:
          - agent: 全局智能体(内置预置库 + 控制室配置,启用的) → 按每项 access 判定解锁
          - skill: 可绑定技能库(预置 + 控制室,启用的) → 按每项 access 判定解锁
          - workflow: 工作流连接器(控制室,启用的) → 按 workflow_run 功能门控判定
          - knowledge: 平台共享知识库文档 → 按 knowledge 功能门控判定
        解锁判定复用 _resource_visible / _gate_allows,与对话注入/能力名册同一套服务端口径。

        ⚠️ 安全:只装「橱窗」字段(名称/描述/分组/解锁状态)。system_prompt、instructions、
        工作流 url/cred/graph 是平台资产与密钥线索,解锁与否都**绝不下发**(用是在聊天里用,
        不需要看到底层定义)。access='admin' 的资源对非管理员整条隐藏(永远解锁不了,列出徒增噪音)。
        """
        items: List[Dict[str, Any]] = []

        def _push(kind: str, it: Dict[str, Any], unlocked: bool, access: str,
                  extra: Optional[Dict[str, Any]] = None) -> None:
            """统一装一条商城条目(只放安全字段;敏感字段在调用处就没传进来)。"""
            row: Dict[str, Any] = {
                "kind": kind,
                "slug": str(it.get("slug") or it.get("id") or ""),
                "name": str(it.get("name") or it.get("title") or ""),
                "description": str(it.get("description") or ""),
                "access": access,
                "unlocked": bool(unlocked),
                "official": bool(it.get("preset")),  # 预置=官方内置;其余=平台运营在后台配的
            }
            if extra:
                row.update(extra)
            items.append(row)

        # —— 智能体:预置+控制室合并(启用的),逐条按 access 判定 ——
        # only_kind(评审 #9):acquire 校验单条资源时只建对应类别,别为一次校验重建全货架。
        # 技能段要用 agents 算「随谁激活」,故 agent/skill 两类都需要 agents 列表。
        agents = (
            self._global_agent_items() if only_kind in ("", "agent", "skill") else []
        )
        if not only_kind or only_kind == "agent":
            for a in agents:
                access = str(a.get("access") or "").strip()
                if access == "admin" and not is_admin:
                    continue
                _push("agent", a, self._resource_visible(a, user_id), access, {
                    "division": str(a.get("division") or ""),
                    # 只给绑定技能的数量,不给技能明细(卡片展示"内置 N 项技能"够了)
                    "skill_count": len(a.get("skill_slugs") or []),
                })

        # —— 技能:可绑定技能库(预置+控制室),附「随哪些 AI 同事激活」供使用指引 ——
        # preset_skills() 的原始条目不带 preset 标记(handle_preset_skills 是展示时补的),
        # 这里按 slug 对照预置库判定「官方」,否则预置技能会错标成"平台运营"。
        if not only_kind or only_kind == "skill":
            from cosmac.ai.preset_skills import preset_skills

            preset_skill_slugs = {str(p.get("slug")) for p in preset_skills()}
            by_skill: Dict[str, List[str]] = {}
            for a in agents:
                for sl in (a.get("skill_slugs") or []):
                    by_skill.setdefault(str(sl), []).append(str(a.get("name") or a.get("slug")))
            for s in self._skill_library():
                access = str(s.get("access") or "").strip()
                if access == "admin" and not is_admin:
                    continue
                _push("skill", s, self._resource_visible(s, user_id), access, {
                    "agents": by_skill.get(str(s.get("slug")), []),
                    "inject": str(s.get("inject") or ""),
                    "official": bool(s.get("preset")) or str(s.get("slug")) in preset_skill_slugs,
                })

        # —— 工作流:控制室连接器(启用的)。解锁=workflow_run 门控(全局一道闸,非逐项)。
        #    门槛=仅管理员(workflow_run 的默认值)时对非管理员整类隐藏,同 access='admin' 资源的口径 ——
        if not only_kind or only_kind == "workflow":
            wf_unlocked = self._gate_allows(user_id, "workflow_run")
            wf_required = self.gating.required("workflow_run")
            # 门槛 free=人人可用,前端语义上等于 access=''(免费)
            wf_access = "" if wf_required == TIER_FREE else str(wf_required)
            if is_admin or wf_required != GATE_ADMIN:
                for w in self._workflow_defs():
                    _push("workflow", w, wf_unlocked, wf_access, {
                        "platform": str(w.get("platform") or "webhook"),
                        "input_hint": str(w.get("input_hint") or ""),
                        "official": True,  # 连接器都是平台后台配的,统一标官方
                    })

        # —— 平台共享知识库:按篇列出。解锁=knowledge 门控。无 DB 时安静跳过。
        #    同上:门槛=仅管理员时对非管理员整类隐藏 ——
        if not only_kind or only_kind == "knowledge":
            kb_unlocked = self._gate_allows(user_id, "knowledge")
            kb_required = self.gating.required("knowledge")
            kb_access = "" if kb_required == TIER_FREE else str(kb_required)
            if is_admin or kb_required != GATE_ADMIN:
                try:
                    from cosmac.db import kb, session_scope
                    from cosmac.db.models import SCOPE_GLOBAL

                    with session_scope() as s:
                        for d in kb.list_docs(s, scope=SCOPE_GLOBAL, scope_id=self._PLATFORM_KB_SCOPE):
                            _push("knowledge", {"slug": f"kbdoc-{d.id}", "name": d.title},
                                  kb_unlocked, kb_access, {"official": True})
                except Exception:
                    logger.debug("商城列平台知识库失败(跳过该分类)", exc_info=True)

        # —— 创作者上架（P2/P4 创作者商城）：在售 listing。人人可获取（unlocked 恒 True），
        #    cagent=加入个人名册时不扣、**使用时**按次收；cskill=**获取时一次性买断**、
        #    之后永久用。前者在 UI 禁止称“免费获取”，避免误解为使用也免费。
        #    人设/技能正文绝不下发（创作者资产）。——
        if not only_kind or only_kind in ("cagent", "cskill"):
            try:
                from cosmac.db import listing_repo, session_scope

                want = {"cagent": "agent", "cskill": "skill"}.get(only_kind, "")
                with session_scope() as s:
                    rows = listing_repo.list_on_sale(s, kind=want)
                for li in rows:
                    lk = str(li.kind or "agent")
                    _push(
                        "cagent" if lk == "agent" else "cskill",
                        {"slug": str(li.id), "name": li.name}, True, "", {
                            "description": str(li.description or ""),
                            "price_tokens": int(li.price_tokens or 0),
                            "creator": str(li.creator or ""),
                            "uses": int(li.uses or 0),
                            "official": False,
                        },
                    )
            except Exception:
                logger.debug("商城列创作者资源失败(跳过该分类)", exc_info=True)
        return items

    def handle_market_catalog(self, access_token: str) -> Tuple[int, Dict[str, Any]]:
        """「AI Agent 商城」目录端点:平台真实资源 + 按发起人标注 解锁/已获取。需登录。

        目录构建见 _market_catalog_items;这里再叠一层本人「已获取」标注(acquired,
        存 cosmac DB,见 market_repo),前端据此渲染「已获取」态。
        """
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        is_admin = self._is_platform_admin(user_id)
        items = self._market_catalog_items(user_id, is_admin)
        # 标注已获取(读不到 DB 就全 False,商城照常能逛)
        try:
            from cosmac.db import session_scope
            from cosmac.db.market_repo import list_acquired

            with session_scope() as s:
                got = set(list_acquired(s, user_id))
            for it in items:
                it["acquired"] = (it["kind"], it["slug"]) in got
        except Exception:
            logger.debug("读取已获取列表失败(按未获取渲染)", exc_info=True)
        tier = self.members.get_tier(user_id)
        return 200, {
            "items": items,
            "tier": tier,
            "tier_label": tier_label(tier),
            "is_admin": is_admin,
        }

    # 商城资源类型全集(acquire 端点校验用)。cagent=创作者上架的 Agent(按次计费)、
    # cskill=创作者上架的 Skill(获取即买断,P4)
    _MARKET_KINDS = ("agent", "skill", "workflow", "knowledge", "cagent", "cskill")

    def handle_market_acquire(
        self, access_token: str, body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """「获取 / 移除获取」某个商城资源。需登录。

        获取时**服务端校验**:资源必须真实存在于当前货架、且对本人已解锁——否则可以
        绕过前端把"付费会员专属"直接记成已获取(虽然权限本身仍由 access 强制,但
        名册标注/工坊展示不该被污染)。移除不校验(货架下架了也要能清掉)。
        写入 cosmac DB(market_repo),并同步失效名册用的缓存,让主 AI 立即感知。
        """
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        kind = str((body or {}).get("kind") or "").strip()
        slug = str((body or {}).get("slug") or "").strip()[:128]
        want = (body or {}).get("acquired") is not False  # 缺省=获取
        if kind not in self._MARKET_KINDS or not slug:
            return 400, {"error": "参数不合法"}
        if want:
            # 商城整体门控(market_acquire):管"能不能用商城获取"这个动作本身;每个资源的
            # 等级另由 access(unlocked)逐条强制——双层。只挡"获取",移除不挡(已获取的要能清)。
            if not self._gate_allows(user_id, "market_acquire"):
                return 403, {"error": self._gate_denied_text("market_acquire", ui=True)}
            is_admin = self._is_platform_admin(user_id)
            # only_kind(评审 #9):校验单条资源只建对应类别,不为一次点击重建全货架
            match = next(
                (i for i in self._market_catalog_items(user_id, is_admin, only_kind=kind)
                 if i["kind"] == kind and i["slug"] == slug),
                None,
            )
            if match is None:
                return 404, {"error": "商城里没有这个资源(可能已下架)"}
            if not match.get("unlocked"):
                return 403, {"error": "该资源需要升级会员后才能获取"}
            # 数量配额(负责人:获取数量按会员等级限)——已获取的再点(幂等重放指引)不占新额度,
            # 故只在"这条还没获取过"时判。-1=不限;管理员永远不限(_quota_limit 内已处理)。
            limit = self._quota_limit(user_id, "acquired_items")
            if limit >= 0 and not match.get("acquired"):
                try:
                    from cosmac.db import session_scope as _sc
                    from cosmac.db.market_repo import list_acquired as _la

                    with _sc() as _s:
                        cur = len(_la(_s, user_id=user_id))
                except Exception:
                    cur = 0  # 数不出来宁可放行,不因计数故障把人挡死
                if cur >= limit:
                    return 403, {
                        "error": f"已获取资源已达上限（{cur}/{limit} 个）。"
                                 "在「我的AI工坊 · 已获取」移除不用的，或升级会员扩容。"
                    }
        # 创作者技能=**获取即买断**（P4）：先付清再记获取；扣不动就明确失败、不给货。
        # 已买断过/免费/自己的由 charge_skill_purchase 内部放行不扣（幂等）；平台内置 AI
        # 计费开关不得把创作者明码标价的商品变免费。
        if want and kind == "cskill":
            # 买断前置守卫(修「钱扣了货没到」)：charge_skill_purchase 自带事务先提交扣款，
            # 若随后 add_acquired 因每人 200 条硬上限失败，就会扣了款却没记获取(需人工退款)。
            # 故对**新买断**先确认没撞上限再扣款，把这个窗口关掉。(已买断过的重复点击不受影响：
            # add_acquired 幂等返回 True，且 charge 内部 has_purchased 命中不再扣款。)
            if not match.get("acquired"):
                try:
                    from cosmac.db import session_scope as _sc2
                    from cosmac.db.market_repo import (
                        MAX_ACQUIRED_PER_USER,
                        list_acquired as _la2,
                    )
                    with _sc2() as _s2:
                        if len(_la2(_s2, user_id=user_id)) >= MAX_ACQUIRED_PER_USER:
                            return 400, {"error": "已获取的资源太多了，先移除一些再购买"}
                except Exception:
                    logger.debug("买断前置上限检查失败，放行不拦", exc_info=True)
            try:
                r = self.wallet.charge_skill_purchase(user_id, int(slug))
            except (TypeError, ValueError):
                return 400, {"error": "参数不合法"}
            if not r.get("ok"):
                return 403, {"error": r.get("error") or "购买失败，请稍后重试"}
            if r.get("charged"):
                logger.info(
                    "技能买断：buyer=%s listing=%s 价=%s 抽成=%s 创作者得=%s",
                    user_id, slug, r.get("charged"), r.get("fee"), r.get("net"),
                )
        try:
            from cosmac.db import session_scope
            from cosmac.db.market_repo import add_acquired, remove_acquired

            with session_scope() as s:
                if want:
                    ok = add_acquired(s, user_id=user_id, kind=kind, slug=slug)
                    if not ok:
                        return 400, {"error": "已获取的资源太多了，先移除一些"}
                else:
                    remove_acquired(s, user_id=user_id, kind=kind, slug=slug)
            self._acquired_cache.pop(user_id, None)  # 名册缓存立刻失效,主 AI 下条消息就能感知
            self._acquired_cagent_cache.pop(user_id, None)  # 创作者 Agent 路由同样立即生效
            self._acquired_cskill_cache.pop(user_id, None)  # 买断技能的注入同样立即生效
            return 200, {"ok": True, "acquired": want}
        except Exception:
            logger.exception("写入已获取记录失败")
            return 500, {"error": "保存失败，请稍后重试"}

    def handle_market_acquired_list(self, access_token: str) -> Tuple[int, Dict[str, Any]]:
        """列本人全部「已获取」资源(给「我的AI工坊」的已获取区回显)。需登录。

        逐条对照当前货架补全 名称/描述/解锁态;货架上已找不到的(资源被下架/删除)标
        stale=True,前端提示并允许移除。
        """
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        try:
            from cosmac.db import session_scope
            from cosmac.db.market_repo import list_acquired

            with session_scope() as s:
                got = list_acquired(s, user_id)
        except Exception:
            logger.exception("读取已获取列表失败")
            return 500, {"error": "读取失败"}
        is_admin = self._is_platform_admin(user_id)
        by_key = {
            (i["kind"], i["slug"]): i
            for i in self._market_catalog_items(user_id, is_admin)
        }
        out: List[Dict[str, Any]] = []
        for kind, slug in got:
            it = by_key.get((kind, slug))
            if it:
                out.append({
                    "kind": kind, "slug": slug,
                    "name": it["name"], "description": it["description"],
                    "unlocked": it["unlocked"], "stale": False,
                    "agents": it.get("agents") or [],
                })
            else:
                out.append({
                    "kind": kind, "slug": slug, "name": slug,
                    "description": "", "unlocked": False, "stale": True,
                    "agents": [],
                })
        return 200, {"items": out}

    # ═══ 创作者商城（模块4 Token 经济 P2）：上架 / 收益账本 ═══

    def _is_creator(self, user_id: str) -> bool:
        """是否具备「创作者」资格：会员等级 ≥ creator，或平台管理员（运营自己也能上架）。"""
        if self._is_platform_admin(user_id):
            return True
        try:
            return tier_level(self.members.get_tier(user_id)) >= tier_level(TIER_CREATOR)
        except Exception:
            return False

    def handle_creator_apply_get(self, access_token: str) -> Tuple[int, Dict[str, Any]]:
        """查"我的创作者认证申请"状态（工坊申请入口回显）。需登录。

        返回 {is_creator, cert_fee_cents, application:{...}|null}——已是创作者也返回
        （前端据此不再展示申请入口）。
        """
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        fee = int(self.wallet.config().get("creator_cert_fee_cents") or 0)
        app = None
        try:
            from cosmac.db import cert_repo, session_scope

            with session_scope() as s:
                row = cert_repo.get_application(s, user_id)
                if row is not None:
                    app = {
                        "status": row.status, "reason": row.reason,
                        "name": row.name, "contact": row.contact,
                        "intro": row.intro, "portfolio": row.portfolio,
                        "paid": bool(row.paid), "order_no": row.order_no,
                    }
        except Exception:
            logger.exception("读认证申请失败 user=%s", user_id)
            return 500, {"error": "读取失败"}
        return 200, {
            "is_creator": self._is_creator(user_id),
            "cert_fee_cents": fee,
            "application": app,
        }

    def handle_creator_apply_submit(
        self, access_token: str, body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """提交/重新提交创作者认证申请（P3 类公众号流程）。

        流转（定稿：拒绝不退费、可免费重提）：
        - 新申请 → 存资料；认证费>0 则建认证费订单返回支付方式（付完自动进待审），
          =0 则直接进待审。
        - 被拒后重提 → 已付过费直接回待审（不再收费）；没付过仍要付。
        - 已通过 / 已是创作者 → 拦（无需重复申请）。
        """
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        if self._is_creator(user_id):
            return 400, {"error": "你已是创作者，无需申请认证"}
        name = str((body or {}).get("name") or "").strip()[:128]
        contact = str((body or {}).get("contact") or "").strip()[:255]
        intro = str((body or {}).get("intro") or "").strip()[:2000]
        portfolio = str((body or {}).get("portfolio") or "").strip()[:4000]
        if not name or not contact or not intro:
            return 400, {"error": "称呼、联系方式与自我介绍都不能为空——这是审核的主要依据"}
        try:
            from cosmac.db import cert_repo, session_scope

            fee = int(self.wallet.config().get("creator_cert_fee_cents") or 0)
            with session_scope() as s:
                row = cert_repo.get_application(s, user_id)
                if row is not None and row.status == "approved":
                    return 400, {"error": "你的申请已通过，无需重复提交"}
                row = cert_repo.submit(
                    s, user_id=user_id, name=name, contact=contact,
                    intro=intro, portfolio=portfolio,
                )
                # 免费认证：直接进待审（不建单）
                if fee <= 0 and row.status == "pending_payment":
                    cert_repo.mark_paid(s, user_id, "")
                    row.paid = False  # 免费≠已付费（将来开始收费时老免费户重提要补缴，先如实记）
                    status = "pending_review"
                else:
                    status = row.status
            # 待付费 → 建认证费订单（复用交易系统，测试通道先行）
            if status == "pending_payment":
                from cosmac.trading.service import OrderError
                try:
                    res = self.orders.create_cert_order(user_id=user_id)
                except OrderError as e:
                    return 400, {"error": str(e)}
                co = res["checkout"]
                return 200, {
                    "ok": True, "status": "pending_payment",
                    "order_no": res["order_no"], "amount_cents": res["amount_cents"],
                    "checkout": {"kind": co.kind, "url": co.url,
                                 "address": co.address, "extra": co.extra},
                }
            return 200, {"ok": True, "status": status}
        except Exception:
            logger.exception("提交认证申请失败 user=%s", user_id)
            return 500, {"error": "提交失败，请稍后再试"}

    def handle_creator_admin_applications(
        self, access_token: str
    ) -> Tuple[int, Dict[str, Any]]:
        """管理员：待审核的认证申请列表（含资料全文，审核依据）。"""
        operator = self.client.whoami(access_token)
        if not operator:
            return 401, {"error": "登录已失效，请重新登录"}
        if not self._is_platform_admin(operator):
            return 403, {"error": "仅平台管理员可操作"}
        try:
            from cosmac.db import cert_repo, session_scope

            with session_scope() as s:
                rows = cert_repo.list_pending(s)
            return 200, {"items": [{
                "user_id": r.user_id, "name": r.name, "contact": r.contact,
                "intro": r.intro, "portfolio": r.portfolio,
                "paid": bool(r.paid),
                "created_at": r.created_at.isoformat() if r.created_at else "",
            } for r in rows]}
        except Exception:
            logger.exception("读待审申请失败")
            return 500, {"error": "读取失败"}

    def handle_creator_admin_review(
        self, access_token: str, body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """管理员审核认证申请：通过=授予「创作者会员」（永久）；拒绝=记原因（可免费重提）。"""
        operator = self.client.whoami(access_token)
        if not operator:
            return 401, {"error": "登录已失效，请重新登录"}
        if not self._is_platform_admin(operator):
            return 403, {"error": "仅平台管理员可操作"}
        target = str((body or {}).get("user_id") or "").strip()
        approve = bool((body or {}).get("approve"))
        reason = str((body or {}).get("reason") or "").strip()[:500]
        if not target.startswith("@"):
            return 400, {"error": "参数不合法"}
        if not approve and not reason:
            return 400, {"error": "拒绝时请填写原因（会展示给申请人，指导重新提交）"}
        try:
            from cosmac.db import cert_repo, session_scope

            with session_scope() as s:
                row = cert_repo.review(s, target, approve=approve, reason=reason)
            if row is None:
                return 404, {"error": "该申请不存在或不在待审核状态"}
            if approve:
                # 授予创作者会员（永久；将来要年审再改带期限）。授予失败回滚状态待重试。
                ok = self.members.grant(
                    target, TIER_CREATOR, source="cert", expires_ts=0,
                )
                if not ok:
                    with session_scope() as s:
                        r2 = cert_repo.get_application(s, target)
                        if r2 is not None:
                            r2.status = "pending_review"
                    return 500, {"error": "授予创作者资格失败，请稍后重试"}
            logger.info(
                "认证审核：%s %s %s%s", operator,
                "通过" if approve else "拒绝", target,
                "" if approve else f"（{reason}）",
            )
            return 200, {"ok": True, "status": "approved" if approve else "rejected"}
        except Exception:
            logger.exception("审核认证申请失败 target=%s", target)
            return 500, {"error": "操作失败，请稍后再试"}

    def handle_creator_admin_listings(
        self, access_token: str
    ) -> Tuple[int, Dict[str, Any]]:
        """管理员：待审核的上架列表。含**人设/技能正文全文**——审核就是审内容，
        管理员（平台方）可见；普通商城目录仍绝不下发这些正文。"""
        operator = self.client.whoami(access_token)
        if not operator:
            return 401, {"error": "登录已失效，请重新登录"}
        if not self._is_platform_admin(operator):
            return 403, {"error": "仅平台管理员可操作"}
        try:
            from cosmac.db import listing_repo, session_scope
            from cosmac.db.models import SCOPE_USER
            from cosmac.db.repo import get_agent, get_skill

            with session_scope() as s:
                rows = listing_repo.list_pending(s)
                items = []
                for li in rows:
                    lk = str(li.kind or "agent")
                    if lk == "skill":
                        sk = get_skill(s, SCOPE_USER, li.creator, li.agent_slug)
                        content = sk.instructions if sk else "（源技能已删除）"
                    else:
                        ag = get_agent(s, SCOPE_USER, li.creator, li.agent_slug)
                        content = ag.system_prompt if ag else "（源智能体已删除）"
                    items.append({
                        "id": li.id, "creator": li.creator, "kind": lk,
                        "agent_slug": li.agent_slug, "name": li.name,
                        "description": li.description,
                        "price_tokens": int(li.price_tokens or 0),
                        "system_prompt": content,
                        "created_at": li.updated_at.isoformat() if li.updated_at else "",
                    })
            return 200, {"items": items}
        except Exception:
            logger.exception("读待审上架失败")
            return 500, {"error": "读取失败"}

    def handle_creator_admin_listing_review(
        self, access_token: str, body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """管理员审核上架：通过=在售（on）；拒绝=rejected（记原因，创作者可改后重提）。"""
        operator = self.client.whoami(access_token)
        if not operator:
            return 401, {"error": "登录已失效，请重新登录"}
        if not self._is_platform_admin(operator):
            return 403, {"error": "仅平台管理员可操作"}
        try:
            lid = int((body or {}).get("id"))
        except (TypeError, ValueError):
            return 400, {"error": "参数不合法"}
        approve = bool((body or {}).get("approve"))
        reason = str((body or {}).get("reason") or "").strip()[:500]
        if not approve and not reason:
            return 400, {"error": "拒绝时请填写原因（会展示给创作者）"}
        try:
            from cosmac.db import listing_repo, session_scope

            with session_scope() as s:
                row = listing_repo.review_listing(s, lid, approve=approve, reason=reason)
            if row is None:
                return 404, {"error": "该上架不存在或不在待审核状态"}
            self._acquired_cagent_cache.clear()
            self._acquired_cskill_cache.clear()  # 审核结果立即反映到路由/计费
            logger.info(
                "上架审核：%s %s listing#%s%s", operator,
                "通过" if approve else "拒绝", lid,
                "" if approve else f"（{reason}）",
            )
            return 200, {"ok": True, "status": "on" if approve else "rejected"}
        except Exception:
            logger.exception("审核上架失败 id=%s", lid)
            return 500, {"error": "操作失败，请稍后再试"}

    def handle_creator_listings(self, access_token: str) -> Tuple[int, Dict[str, Any]]:
        """列本人全部上架（含已下架/被封）+ 收益汇总——工坊「我的上架」区回显。需登录。

        非创作者也能查（返回空列表 + is_creator=False），前端据此渲染引导文案。
        """
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        try:
            from cosmac.db import listing_repo, session_scope

            with session_scope() as s:
                rows = listing_repo.list_by_creator(s, user_id)
                summary = listing_repo.earnings_summary(s, user_id)
            return 200, {
                "is_creator": self._is_creator(user_id),
                "fee_pct": int(self.wallet.config().get("platform_fee_pct") or 10),
                "wallet_enabled": self.wallet.enabled(),
                "summary": summary,
                "items": [{
                    "id": li.id, "agent_slug": li.agent_slug, "name": li.name,
                    "kind": str(li.kind or "agent"),
                    "description": li.description,
                    "price_tokens": int(li.price_tokens or 0),
                    "status": li.status, "uses": int(li.uses or 0),
                    "earned": int(li.earned or 0),
                    "review_reason": str(getattr(li, "review_reason", "") or ""),
                } for li in rows],
            }
        except Exception:
            logger.exception("列创作者上架失败")
            return 500, {"error": "读取失败"}

    def handle_creator_publish(
        self, access_token: str, body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """上架/更新：把本人自建 Agent / Skill 上架到商城。

        计费（定稿）：kind=agent → price_tokens = **每次使用**价；kind=skill →
        price_tokens = **一次性买断**价（技能每轮自动注入，按次不可预期，故买断）。
        服务端强制：① 创作者资格（会员等级 ≥ creator）；② 资源必须是本人自建且启用
        （上架是引用，人设/技能正文仍在创作者名下、绝不进商城橱窗）。重复上架=更新价格/文案。
        """
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        if not self._is_creator(user_id):
            return 403, {"error": "上架需要「创作者会员」资格——认证通过后即可上架赚 token"}
        kind = "skill" if str((body or {}).get("kind") or "") == "skill" else "agent"
        agent_slug = str((body or {}).get("agent_slug") or "").strip().lower()
        try:
            price = int((body or {}).get("price_tokens") or 0)
        except (TypeError, ValueError):
            return 400, {"error": "价格必须是整数（token，0=免费）"}
        if price < 0 or price > 1_000_000:
            return 400, {"error": "价格超出范围（0 ~ 100万 token）"}
        # 橱窗文案：默认取资源自身的名称/说明，允许单独传（不改资源本体）
        pool = (
            self._my_skill_items(user_id) if kind == "skill"
            else self._my_agent_items(user_id)
        )
        mine = next((m for m in pool if m.get("slug") == agent_slug), None)
        if mine is None:
            what = "自建技能" if kind == "skill" else "自建智能体"
            return 404, {"error": f"没有这个{what}（或未启用）——先在工坊建好再上架"}
        name = str((body or {}).get("name") or mine.get("name") or agent_slug).strip()[:80]
        description = str(
            (body or {}).get("description") or mine.get("description") or ""
        ).strip()[:300]
        try:
            from cosmac.db import listing_repo, session_scope

            with session_scope() as s:
                try:
                    row = listing_repo.upsert_listing(
                        s, creator=user_id, agent_slug=agent_slug, kind=kind,
                        name=name, description=description, price_tokens=price,
                    )
                except listing_repo.SlugTaken as e:
                    other = "技能" if str(e) == "skill" else "智能体"
                    return 400, {
                        "error": f"标识「{agent_slug}」已被你上架的{other}占用，"
                                 "请把其中一个改个标识再上架"
                    }
                if row is None:
                    return 403, {"error": "该资源已被平台下架，不可重新上架（如有疑问联系管理员）"}
                lid = row.id
            # 上架/更新一律进待审（P3）：原在售的也立即变待审，清全部路由缓存立刻生效。
            self._acquired_cagent_cache.clear()
            self._acquired_cskill_cache.clear()
            return 200, {"ok": True, "id": lid, "status": "pending"}
        except Exception:
            logger.exception("上架失败 user=%s agent=%s", user_id, agent_slug)
            return 500, {"error": "上架失败，请稍后再试"}

    def handle_creator_listing_status(
        self, access_token: str, body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """创作者上/下架自己的 listing（on/off）；管理员可传 banned/on 强制处置任意条目。"""
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        try:
            lid = int((body or {}).get("id"))
        except (TypeError, ValueError):
            return 400, {"error": "参数不合法"}
        status = str((body or {}).get("status") or "").strip()
        is_admin = self._is_platform_admin(user_id)
        # 创作者只能下架（off）；重新上架必须走 publish 进待审（P3 任何更新都重审）。
        allowed = ("on", "off", "banned") if is_admin else ("off",)
        if status not in allowed:
            return 400, {"error": "状态不合法（重新上架请用「上架/更新」按钮，会进入审核）"}
        try:
            from cosmac.db import listing_repo, session_scope

            with session_scope() as s:
                ok = listing_repo.set_status(
                    s, lid, status, creator="" if is_admin else user_id,
                )
            if not ok:
                return 404, {"error": "找不到该上架记录（或无权操作）"}
            # 下架要立刻生效：清全部路由缓存（谁获取过无从得知，全清最稳；量小无碍）
            self._acquired_cagent_cache.clear()
            self._acquired_cskill_cache.clear()
            return 200, {"ok": True}
        except Exception:
            logger.exception("改上架状态失败 id=%s", lid)
            return 500, {"error": "操作失败，请稍后再试"}

    def handle_creator_earnings(
        self, access_token: str, limit: int = 50, offset: int = 0
    ) -> Tuple[int, Dict[str, Any]]:
        """本人分成明细（新→旧分页）+ 汇总——创作者收益账本（本期只可见、不出金）。"""
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        try:
            from cosmac.db import listing_repo, session_scope

            with session_scope() as s:
                rows = listing_repo.list_earnings(
                    s, user_id, limit=limit, offset=offset
                )
                summary = listing_repo.earnings_summary(s, user_id)
            return 200, {
                "summary": summary,
                "items": [{
                    "id": e.id, "agent_slug": e.agent_slug, "buyer": e.buyer,
                    "gross": int(e.gross), "fee": int(e.fee), "net": int(e.net),
                    "created_at": e.created_at.isoformat() if e.created_at else "",
                } for e in rows],
            }
        except Exception:
            logger.exception("读收益明细失败 user=%s", user_id)
            return 500, {"error": "读取失败"}

    def handle_people_list_mine(self, access_token: str) -> Tuple[int, Dict[str, Any]]:
        """列本人维护的协作人能力名册。需登录。

        返回 = 本人 DB 名册 + **admin 后台的全局能力名册**(控制室 cosmac.people)叠加。
        AI 派单时两份本就合并(_list_capabilities_for_tool 同口径);这里若不叠加,就会出现
        QA 报的"管理员后台给用户设了能力,用户打开『我的协作人』全是未设能力"——功能其实
        生效了,但 UI 看不见。同一 user_id 以**本人记录优先**(用户可自己覆盖平台预设);
        全局来的条目带 source='global',前端标「平台已设」。
        """
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        out: List[Dict[str, Any]] = []
        try:
            from cosmac.db import session_scope
            from cosmac.db.person_repo import list_people, to_dict

            with session_scope() as s:
                out = [to_dict(p) for p in list_people(s, user_id)]
        except Exception:
            logger.debug("列个人协作人失败", exc_info=True)
        try:
            mine_by_id = {str(p.get("user_id") or ""): p for p in out}
            for gp in self._people_items():
                uid = str(gp.get("user_id") or "")
                if not uid:
                    continue
                if uid in mine_by_id:
                    # 同一人既有个人记录又有平台预设:个人记录生效(覆盖),但把平台值一并带给前端,
                    # 让 UI 能标「已覆盖平台设置」并展示被覆盖的内容——否则用户在后台改了平台能力、
                    # 这里看不到任何变化,以为"两个入口数据不同步"(负责人实报)。
                    mine_by_id[uid]["overrides_global"] = True
                    mine_by_id[uid]["global_role"] = str(gp.get("role") or "")
                    mine_by_id[uid]["global_expertise"] = str(gp.get("expertise") or "")
                    continue
                out.append({
                    "user_id": uid,
                    "name": str(gp.get("name") or ""),
                    "role": str(gp.get("role") or ""),
                    "expertise": str(gp.get("expertise") or ""),
                    "note": str(gp.get("note") or ""),
                    "enabled": True,
                    "source": "global",
                })
        except Exception:
            logger.debug("叠加全局能力名册失败（忽略）", exc_info=True)
        return 200, {"people": out}

    def handle_admin_people_notes(self, access_token: str) -> Tuple[int, Dict[str, Any]]:
        """后台「人员能力」：列出**全平台的个人标注**(仅平台管理员)。

        负责人实报"设置后没同步":前台「我的协作人」是**个人级**名册(按 owner 隔离),
        后台「人员能力」是**平台级**(控制室 cosmac.people),两套互不可见——管理员在后台
        看不到用户私下标注了谁擅长什么(但 AI 派单其实已合并两份)。这里把个人标注聚合
        出来给后台**只读**展示:{被标注人: [{标注者, 角色, 擅长}...]},不改任何数据归属。
        """
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        if not self._is_platform_admin(user_id):
            return 403, {"error": "仅平台管理员可查看"}
        notes: Dict[str, List[Dict[str, Any]]] = {}
        try:
            from sqlalchemy import select

            from cosmac.db import session_scope
            from cosmac.db.models import PersonProfile

            with session_scope() as s:
                rows = s.execute(
                    select(PersonProfile).order_by(PersonProfile.id.desc()).limit(2000)
                ).scalars().all()
                for p in rows:
                    notes.setdefault(str(p.person_id or ""), []).append({
                        "owner": str(p.owner or ""),
                        "name": str(p.name or ""),
                        "role": str(p.role or ""),
                        "expertise": str(p.expertise or ""),
                        "enabled": bool(p.enabled),
                    })
        except Exception:
            logger.debug("聚合个人标注失败（忽略，后台按无标注展示）", exc_info=True)
        return 200, {"notes": notes}

    def handle_people_promote(
        self, access_token: str, body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """把某条**个人标注**提升为**平台能力**(写控制室 cosmac.people)。仅平台管理员。

        负责人拍板的方案 B:管理员在「我的协作人」里给某人标了能力后,可一键让全平台可见,
        免得同一份信息在前台后台各录一遍。幂等:平台已有同一 user_id 则**覆盖**其 role/
        expertise/name;其余条目原样保留。bot 无控制室写权限时如实报错(不假装成功)。
        """
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        if not self._is_platform_admin(user_id):
            return 403, {"error": "仅平台管理员可同步到平台能力名册"}
        pid = str((body or {}).get("person_id") or "").strip()
        if not pid.startswith("@"):
            return 400, {"error": "无效的用户 id"}
        # 取本人名册里的这条(以设置者自己的记录为准)
        row: Optional[Dict[str, Any]] = None
        try:
            from cosmac.db import session_scope
            from cosmac.db.person_repo import list_people, to_dict

            with session_scope() as s:
                for p in list_people(s, user_id):
                    if str(p.person_id) == pid:
                        row = to_dict(p)
                        break
        except Exception:
            logger.exception("读取个人标注失败")
            return 500, {"error": "读取失败"}
        if row is None:
            return 404, {"error": "你的名册里没有这个人的能力标注"}
        try:
            ctrl = self.client.resolve_alias(self.config.control_room_alias)
            if not ctrl:
                return 500, {"error": "找不到控制室，无法写入平台名册"}
            ev = self.client.get_state_event(ctrl, PEOPLE_EVENT_TYPE) or {}
            people = [p for p in (ev.get("people") or []) if isinstance(p, dict)]
            merged = [p for p in people if str(p.get("user_id") or "") != pid]
            merged.append({
                "user_id": pid,
                "name": str(row.get("name") or ""),
                "role": str(row.get("role") or ""),
                "expertise": str(row.get("expertise") or ""),
                "note": str(row.get("note") or ""),
                "enabled": True,
            })
            ok = self.client.set_state_event(ctrl, PEOPLE_EVENT_TYPE, {"people": merged})
            if not ok:
                return 500, {"error": "写入平台名册失败（可能没有控制室写权限）"}
        except Exception:
            logger.exception("同步平台能力名册失败")
            return 500, {"error": "同步失败，请稍后重试"}
        # _people_items 每次直读控制室(无缓存)，写完主 AI 下条消息即生效，无需失效动作
        return 200, {"ok": True}

    def handle_people_add(
        self, access_token: str, body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """新增/更新本人名册里某个协作人的能力备注。需登录 + people_manage 门控（付费功能）。
        查看/删除自己的数据不拦（同知识库做法），只对"添加/更新"这个增值动作收费。"""
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        if not self._gate_allows(user_id, "people_manage"):
            return 403, {"error": self._gate_denied_text("people_manage", ui=True)}
        person_id = str((body or {}).get("person_id") or "").strip()
        if not person_id.startswith("@") or ":" not in person_id:
            return 400, {"error": "请填写完整的用户 ID（如 @bob:example.invalid）"}
        try:
            from cosmac.db import session_scope
            from cosmac.db.person_repo import to_dict, upsert_person

            with session_scope() as s:
                p = upsert_person(
                    s, owner=user_id, person_id=person_id,
                    name=str(body.get("name") or ""), role=str(body.get("role") or ""),
                    expertise=str(body.get("expertise") or ""),
                    note=str(body.get("note") or ""),
                    enabled=body.get("enabled", True) is not False,
                )
                return 200, {"ok": True, "person": to_dict(p)}
        except ValueError as e:
            return 400, {"error": str(e)}
        except Exception:
            logger.exception("保存个人协作人失败")
            return 500, {"error": "保存失败（数据库不可用？）"}

    def handle_people_delete(
        self, access_token: str, body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """从本人名册删除某协作人（按 person_id）。需登录。只能删自己名册里的（owner=本人）。"""
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        person_id = str((body or {}).get("person_id") or "").strip()
        if not person_id:
            return 400, {"error": "person_id 无效"}
        try:
            from cosmac.db import session_scope
            from cosmac.db.person_repo import delete_person

            with session_scope() as s:
                ok = delete_person(s, user_id, person_id)
            return (200, {"ok": True}) if ok else (404, {"error": "没找到该协作人"})
        except Exception:
            logger.exception("删除个人协作人失败")
            return 500, {"error": "删除失败"}

    # —— 用户个人偏好画像（About me / Outputs：每个用户自己设置，主 AI 注入）——

    def handle_profile_mine(self, access_token: str) -> Tuple[int, Dict[str, Any]]:
        """读本人的个人偏好画像（前端「AI 偏好」回显）。需登录。没设过返回空白默认。"""
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        try:
            from cosmac.db import session_scope
            from cosmac.db.user_profile_repo import get_profile, to_dict

            with session_scope() as s:
                return 200, {"profile": to_dict(get_profile(s, user_id))}
        except Exception:
            logger.debug("读取个人偏好失败", exc_info=True)
            # 读失败也回一份空白默认，不把弹窗卡死（best-effort，与个人额度同口径）
            from cosmac.db.user_profile_repo import to_dict

            return 200, {"profile": to_dict(None)}

    def handle_profile_save(
        self, access_token: str, body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """保存本人的个人偏好画像。需登录。这是个人设置（非增值功能），不走门控。"""
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        b = body or {}
        try:
            from cosmac.db import session_scope
            from cosmac.db.user_profile_repo import to_dict, upsert_profile

            with session_scope() as s:
                p = upsert_profile(
                    s,
                    user_id=user_id,
                    about=str(b.get("about") or ""),
                    style=str(b.get("style") or ""),
                    extra=str(b.get("extra") or ""),
                    enabled=b.get("enabled", True) is not False,
                )
                return 200, {"ok": True, "profile": to_dict(p)}
        except ValueError as e:
            return 400, {"error": str(e)}
        except Exception:
            logger.exception("保存个人偏好失败")
            return 500, {"error": "保存失败（数据库不可用？）"}

    # —— 我的额度（变现第二步：给用户看每个计量项的 已用/上限）——

    def handle_usage_mine(self, access_token: str) -> Tuple[int, Dict[str, Any]]:
        """返回本人各计量项的当前用量与上限（前端「我的额度」展示）。需登录。"""
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        from cosmac.quotas import QUOTA_CATALOG

        out: List[Dict[str, Any]] = []
        try:
            from cosmac.db import session_scope
            from cosmac.db.quota_repo import get_count, period_key

            with session_scope() as s:
                for q in QUOTA_CATALOG:
                    metric = q["key"]
                    limit = self._quota_limit(user_id, metric)
                    if q.get("track") == "existing" and metric == "kb_docs":
                        # 个人库 + 本人建的频道库(负责人口径:频道资源计入建者额度)
                        used = self._kb_docs_used(s, user_id)
                    elif q.get("track") == "existing" and metric == "storage_mb":
                        used = round(self._storage_bytes(user_id) / 1048576, 1)
                    elif q.get("track") == "existing" and metric == "acquired_items":
                        from cosmac.db.market_repo import list_acquired

                        used = len(list_acquired(s, user_id=user_id))
                    else:
                        used = get_count(
                            s, user_id, metric, period_key(str(q.get("period") or "day"))
                        )
                    out.append({
                        "key": metric, "label": q["label"], "unit": q.get("unit", ""),
                        "group": q.get("group", ""), "used": used, "limit": limit,
                    })
        except Exception:
            logger.debug("读取我的用量失败", exc_info=True)
        return 200, {"usage": out}

    def handle_pay_checkout(
        self, access_token: str, body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """下单：用用户 token 验明身份 → 建订单 → 返回支付方式。返回 (状态码, body)。"""
        from cosmac.trading.service import OrderError

        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        plan_slug = str(body.get("plan_slug") or "")
        currency = str(body.get("currency") or "")
        provider = str(body.get("provider") or "manual")
        try:
            res = self.orders.create_order(
                user_id=user_id, plan_slug=plan_slug,
                currency=currency, provider=provider,
            )
        except OrderError as e:
            return 400, {"error": str(e)}
        except Exception:
            logger.exception("下单失败 user=%s plan=%s", user_id, plan_slug)
            return 500, {"error": "下单失败，请稍后再试"}
        co = res["checkout"]
        return 200, {
            "order_no": res["order_no"], "amount_cents": res["amount_cents"],
            "currency": res["currency"], "tier": res["tier"],
            "period_days": res["period_days"],
            "checkout": {"kind": co.kind, "url": co.url, "address": co.address,
                         "extra": co.extra},
        }

    def handle_pay_callback(
        self, provider_name: str, headers: Dict[str, str], body: bytes
    ) -> int:
        """支付平台回调：取对应渠道 adapter 验签 → 归一化 → 幂等开会员。返回 HTTP 状态码。"""
        from cosmac.trading.service import OrderError

        # manual（测试/线下确认）渠道默认**禁用**，避免任何人自助白嫖会员；
        # 要测试整条链时临时设 COSMAC_PAY_ALLOW_MANUAL=1（上线前务必关掉，改用真实渠道）。
        if provider_name == "manual" and os.environ.get(
            "COSMAC_PAY_ALLOW_MANUAL", ""
        ).lower() not in ("1", "true", "yes"):
            return 403
        provider = self.orders.get_provider(provider_name)
        if provider is None:
            return 404
        try:
            ev = provider.parse_callback(headers=headers, body=body)  # 验签失败会抛
        except Exception as e:
            logger.warning("支付回调验签失败 provider=%s: %s", provider_name, e)
            return 400
        if not ev.paid:
            return 200  # 非成功事件（如失败/退款通知），先确认收到、不开会员
        try:
            self.orders.on_payment_success(
                ev.order_no, provider_ref=ev.provider_ref,
                paid_amount_cents=ev.amount_cents, paid_currency=ev.currency,
            )
        except OrderError as e:
            logger.warning("支付回调开通失败 order=%s: %s", ev.order_no, e)
            return 500  # 让平台重试
        except Exception:
            logger.exception("支付回调处理出错 order=%s", ev.order_no)
            return 500
        return 200

    def _reserve_wf_source(self, source_key, conn, user_input, room_id, sender) -> bool:
        """外呼前登记工作流来源事件；新登记返回 True，已存在返回 False。

        这一步放在提交后台池之前，是为了堵住 appservice txn 还没标记 done 时进程崩溃、
        Synapse 重放同一事件导致外部平台重复接单/扣费的窗口。DB 不可用时保持旧行为继续跑。
        """
        try:
            from cosmac.db import session_scope
            from cosmac.db.wf_repo import create_pending, find_by_source_key

            with session_scope() as s:
                if find_by_source_key(s, source_key) is not None:
                    return False
                create_pending(
                    s, slug=conn.get("slug", ""),
                    platform=conn.get("platform", "webhook"),
                    room_id=room_id, sender=sender, user_input=user_input,
                    token="", source_key=source_key,
                )
                return True
        except Exception as e:
            logger.debug("工作流来源幂等登记失败（降级继续执行）：%s", e)
            return True

    def _release_wf_source(self, source_key: str) -> None:
        """回滚来源预约（删尚未提交的 queued 占位）。DB 不可用则忽略。

        M8：命令路径 _run_wf_in_background 池满提交失败时必须调它，否则 queued 占位残留——之后
        同一事件被 Synapse 重放会命中占位、_reserve_wf_source 返回 False → _run_wf_in_background
        返回 True 让用户以为"已提交"实则什么都没跑；且 1 小时后被遗孤回收误报"提交队列中断"。
        （工具路径 _release_workflow_source 早已这么做，命令路径此前漏了。）
        """
        if not source_key:
            return
        try:
            from cosmac.db import session_scope
            from cosmac.db.wf_repo import release_pending_source

            with session_scope() as s:
                release_pending_source(s, source_key)
        except Exception:
            logger.debug("回滚工作流来源预约失败（忽略）", exc_info=True)

    def _record_wf_run(
        self, room_id, sender, conn, user_input, result, source_key: str = ""
    ) -> None:
        """尽力把运行记录落库；DB 不可用就跳过（不影响已拿到的结果）。"""
        try:
            from cosmac.db import session_scope
            from cosmac.db.wf_repo import record_run

            with session_scope() as s:
                record_run(
                    s, slug=conn.get("slug", ""), platform=conn.get("platform", "webhook"),
                    room_id=room_id, sender=sender, user_input=user_input, result=result,
                    source_key=source_key,
                )
        except Exception as e:
            logger.debug("工作流运行记录入库失败（忽略）：%s", e)

    def _is_kb_command(self, text: str) -> bool:
        """是不是「知识」命令——纯字符串判断，不导入 cosmac.db。"""
        t = text.strip()
        low = t.lower()
        return (
            t.startswith("知识")
            or t.startswith("/知识")
            or low == "kb"
            or low.startswith("kb ")
            or low.startswith("/kb")
        )

    def _run_kb_command(self, room_id: str, sender: str, text: str) -> str:
        """执行知识库命令并返回回复文本（私聊→个人库，群→本群库；写操作群里需管理员）。"""
        # 知识库门控：低于门槛者整条知识命令都不放行
        if not self._gate_allows(sender, "knowledge"):
            return self._gate_denied_text("knowledge")
        try:
            # 与主 AI 路径(见 _handle 处 is_dm)同口径：实名频道即使暂时只剩 ≤2 人也按群聊，
            # 否则新频道/退到 2 人的实名频道里发「知识 添加」会误判私聊→写进个人库、并跳过
            # 频道管理员写检查(作用域错乱)。人数兜底只对无名房生效。
            is_dm = (
                self.client.joined_member_count(room_id) <= 2
                and not self._room_is_named_channel(room_id)
            )
        except Exception:
            is_dm = False
        can_write = True if is_dm else self._is_room_admin(room_id, sender)
        # 个人库「添加」的会员配额守卫（M4）：篇数 kb_docs + 存储 storage_mb，与 UI 端 handle_kb_add
        # 同口径。只对私聊(个人库)生效；群库不走它。起始存量算一次，闭包内比对。
        guard = None
        if is_dm:
            kb_limit = self._quota_limit(sender, "kb_docs")
            st_limit = self._quota_limit(sender, "storage_mb")
            used_bytes = self._storage_bytes(sender)

            def guard(cur: int, body_len: int) -> Optional[str]:
                if kb_limit >= 0 and cur >= kb_limit:
                    return f"个人知识库已满（{cur}/{kb_limit} 篇）。升级会员可扩容。"
                if st_limit >= 0 and used_bytes + body_len > st_limit * 1048576:
                    return f"存储空间不足（上限 {st_limit}MB）。删除一些内容或升级会员扩容。"
                return None
        try:
            from cosmac.db import session_scope
            from cosmac.db.kb_cmd import handle_kb_command

            with session_scope() as s:
                reply = handle_kb_command(
                    s,
                    is_dm=is_dm,
                    room_id=room_id,
                    user_id=sender,
                    text=text,
                    can_write=can_write,
                    personal_add_guard=guard,
                )
            if is_dm:
                self._storage_cache = {}  # 个人库可能增删，作废存量缓存（与 UI 路径一致）
            return reply
        except Exception as e:
            logger.warning("知识库命令执行失败：%s", e)
            return "知识库功能暂不可用（服务器可能还没配置数据库）。"

    def _is_skill_command(self, text: str) -> bool:
        """是不是「技能」命令——纯字符串判断，不导入 cosmac.db（避免无谓依赖加载）。"""
        t = text.strip()
        low = t.lower()
        return (
            t.startswith("技能")
            or t.startswith("/技能")
            or low == "skill"
            or low.startswith("skill ")
            or low.startswith("/skill")
        )

    def _run_skill_command(self, room_id: str, sender: str, text: str) -> str:
        """执行技能命令并返回回复文本。作用域：私聊→个人技能，群里→本群技能。

        和 _skill_addendum 一样：cosmac.db 懒导入 + 全程兜异常——服务器没装
        SQLAlchemy / 没配 DB 时，回一句"未启用"而不是让 bot 崩或不吭声。
        """
        try:
            # 与主 AI 路径同口径：实名频道即使暂时只剩 ≤2 人也按群聊，避免误判私聊把技能
            # 写进个人库、并跳过频道管理员写检查(作用域错乱)。人数兜底只对无名房生效。
            is_dm = (
                self.client.joined_member_count(room_id) <= 2
                and not self._room_is_named_channel(room_id)
            )
        except Exception:
            is_dm = False
        # #1 群级技能写操作要求发送者是房间管理员（个人技能/私聊不限）。
        can_write = True if is_dm else self._is_room_admin(room_id, sender)
        try:
            from cosmac.db import session_scope
            from cosmac.db.skill_cmd import handle_skill_command

            with session_scope() as s:
                return handle_skill_command(
                    s,
                    is_dm=is_dm,
                    room_id=room_id,
                    user_id=sender,
                    text=text,
                    can_write=can_write,
                )
        except Exception as e:
            logger.warning("技能命令执行失败：%s", e)
            return "技能功能暂不可用（服务器可能还没配置数据库）。"

    def _is_room_admin(self, room_id: str, user_id: str) -> bool:
        """发送者在该房间是否为管理员（power≥50）。读不到权限 → 保守视为否（写被挡）。

        用于群级技能的写权限判断：群级技能会注入所有群成员的 AI 请求，普通成员不能改。
        """
        try:
            pl = self.client.get_state_event(room_id, "m.room.power_levels", "") or {}
            users = pl.get("users") or {}
            default = pl.get("users_default", 0)
            level = users.get(user_id, default)
            return isinstance(level, int) and level >= 50
        except Exception:
            return False

    # —— 任务时效提醒（定时扫描）：快到期/逾期在任务所属频道内 @ 负责人提醒 ——

    def _fmt_due(self, ts: Optional[int]) -> str:
        """把截止 epoch 秒格式化成 'MM-DD HH:MM'（**产品时区**，见 tzutil），给提醒文案用。"""
        if not ts:
            return "截止时间"
        try:
            from cosmac.tzutil import fmt_ts

            return fmt_ts(int(ts))
        except Exception:
            return "截止时间"

    def _task_reminder_target(self, task: Any) -> str:
        """提醒该 @ 谁：类型化真人执行者 id 优先（能触发推送）；否则退回 assignee 文本标签。"""
        if task.executor_kind == "human" and str(task.executor_ref or "").startswith("@"):
            return str(task.executor_ref)
        return str(task.assignee or "")

    def _assignee_unavailable(self, task: Any) -> Optional[str]:
        """任务负责人当前是否**不可用**，是则返回原因文案（"账号已停用"/"休假·暂不可用"），否则 None。

        只对**类型化真人执行者**（有 @user_id）判定；文本标签负责人对应不到账号，返回 None。
        用于逾期/快到期提醒时判断"是不是人不在导致挂着"，据此升级给下达者、提示改派——避免任务
        永远挂在一个登不进来/在休假的人头上、阻塞其他协作者。
        """
        if task.executor_kind != "human":
            return None
        uid = str(task.executor_ref or "").strip()
        if not uid.startswith("@"):
            return None
        try:
            deact = self._deactivated_user_ids()
            if deact and uid in deact:
                return "账号已停用"
        except Exception:
            pass
        try:
            for p in self._people_items():
                if str(p.get("user_id") or "").strip() == uid and p.get("unavailable"):
                    return "休假·暂不可用"
        except Exception:
            pass
        return None

    def scan_task_reminders(self) -> int:
        """扫一遍任务，给**快到期/逾期**的未完成任务在其频道内发提醒（@负责人），按位去重。

        返回本轮发出的提醒条数。全程兜异常：一条失败不影响其余、更不阻断扫描线程。
        """
        now = int(time.time())
        sent = 0
        try:
            from cosmac.db import session_scope
            from cosmac.db.task_repo import (
                REMIND_OVERDUE, REMIND_SOON, mark_reminded, tasks_needing_reminder,
            )

            with session_scope() as s:
                items = tasks_needing_reminder(
                    s, now_ts=now, soon_secs=self._reminder_soon_secs
                )
                for it in items:
                    t = it["task"]
                    overdue = it["kind"] == "overdue"
                    bit = REMIND_OVERDUE if overdue else REMIND_SOON
                    room = t.room_id or ""
                    if not room:
                        # 没挂在任何频道的任务没法"频道内提醒"——直接标记，避免每轮空扫它。
                        mark_reminded(s, t.id, bit)
                        s.commit()  # 逐条落库（见下方 #2 注释）
                        continue
                    who = self._task_reminder_target(t)
                    when = self._fmt_due(t.due_ts)
                    reason = self._assignee_unavailable(t)  # 负责人不可用的原因（None=可用/判不了）
                    # 升级条件：逾期 一律升级；或负责人已"不可用"(停用/休假)则**提前**升级——
                    # 别等它逾期才发现人不在、任务早已阻塞了别人。升级 = 同时 @ 下达者(owner)提示改派。
                    escalate = overdue or (reason is not None)
                    if overdue:
                        body = f"⚠️ 任务「{t.title}」已逾期（应于 {when} 完成）"
                    else:
                        body = f"⏰ 提醒：任务「{t.title}」将在 {when} 到期"
                    if reason:
                        body += f"，且负责人{reason}"
                    # @ 提及：负责人 +（升级时）下达者，两者去重、只 @ 真实 @id。
                    mentions: List[str] = []
                    if who and who.startswith("@"):
                        mentions.append(who)
                    owner = str(t.sender or "").strip()
                    if escalate and owner.startswith("@") and owner != who:
                        mentions.append(owner)
                    if mentions:
                        body = " ".join(mentions) + " " + body
                    if escalate:
                        body += "，请及时跟进；若负责人无法推进，建议改派他人，以免阻塞其他协作。（详见任务看板）"
                    else:
                        body += "，请及时推进或更新状态（详见任务看板）。"
                    try:
                        self.client.send_text(room, body)
                    except Exception:
                        logger.debug("发任务提醒失败 task=%s room=%s", t.id, room, exc_info=True)
                        continue  # 发失败**不标记**已提醒，下一轮再试
                    mark_reminded(s, t.id, bit)
                    # #2：**逐条提交**——原来整轮扫描共用一个事务、到最后才 commit，若进程崩在循环
                    # 中途，本轮所有 mark_reminded 一起回滚，下一轮会对**已发过提醒**的任务重复 @
                    # 轰炸(逾期任务反复骚扰负责人+下达者)。expire_on_commit=False，逐条 commit 安全。
                    s.commit()
                    sent += 1
        except Exception:
            logger.debug("扫描任务时效提醒失败（忽略本轮）", exc_info=True)
        if sent:
            logger.info("任务时效提醒：本轮发出 %d 条", sent)
        return sent

    # —— 归档催办（负责人需求）：AI 口头问"是否归档"被忽略时的确定性兜底 ——
    # 频道任务**全部完成**且完成后 24h 没动静(没归档) → 在频道里 @频道主 提醒归档;
    # 之后每 24h 催一次,直到有人让 AI 归档(写下 cosmac.project.archived)为止。
    # 上次催办时刻记在房间 state `cosmac.archive.nag`(持久,bot 重启不丢)。
    _ARCHIVE_NAG_STATE = "cosmac.archive.nag"

    def _room_owner_mentions(self, room_id: str) -> List[str]:
        """找频道主(power=100 的真人)用于 @ 提醒;没有 100 就退而找 ≥50 的管理员。
        排除主 AI 与傀儡账号(它们不是"人",@ 了也没人看)。读不到权限表 → 空(不 @ 只发文本)。"""
        try:
            pl = self.client.get_state_event(room_id, "m.room.power_levels", "") or {}
            users = pl.get("users") or {}
            # 主 AI 按 localpart 比对(@guduu:任何域)——域随部署变,别只认配置里的完整 id
            bot_lp = str(self.config.bot_user_id or "").split(":")[0]
            humans = [
                (uid, lv) for uid, lv in users.items()
                if isinstance(lv, int)
                and uid.split(":")[0] != bot_lp
                and not self._worker_slug_of(uid)
            ]
            owners = [uid for uid, lv in humans if lv >= 100]
            if owners:
                return sorted(owners)
            return sorted(uid for uid, lv in humans if lv >= 50)
        except Exception:
            logger.debug("读频道主失败 room=%s", room_id, exc_info=True)
            return []

    def scan_archive_nags(self, nag_secs: int = 24 * 3600) -> int:
        """扫一遍「任务全部完成但未归档」的频道，按 24h 节流发归档催办。返回本轮发出条数。

        判定链（每个频道）：
          ① DB：有任务且全部 done（rooms_all_tasks_done）;
          ② 完成后满 24h（最后一次任务更新距今 ≥ nag_secs）——刚完成时 AI 已口头征询过,
             这 24h 就是"AI 询问被忽略"的观察窗;
          ③ 房间 state 无 cosmac.project.archived(archived=true)——已归档即闭环终点;
          ④ 房间 state cosmac.archive.nag 的 last_ts 距今 ≥ nag_secs——每天最多一条。
        发送顺序:先写 nag state 成功、再发消息——反过来的话写失败会按扫描间隔(15min)轰炸。
        全程兜异常:一个频道失败不影响其余。
        """
        now = int(time.time())
        sent = 0
        try:
            from cosmac.db import session_scope
            from cosmac.db.task_repo import rooms_all_tasks_done

            with session_scope() as s:
                candidates = rooms_all_tasks_done(s)
        except Exception:
            logger.debug("归档催办：读任务失败（跳过本轮）", exc_info=True)
            return 0
        for c in candidates:
            room = c["room_id"]
            try:
                if now - int(c.get("last_update_ts") or 0) < nag_secs:
                    continue  # ② 完成还不满观察窗
                arch = self.client.get_state_event(
                    room, "cosmac.project.archived", "") or {}
                if arch.get("archived"):
                    continue  # ③ 已归档
                nag = self.client.get_state_event(
                    room, self._ARCHIVE_NAG_STATE, "") or {}
                last = int(nag.get("last_ts") or 0)
                if now - last < nag_secs:
                    continue  # ④ 今天已催过
                count = int(nag.get("count") or 0) + 1
                # 先记账再发声(见 docstring);写不进 state(无权限?)就跳过这个房,别轰炸
                if not self.client.set_state_event(
                    room, self._ARCHIVE_NAG_STATE,
                    {"last_ts": now, "count": count},
                ):
                    continue
                owners = self._room_owner_mentions(room)
                at = (" ".join(owners) + " ") if owners else ""
                body = (
                    f"{at}🗄 本频道 {c['total']} 个任务已全部完成，项目似乎可以收尾了。"
                    "是否归档本频道？对我说「归档本频道」即可（归档前我会和你确认收尾摘要）。"
                    "在归档或有新任务之前，我每天会提醒一次。"
                )
                self.client.send_text(room, body)
                sent += 1
            except Exception:
                logger.debug("归档催办失败 room=%s（跳过）", room, exc_info=True)
        if sent:
            logger.info("归档催办：本轮发出 %d 条", sent)
        return sent

    # 默认「频道资源边界」规则(与建频道时写入的同一条;backfill 与工具共用)
    _DEFAULT_CHANNEL_RULE = {
        "label": "频道资源边界",
        "desc": "本频道 AI 仅使用本频道的技能、智能体、规则与知识库"
                "(含管理员显式绑定进本频道的知识源)作答,不引用频道外内容。",
    }

    def backfill_channel_rules(self) -> int:
        """给**存量频道**补写默认「频道资源边界」规则(负责人:每个频道都要有可见 RULE)。

        建频道时的默认写入只覆盖新频道;存量频道规则 tab 仍是 0(线上实报)。本方法扫一遍
        bot 已加入的频道,规则为空的补上这一条——**读旧配置 merge 后整体写回**(set_state_event
        是覆盖语义,不 merge 会把 persona/kbScopes 抹掉)。幂等:已有任何规则的房跳过,
        稳定态零写入。bot 无写权限的房(用户自建、bot 仅是普通成员)写失败忽略——那类房由
        前端「频道管理」弹窗打开时兜底补。返回本轮补写条数。
        """
        done = 0
        try:
            rooms = self.client.joined_rooms()
        except Exception:
            return 0
        for rid in rooms:
            try:
                # 房型/房名判定在 Toolbox 上(共享缓存);bot 类自身没有这俩方法
                if self.toolbox._room_kind(rid) != "channel":
                    continue
                name_ev = self.client.get_state_event(rid, "m.room.name") or {}
                if "控制室" in str(name_ev.get("name") or ""):
                    continue  # 平台配置房不是聊天频道
                cfg = self.client.get_state_event(rid, CHANNEL_CONFIG_EVENT_TYPE) or {}
                # 「rules 键存在」(哪怕空数组)=用户动过——显式删光默认规则也算,**尊重删除,
                # 不复活**(负责人实报:删掉「频道资源边界」重进又出现)。只补从未配置过的房。
                if "rules" in cfg:
                    continue  # 已有规则 或 用户显式清空,都不动
                cfg["rules"] = [dict(self._DEFAULT_CHANNEL_RULE)]
                if self.client.set_state_event(rid, CHANNEL_CONFIG_EVENT_TYPE, cfg):
                    done += 1
                time.sleep(0.2)  # 全量扫描限速,别打爆 Synapse
            except Exception:
                continue
        if done:
            logger.info("存量频道默认规则补写:本轮 %d 个频道", done)
        return done

    def seed_default_control_config(self) -> int:
        """把**代码内置的默认配置落地到控制室**,让发行版出厂即有可见、可改的完整基线
        (负责人:人设/配额/门控/等作为系统默认基础)。

        背景:人设(system_prompt)、门控门槛、配额上限都有代码兜底默认,功能上出厂即生效;
        但控制室对应 state event 为空时,后台管理页(尤其 AI 配置的人设框)显示空白,让人
        误以为"没配置"。这里首启时把默认写进控制室——**幂等,只补空缺,绝不覆盖已配的值**:
        存量已配的实例重启重跑无害;新装实例后台打开即见完整默认。返回本轮补写的项数。

        bot 无控制室写权限(权限不足)时静默跳过——功能不受影响(代码兜底仍在),仅后台仍空白。
        技能/Agent 是代码预置库(122 Agent + 13 技能),商城/名册直接读,无需落地 state。
        """
        n = 0
        try:
            room = self.client.resolve_alias(self.config.control_room_alias)
        except Exception:
            room = None
        if not room:
            return 0
        # 1) AI 控制室只保留人设/工具。顺手清除旧 provider/model/key 当前态，避免
        # 后台继续出现第二套模型配置（历史事件不可删除，已暴露 key 仍需轮换）。
        try:
            cfg = self.client.get_state_event(room, AI_CONFIG_EVENT_TYPE) or {}
            new = dict(cfg)
            changed = False
            for obsolete in ("provider", "model", "api_key", "base_url"):
                if obsolete in new:
                    new.pop(obsolete, None)
                    changed = True
            if not str(new.get("system_prompt") or "").strip():
                new["system_prompt"] = self.config.system_prompt
                changed = True
            if changed:
                if self.client.set_state_event(room, AI_CONFIG_EVENT_TYPE, new):
                    n += 1
                    logger.info("已规范控制室 AI 配置：仅保留人设与工具开关")
        except Exception:
            logger.debug("落地默认人设失败(忽略)", exc_info=True)
        # 2) 门控策略:gates 缺/空 → 写目录默认门槛(能力→最低等级)
        try:
            g = self.client.get_state_event(room, GATING_EVENT_TYPE) or {}
            if not isinstance(g.get("gates"), dict) or not g.get("gates"):
                from cosmac.members import GATE_CATALOG
                gates = {gg["key"]: gg["default"] for gg in GATE_CATALOG}
                if self.client.set_state_event(room, GATING_EVENT_TYPE, {"gates": gates}):
                    n += 1
                    logger.info("已把默认门控策略落地到控制室")
        except Exception:
            logger.debug("落地默认门控失败(忽略)", exc_info=True)
        # 3) 用量配额:limits 缺/空 → 写目录默认(各计量项 free/paid/creator 上限)
        try:
            q = self.client.get_state_event(room, QUOTAS_EVENT_TYPE) or {}
            if not isinstance(q.get("limits"), dict) or not q.get("limits"):
                from cosmac.quotas import QUOTA_CATALOG
                limits = {qq["key"]: dict(qq["defaults"]) for qq in QUOTA_CATALOG}
                if self.client.set_state_event(room, QUOTAS_EVENT_TYPE, {"limits": limits}):
                    n += 1
                    logger.info("已把默认用量配额落地到控制室")
        except Exception:
            logger.debug("落地默认配额失败(忽略)", exc_info=True)
        if n:
            logger.info("控制室默认配置落地:本轮补写 %d 项(幂等,已配的不动)", n)
        return n

    def start_rules_backfill(self) -> None:
        """启动后台线程,延迟一次性补写存量频道的默认规则 + 落地默认配置(幂等,重启重跑无害)。"""
        def _once() -> None:
            time.sleep(90)  # 等服务/sync 稳定再扫
            try:
                self.seed_default_control_config()  # 默认人设/门控/配额落地控制室(出厂基线)
            except Exception:
                logger.debug("默认配置落地失败(忽略)", exc_info=True)
            try:
                self.backfill_channel_rules()
            except Exception:
                logger.debug("存量规则补写失败(忽略)", exc_info=True)

        threading.Thread(target=_once, name="rules-backfill", daemon=True).start()

    def start_reminder_scanner(self) -> None:
        """启动后台守护线程，周期性扫描任务时效并发提醒。

        单实例内定时即可（见 memory wf-reliability-scope：durable 队列/多实例是已知边界、本期不做）。
        """
        interval = self._reminder_interval_secs

        def _loop() -> None:
            time.sleep(min(60, interval))  # 启动后先等一会儿，让服务/sync 就绪
            while True:
                self.scan_task_reminders()
                self.scan_archive_nags()   # 归档催办与任务时效提醒共用一个扫描节奏
                time.sleep(interval)

        threading.Thread(target=_loop, name="task-reminder", daemon=True).start()
        logger.info(
            "任务时效提醒扫描线程已启动（间隔 %ds，快到期窗口 %ds）",
            interval, self._reminder_soon_secs,
        )

    def _room_is_named_channel(self, room_id: str) -> bool:
        """房间有"实名"(非空、不是「中枢 AI」)→ 视为频道。

        私聊/群聊判定的限定条件:实名频道即使只有 2 人也按群聊(只 @ 才回)。
        真正的私聊房要么带 cosmac.ai_session 标记、要么叫「中枢 AI」/无名(旧房),
        不会撞上。结果永久缓存(频道改名极少且只影响该判定);读失败按"非频道"处理
        且不缓存——保守方向是维持私聊可用,下条消息再试。
        """
        cached = self._named_channel_cache.get(room_id)
        if cached is not None:
            return cached
        try:
            ev = self.client.get_state_event(room_id, "m.room.name") or {}
            name = str(ev.get("name") or "").strip()
        except Exception:
            return False
        val = bool(name) and "中枢 AI" not in name and "中枢AI" not in name
        self._named_channel_cache[room_id] = val
        if len(self._named_channel_cache) > 5000:  # 防长期运行字典膨胀
            self._named_channel_cache.clear()
        return val

    def _is_ai_session_room(self, room_id: str) -> bool:
        """判断房间是不是「AI 会话房」(前端建会话时打的 cosmac.ai_session state 标记)。

        结果按房间**永久缓存**——标记建房时打上后不会变,别每条消息打一次 state 查询。
        读失败(网络/403)按 False 处理且**不缓存**,下条消息再试。
        """
        cached = self._ai_session_room_cache.get(room_id)
        if cached is not None:
            return cached
        try:
            ev = self.client.get_state_event(room_id, "cosmac.ai_session")
            val = ev is not None
        except Exception:
            return False  # 读失败:本条按普通房处理,不缓存(下次重试)
        self._ai_session_room_cache[room_id] = val
        if len(self._ai_session_room_cache) > 5000:  # 防长期运行字典膨胀
            self._ai_session_room_cache.clear()
        return val

    def _is_platform_admin(self, user_id: str) -> bool:
        """是否**平台管理员** = 在控制室里 power≥50。用于工作流这类"用服务端共享凭据、
        触发付费/外部操作"的授权——不分 DM/群，堵住"和 bot 开个 DM 就能跑"的绕过。
        非控制室成员/读不到一律视为否（保守拒绝）。
        60 秒缓存(评审 #9):资源可见性/商城目录逐条调它,每次 2 趟 HTTP 太贵;
        控制室 power_levels 变更事件到达时清表(见 _handle_event),平时 60 秒兜底。
        """
        cached = self._admin_flag_cache.get(user_id)
        if cached and time.monotonic() - cached[1] < 60:
            return cached[0]
        flag = self._is_platform_admin_uncached(user_id)
        self._admin_flag_cache[user_id] = (flag, time.monotonic())
        if len(self._admin_flag_cache) > 10000:
            self._admin_flag_cache.clear()
        return flag

    def _is_platform_admin_uncached(self, user_id: str) -> bool:
        """_is_platform_admin 的真实读取体(缓存壳见上)。"""
        try:
            ctrl = self.client.resolve_alias(self.config.control_room_alias)
            if not ctrl:
                return False
            pl = self.client.get_state_event(ctrl, "m.room.power_levels", "") or {}
            users = pl.get("users") or {}
            level = users.get(user_id, pl.get("users_default", 0))
            return isinstance(level, int) and level >= 50
        except Exception:
            return False

    # —— 功能门控：按后台配置的「能力→最低等级」服务端强制 ——

    def _gate_allows(self, sender: str, capability: str) -> bool:
        """sender 是否被允许使用 capability（读控制室 cosmac.gating 配置裁决）。

        规则（见 cosmac.members 门控阶梯）：
          - 门槛 = admin → 仅平台管理员；
          - 门槛 = tier(free/paid/creator) → **平台管理员永远放行**；否则按会员等级比较。
        读不到配置 → GatingStore 回落默认（多为 free，不限制），不失效锁死。
        """
        req = self.gating.required(capability)
        if req == GATE_ADMIN:
            return self._is_platform_admin(sender)
        # tier 门槛：staff（平台管理员）一律放行，免得给自己开会员
        if self._is_platform_admin(sender):
            return True
        return gate_rank(self.members.get_tier(sender)) >= gate_rank(req)

    def _gate_denied_text(self, capability: str, ui: bool = False) -> str:
        """被门控拦下时给用户的友好提示（点名所需等级，引导查/升级会员）。

        ui=True 给**浏览器 HTTP 端点**用（403 的 error 文案直接弹在界面上）：
        label 取括号前的短名（目录里的全称带长解释，弹窗里太啰嗦），引导语改成
        界面动线「右上角升级会员」——聊天场景那句"发「会员」查看"在网页 UI 里不成立。"""
        label = gate_capability_label(capability)
        req = self.gating.required(capability)
        if ui:
            short = label.split("（")[0].split("(")[0].strip() or label
            if req == GATE_ADMIN:
                return f"「{short}」仅平台管理员可用。"
            return f"「{short}」是{tier_label(req)}功能，请开通会员后使用（右上角「升级会员」）。"
        if req == GATE_ADMIN:
            return f"「{label}」仅平台管理员可用。"
        return (
            f"「{label}」需要{tier_label(req)}及以上。"
            "发「会员」查看你的等级，或联系管理员升级。"
        )

    # 工具名 → 门控能力 key（只有这些工具受会员门控；其余由入口的 ai_chat 门控覆盖）
    _TOOL_GATE_MAP = {
        "create_room": "create_room",
        "run_workflow": "workflow_run",
        "search_knowledge": "knowledge",  # 与「知识」命令、RAG 自动注入同一道 knowledge 门
        "web_search": "web_search",       # 联网搜索：共享付费 key、默认仅管理员（见 GATE_CATALOG）
        # 抓网页：与联网搜索同属"对外读取"，共用一道闸（替代被拉黑的 SDK WebFetch）
        "fetch_url": "web_search",
        "assemble_team": "assemble_team",  # 一键建专班：独立门控（默认免费，可在后台调成付费）
        "create_tasks": "task_board",      # AI 拆解任务到看板：独立门控（默认免费）
        "query_hr": "hr_data",             # 人事数据查询：敏感数据，默认仅管理员（见 GATE_CATALOG）
        "query_sales": "sales_data",       # 销售业绩查询：经营敏感数据，默认仅管理员
        # 从 GitHub 装 Skill/Agent：与工坊里手动建同一道闸（custom_skill/custom_agent，
        # 默认付费）。preview 不设门控——它只读、且回调里已按 kind 各查一次，
        # 让用户能先看清是什么再决定要不要为此升级。
        "import_skill_from_url": "custom_skill",
    }

    # —— 用量配额（变现第二步）——

    def _quota_limit(self, user_id: str, metric: str) -> int:
        """某用户某计量项的上限：平台管理员永远不限(-1)；否则按其会员等级取配额。-1=不限。"""
        if self._is_platform_admin(user_id):
            return -1
        try:
            return self.quotas.limit(metric, self.members.get_tier(user_id))
        except Exception:
            return -1  # 读不到配额配置：宁可放行，不锁死

    def _rate_quota_blocked(
        self, user_id: str, metric: str, consume: bool = True
    ) -> Optional[str]:
        """配额检查（可选消费）：超额返回升级提示文案，否则返回 None。

        consume=True 才计数 +1；工具路径传 False（只拦不扣），由工具在**成功路径**上另调
        _tool_quota_consume 扣数——避免"先扣后执行、失败也扣"（审查 bug#7）。
        DB 不可用一律放行（不因计数挂了就把人挡在门外）。管理员/不限额直接放行不计数。
        """
        limit = self._quota_limit(user_id, metric)
        if limit < 0:
            return None
        from cosmac.quotas import metric_meta

        meta = metric_meta(metric) or {}
        period = str(meta.get("period") or "day")
        label = str(meta.get("label") or metric)
        try:
            from cosmac.db import session_scope
            from cosmac.db.quota_repo import consume_if_below, get_count, period_key

            pkey = period_key(period)
            with session_scope() as s:
                if consume:
                    # “判断还有额度 +1”必须是一条带上限守卫的原子 UPDATE；否则并发线程
                    # 都可能读到最后 1 次并一同放行。None 表示本次没有拿到额度。
                    consumed = consume_if_below(
                        s, user_id, metric, pkey, limit, by=1,
                    )
                    if consumed is not None:
                        return None
                used = get_count(s, user_id, metric, pkey)
                if used >= limit:
                    span = "今天" if period == "day" else ("本月" if period == "month" else "")
                    return (
                        f"你{span}的「{label}」额度已用完（{used}/{limit}）。"
                        "升级会员可解锁更多 —— 私聊发「会员」查看，或在「升级会员」里订阅。"
                    )
        except Exception:
            logger.debug("配额计数失败（放行）：metric=%s", metric, exc_info=True)
        return None

    def _wallet_precheck_blocked(self, user_id: str) -> Optional[str]:
        """Token 余额/免费额度前拦（模块4 Token 经济）：不足返回提示文案，否则 None。

        - 总开关关（默认）→ wallet.precheck 恒返回 None（现网零影响）。
        - 平台管理员豁免（与配额/门控一致）。
        - 任何异常一律放行（fail-open）——绝不因计费层出错把用户挡在门外。
        """
        try:
            if self._is_platform_admin(user_id):
                return None
            return self.wallet.precheck(user_id)
        except Exception:
            logger.debug("Token 前拦失败（放行）：user=%s", user_id, exc_info=True)
            return None

    def _wallet_charge(self, user_id: str, usage_tokens: int, room_id: str) -> None:
        """按模型真实输出量扣 token（模块4 Token 经济）。回复成功后调，best-effort。

        总开关关或管理员豁免时不扣；扣费任何异常都吞掉（已发出的回复不因计费失败而回滚）。
        """
        try:
            if usage_tokens <= 0 or self._is_platform_admin(user_id):
                return
            if not self.wallet.enabled():
                return
            r = self.wallet.charge_usage(
                user_id, real_tokens=usage_tokens, room_id=room_id,
            )
            if r.get("charged"):
                logger.info(
                    "Token 扣费：user=%s 真实=%s 扣=%s(免费%s+钱包%s) 余额=%s%s",
                    user_id, r.get("real_tokens"), r.get("charged"),
                    r.get("from_free"), r.get("from_wallet"), r.get("balance"),
                    "（余额不足已扣到0）" if r.get("capped") else "",
                )
        except Exception:
            logger.debug("Token 扣费失败（忽略）：user=%s", user_id, exc_info=True)

    def _tool_gate_check(self, sender: str, tool_name: str) -> Optional[str]:
        """工具门控钩子（注入 Toolbox.gate_check）：放行返回 None，拦下返回拒绝文案。"""
        cap = self._TOOL_GATE_MAP.get(tool_name)
        if not cap:
            return None  # 该工具不单独门控
        if self._gate_allows(sender, cap):
            return None
        return self._gate_denied_text(cap)

    # 工具名 → 可计量配额 metric（超额拦 + 计数）。其余工具不计量。
    _TOOL_QUOTA_MAP = {
        "assemble_team": "teams",       # 一键建专班（建频道+配资源+派单）
        # create_room 也算 teams(负责人实报:免费用户 teams=1 却能反复建专班)——用户说
        # 「建专班」时 AI 常调轻量的 create_room 而非 assemble_team,此前它不受任何配额,
        # 成了免费墙的旁路。两工具各自直接建房、互不调用,不会双扣。
        "create_room": "teams",
        "run_workflow": "workflow_runs",  # 工作流运行次数（每月）
    }

    def _tool_quota_check(self, sender: str, tool_name: str) -> Optional[str]:
        """工具配额钩子（注入 Toolbox.quota_check）：超额返回升级提示。**只查不扣**——
        计数由工具在成功路径上调 quota_consume（审查 bug#7：失败/纯列表查询不该扣）。"""
        metric = self._TOOL_QUOTA_MAP.get(tool_name)
        if not metric:
            return None
        return self._rate_quota_blocked(sender, metric, consume=False)

    def _tool_quota_consume(self, sender: str, tool_name: str) -> None:
        """工具配额**消费**钩子（注入 Toolbox.quota_consume）：计数 +1，绝不抛异常。

        与 _tool_quota_check 配对：check 在执行前拦超额，consume 在工具**做成事**后扣。
        消费本身使用数据库原子上限守卫；AI 回复路径另有用户级锁，保证同一用户从检查到
        工具成功消费之间不会被另一条回复插队。
        """
        metric = self._TOOL_QUOTA_MAP.get(tool_name)
        if not metric:
            return
        try:
            from cosmac.quotas import metric_meta

            from cosmac.db import session_scope
            from cosmac.db.quota_repo import consume_if_below, period_key

            limit = self._quota_limit(sender, metric)
            if limit < 0:
                return  # 管理员/不限额：check 时没拦，也无需计数
            meta = metric_meta(metric) or {}
            pkey = period_key(str(meta.get("period") or "day"))
            with session_scope() as s:
                consumed = consume_if_below(s, sender, metric, pkey, limit, by=1)
                if consumed is None:
                    # 正常单 bot 路径受用户锁保护，不应走到这里；若未来多实例部署且发生
                    # 跨进程竞争，至少数据库不会把计数写穿，并留下清晰告警供架构升级。
                    logger.warning(
                        "工具完成后未拿到配额（疑似跨实例竞态）：user=%s metric=%s",
                        sender,
                        metric,
                    )
        except Exception:
            logger.debug("配额消费失败（忽略）：metric=%s", metric, exc_info=True)

    # 注:原 _launch_campaign(演示派单卡)已删除——「建专班」命令改为交回 AI 走
    # assemble_team 真编排(拆任务/选真 Agent/拉傀儡进群/写 RULE),见 _try_handle_command。


class _DeadlineSocket:
    """给 socket 包一层「整次请求的绝对时限」（#1 真正防住 Slowloris）。

    单纯设 socket timeout 只约束"单次 recv"——攻击者每隔 19s 挤一个字节就能不断重置
    20s 计时器，把请求行/请求头/正文的读取无限拖住，占死一个线程。

    这里把时限**下沉到每次 recv**：每次读前，把 socket 超时设成"距整次请求 deadline 的
    剩余时间"。剩余时间随墙钟单调缩到 0、与对端是否还在发字节无关——所以无论慢速 drip
    怎么发，整次请求都无法越过 deadline。一旦越过就抛 socket.timeout，由上层(请求行/头读取
    或 _read_body)收口：要么优雅关连接、要么回 408。

    因 BaseHTTPRequestHandler 读请求行/头/正文最终都经 SocketIO.readinto → 本对象的
    recv_into，故装一处即覆盖整次请求（默认 HTTP/1.0 一连接一请求，deadline 即请求级）。
    """

    def __init__(self, sock: Any, total_secs: float) -> None:
        self._sock = sock
        self._deadline = time.monotonic() + total_secs

    def recv_into(self, buf: Any, *args: Any) -> int:
        left = self._deadline - time.monotonic()
        if left <= 0:
            raise socket.timeout("request deadline exceeded")  # 上层按超时处理
        self._sock.settimeout(left)
        return self._sock.recv_into(buf, *args)

    def __getattr__(self, name: str) -> Any:
        # close/fileno/send/settimeout/... 一律透传给真实 socket
        return getattr(self._sock, name)


class _Handler(BaseHTTPRequestHandler):
    """HTTP 请求处理器：实现 Matrix Application Service 协议的服务端。

    Synapse 会向我们发起：
      - PUT  .../transactions/{txnId} —— 推送一批事件（核心）。
      - GET  .../users/{userId}       —— 查询某用户是否归我们管。
    """

    # 由工厂注入的对象
    bot: CosmacBot
    hs_token: str

    # #1 防 Slowloris：整次请求的绝对时限（秒）。慢/停的客户端最多占住线程这么久。
    # 真正的强制在 setup() 装的 _DeadlineSocket（把时限下沉到每次 recv），单纯 socket
    # timeout 会被每隔几秒挤一字节的 drip 不断重置、约束不住。
    timeout = 20

    def setup(self) -> None:
        """在标准 setup 之后，把读端 socket 包成 _DeadlineSocket，给整次请求装上绝对时限。

        这样请求行/请求头/正文(都经 SocketIO.readinto → recv_into)都受同一个 deadline 约束，
        慢速 drip 无法分别在"读头"或"读体"阶段把线程拖死。失败则降级为普通 socket timeout。
        """
        super().setup()
        try:
            raw = getattr(self.rfile, "raw", None)  # BufferedReader → SocketIO
            if raw is not None and hasattr(raw, "_sock"):
                raw._sock = _DeadlineSocket(raw._sock, self.timeout)
        except Exception:  # 包装失败不致命：退回 setup() 已设的 socket timeout
            logger.debug("装配请求绝对时限失败（降级为 socket timeout）", exc_info=True)

    # 关掉默认那行嘈杂的访问日志，改用我们自己的 logger
    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: N802
        logger.debug("HTTP " + fmt, *args)

    def _read_body(self, length: int) -> Optional[bytes]:
        """读 length 字节的请求体；靠 setup() 装的 _DeadlineSocket 兜底防 Slowloris。

        _DeadlineSocket 把整次请求的绝对时限下沉到每次 recv：哪怕攻击者每隔几秒挤一个字节，
        读取也无法越过 deadline——越过即抛 socket.timeout，这里 ``except OSError`` 收成 None，
        调用方回 408，不会无限阻塞线程。length 已被调用方按上限校验，单次读入内存可控。
        """
        out = bytearray()
        remaining = length
        while remaining > 0:
            try:
                chunk = self.rfile.read(min(remaining, 65536))
            except OSError:  # socket.timeout（含 _DeadlineSocket 触发的）等
                return None
            if not chunk:
                break
            out += chunk
            remaining -= len(chunk)
        return bytes(out)

    def _check_auth(self) -> bool:
        """校验请求确实来自我们的 Synapse（比对 hs_token）。

        Synapse 会通过 Authorization: Bearer <hs_token> 头，或老式的
        ?access_token= 查询参数携带 token，两种都兼容一下。
        """
        # 用 compare_digest 做常数时间比较，避免 hs_token 被时序侧信道逐字节猜出来
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return hmac.compare_digest(auth[len("Bearer "):], self.hs_token)
        # 兼容老式查询参数
        if "access_token=" in self.path:
            token = self.path.split("access_token=", 1)[1].split("&", 1)[0]
            return hmac.compare_digest(token, self.hs_token)
        return False

    def _send_json(self, status: int, body: Dict[str, Any], *, cors: bool = False) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        # cosmac JSON 都是实时业务数据（钱包、任务、配置、审核等），不能让浏览器按固定
        # URL 缓存旧响应。钱包旧代码正因此出现“后台已入账，用户仍看到 0/空流水”。
        # 服务端统一 no-store 是最后一道保险；前端关键读取也会显式 no-store。
        self.send_header("Cache-Control", "no-store")
        self.send_header("Pragma", "no-cache")
        if cors:
            # 跨源：客户端与 Matrix API 分属不同子域时，浏览器需要 CORS 头才会放行。
            # 默认 *（这些端点要么公开、要么自带 token 校验）；可用 COSMAC_APP_ORIGIN 收紧到具体域名。
            origin = os.environ.get("COSMAC_APP_ORIGIN", "") or "*"
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self) -> None:  # noqa: N802
        # 给浏览器调的端点回 CORS 预检（带 Authorization 头的请求会先发 OPTIONS）
        p = self.path.split("?", 1)[0]
        if (p.startswith("/cosmac/pay/") or p.startswith("/cosmac/member/")
                or p == "/cosmac/stats"
                or p.startswith("/cosmac/tasks")
                or p.startswith("/cosmac/doc/")
                or p.startswith("/cosmac/register/")
                or p.startswith("/cosmac/reset/")
                or p.startswith("/cosmac/login/")
                or p.startswith("/cosmac/onboard/")
                or p.startswith("/cosmac/onboarding/")
                or p.startswith("/cosmac/skills/")
                or p.startswith("/cosmac/agents/")
                or p.startswith("/cosmac/kb/")
                or p.startswith("/cosmac/platform-kb/")
                or p.startswith("/cosmac/people/")
                or p.startswith("/cosmac/user/")
                or p.startswith("/cosmac/my/")
                or p.startswith("/cosmac/market/")   # AI Agent 商城目录（带 Authorization 的 GET 要预检）
                or p.startswith("/cosmac/space/")
                or p.startswith("/cosmac/profile/")
                or p.startswith("/cosmac/usage/")
                or p.startswith("/cosmac/wallet/")   # Token 钱包（余额/流水/充值，带 Authorization）
                or p.startswith("/cosmac/creator/")  # 创作者商城（上架/收益，带 Authorization）
                or p.startswith("/cosmac/admin/")
                or p.startswith("/cosmac/channel/")   # 频道规则文档 AI 一键写      # 后台用户列表拉邮箱（GET 带 Authorization 也要预检）
                or p.startswith("/cosmac/channel/")     # 平台管理员接管频道（bug14）
                or p.startswith("/cosmac/auth/")
                or p.startswith("/cosmac/node/")):     # 节点激活：状态公开、提交携带本人 token
            origin = os.environ.get("COSMAC_APP_ORIGIN", "") or "*"
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Vary", "Origin")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_PUT(self) -> None:  # noqa: N802
        # 只接收事务推送
        if "/transactions/" not in self.path:
            self._send_json(404, {"errcode": "M_UNRECOGNIZED"})
            return
        if not self._check_auth():
            self._send_json(403, {"errcode": "M_FORBIDDEN"})
            return

        # 从路径里取出事务 id（.../transactions/{txnId}?...）
        txn_id = self.path.split("/transactions/", 1)[1].split("?", 1)[0]

        # 读取请求体（里面是事件数组）。同回调端点一样按 Content-Length 限大小、拒负数/非法值，
        # 防把超大请求整个读进内存（纵深防御；事务批量事件给 8MB 余量）。
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            self._send_json(400, {"errcode": "M_NOT_JSON"})
            return
        if length < 0 or length > _MAX_TXN_BODY:
            self._send_json(413, {"errcode": "M_TOO_LARGE"})
            return
        raw = self._read_body(length) if length else b"{}"  # #1 防 Slowloris
        if raw is None:
            self._send_json(408, {"errcode": "M_REQUEST_TIMEOUT"})
            return
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            self._send_json(400, {"errcode": "M_NOT_JSON"})
            return

        events = data.get("events", [])
        # 已处理/重复 → True 回 200；正被处理中(未过期) → False 回 503 让 Synapse 稍后重试
        # （#3：宁可让上游重试，也不在崩溃窗口里把一整批事务永久跳过/丢失）。
        if self.bot.handle_transaction(txn_id, events):
            self._send_json(200, {})
        else:
            self._send_json(503, {"errcode": "M_UNAVAILABLE"})

    def do_GET(self) -> None:  # noqa: N802
        # 登录前读取的最小实例品牌配置：只含名称/Logo/向导状态，绝不解密任何凭据。
        if self.path.split("?", 1)[0] == "/cosmac/instance/config":
            try:
                from cosmac.node_settings import public_config

                self._send_json(200, public_config(), cors=True)
            except Exception:
                logger.exception("读取公开实例配置失败")
                self._send_json(200, {
                    "setup_completed": False,
                    "brand": {"product_name": "GuDuu OS", "company_name": "", "logo_data_url": ""},
                }, cors=True)
            return
        if self.path.split("?", 1)[0] == "/cosmac/admin/node-settings":
            code, payload = self.bot.handle_node_settings_get(self._bearer())
            self._send_json(code, payload, cors=True)
            return
        if self.path.split("?", 1)[0] == "/cosmac/admin/node-update":
            code, payload = self.bot.handle_node_update_status(self._bearer())
            self._send_json(code, payload, cors=True)
            return
        # OEM 邀请注册页：实例代前端向 Nexus 校验分享码，避免跨域和暴露实例授权 KEY。
        if self.path.split("?", 1)[0] == "/cosmac/register/referral":
            from urllib.parse import parse_qs, urlparse
            from cosmac import nexus_link

            qs = parse_qs(urlparse(self.path).query)
            try:
                payload = nexus_link.referral_info((qs.get("code") or [""])[0])
                self._send_json(200, payload, cors=True)
            except nexus_link.ReferralError as exc:
                self._send_json(400, {"error": str(exc)}, cors=True)
            return
        # 公开读「认证前端配置」：前端据此决定登录/注册页要不要挂 Turnstile 人机验证。
        # 只回 site_key(本就是公开的)+ 开关;secret 绝不出现。无需鉴权、可跨源。
        if self.path.split("?", 1)[0] == "/cosmac/auth/config":
            from cosmac import registration
            from cosmac.config import _env
            self._send_json(200, {
                "turnstile": registration.turnstile_enabled(),
                "turnstile_site_key": _env("TURNSTILE_SITE_KEY", ""),  # 与 secret 同走 _env(支持前缀回退,低⑦)
            }, cors=True)
            return
        if self.path.split("?", 1)[0] == "/cosmac/node/activation":
            code, payload = self.bot.handle_node_activation_status()
            self._send_json(code, payload, cors=True)
            return
        # 模块4：公开读上架套餐（给前端「升级会员」展示；无密钥、可跨源）
        if self.path.split("?", 1)[0] == "/cosmac/pay/plans":
            try:
                plans = self.bot.handle_pay_plans()
            except Exception:
                logger.exception("读取套餐失败")
                self._send_json(500, {"error": "读取套餐失败"}, cors=True)
                return
            self._send_json(200, {"plans": plans}, cors=True)
            return
        # 模块4：查"我的会员状态"（带本人 token；给升级弹窗顶部展示）
        if self.path.split("?", 1)[0] == "/cosmac/pay/me":
            auth = self.headers.get("Authorization", "")
            token = auth[len("Bearer "):] if auth.startswith("Bearer ") else ""
            code, payload = self.bot.handle_pay_me(token)
            self._send_json(code, payload, cors=True)
            return

        # 数据看板：平台真实运营指标（带本人 token）
        if self.path.split("?", 1)[0] == "/cosmac/stats":
            auth = self.headers.get("Authorization", "")
            token = auth[len("Bearer "):] if auth.startswith("Bearer ") else ""
            code, payload = self.bot.handle_stats(token)
            self._send_json(code, payload, cors=True)
            return

        # Token 钱包：我的余额/免费额度/充值包（模块4 Token 经济 1d）
        if self.path.split("?", 1)[0] == "/cosmac/wallet/me":
            code, payload = self.bot.handle_wallet_me(self._bearer())
            self._send_json(code, payload, cors=True)
            return
        # Token 钱包：我的流水（?limit=&offset=）
        if self.path.split("?", 1)[0] == "/cosmac/wallet/ledger":
            from urllib.parse import parse_qs, urlparse
            qs = parse_qs(urlparse(self.path).query)
            try:
                limit = int((qs.get("limit") or ["50"])[0])
                offset = int((qs.get("offset") or ["0"])[0])
            except (TypeError, ValueError):
                limit, offset = 50, 0
            code, payload = self.bot.handle_wallet_ledger(
                self._bearer(), limit=limit, offset=offset
            )
            self._send_json(code, payload, cors=True)
            return
        # 创作者认证：我的申请状态（P3）
        if self.path.split("?", 1)[0] == "/cosmac/creator/apply":
            code, payload = self.bot.handle_creator_apply_get(self._bearer())
            self._send_json(code, payload, cors=True)
            return
        # 创作者认证：管理员待审申请列表（P3）
        if self.path.split("?", 1)[0] == "/cosmac/creator/admin/applications":
            code, payload = self.bot.handle_creator_admin_applications(self._bearer())
            self._send_json(code, payload, cors=True)
            return
        # 上架审核：管理员待审上架列表（P3）
        if self.path.split("?", 1)[0] == "/cosmac/creator/admin/listings":
            code, payload = self.bot.handle_creator_admin_listings(self._bearer())
            self._send_json(code, payload, cors=True)
            return
        # 创作者商城：我的上架列表 + 收益汇总（P2）
        if self.path.split("?", 1)[0] == "/cosmac/creator/listings":
            code, payload = self.bot.handle_creator_listings(self._bearer())
            self._send_json(code, payload, cors=True)
            return
        # 创作者商城：收益明细（?limit=&offset=）
        if self.path.split("?", 1)[0] == "/cosmac/creator/earnings":
            from urllib.parse import parse_qs, urlparse
            qs = parse_qs(urlparse(self.path).query)
            try:
                limit = int((qs.get("limit") or ["50"])[0])
                offset = int((qs.get("offset") or ["0"])[0])
            except (TypeError, ValueError):
                limit, offset = 50, 0
            code, payload = self.bot.handle_creator_earnings(
                self._bearer(), limit=limit, offset=offset
            )
            self._send_json(code, payload, cors=True)
            return
        # Token 钱包：管理员查某用户余额+流水（?user_id=，仅平台管理员）
        if self.path.split("?", 1)[0] == "/cosmac/wallet/admin/balance":
            from urllib.parse import parse_qs, urlparse
            qs = parse_qs(urlparse(self.path).query)
            code, payload = self.bot.handle_wallet_admin_balance(
                self._bearer(), (qs.get("user_id") or [""])[0]
            )
            self._send_json(code, payload, cors=True)
            return

        # 组织/人事页：员工花名册（仅平台管理员；带本人 token）
        if self.path.split("?", 1)[0] == "/cosmac/hr/employees":
            auth = self.headers.get("Authorization", "")
            token = auth[len("Bearer "):] if auth.startswith("Bearer ") else ""
            code, payload = self.bot.handle_hr_employees(token)
            self._send_json(code, payload, cors=True)
            return

        # 管理后台：用户名→邮箱 映射（仅平台管理员;用户列表显示邮箱用）
        # 专班归档记录(管理后台「归档记录」页,仅管理员)
        if self.path.split("?", 1)[0] == "/cosmac/admin/archives":
            code, payload = self.bot.handle_admin_archives(self._bearer())
            self._send_json(code, payload, cors=True)
            return
        # 后台「频道详情」点开知识库文档看全文(仅平台管理员)
        if self.path.split("?", 1)[0] == "/cosmac/admin/kb_doc":
            from urllib.parse import parse_qs, urlparse
            qs = parse_qs(urlparse(self.path).query)
            did = (qs.get("id") or [""])[0]
            code, payload = self.bot.handle_admin_kb_doc(self._bearer(), did)
            self._send_json(code, payload, cors=True)
            return
        # 后台「频道管理·详情」:某频道的 RULE/知识库/技能/智能体/记忆(仅平台管理员)
        if self.path.split("?", 1)[0] == "/cosmac/admin/room_detail":
            from urllib.parse import parse_qs, urlparse
            qs = parse_qs(urlparse(self.path).query)
            rid = (qs.get("room_id") or [""])[0]
            code, payload = self.bot.handle_admin_room_detail(self._bearer(), rid)
            self._send_json(code, payload, cors=True)
            return
        if self.path.split("?", 1)[0] == "/cosmac/admin/emails":
            code, payload = self.bot.handle_admin_emails(self._bearer())
            self._send_json(code, payload, cors=True)
            return

        # 任务看板：列出真实任务（带本人 token）
        if self.path.split("?", 1)[0] == "/cosmac/tasks":
            auth = self.headers.get("Authorization", "")
            token = auth[len("Bearer "):] if auth.startswith("Bearer ") else ""
            code, payload = self.bot.handle_tasks_list(token)
            self._send_json(code, payload, cors=True)
            return
        # AI 侧栏「项目文件」：列本人个人知识库文档（带本人 token）
        if self.path.split("?", 1)[0] == "/cosmac/kb/list":
            auth = self.headers.get("Authorization", "")
            token = auth[len("Bearer "):] if auth.startswith("Bearer ") else ""
            code, payload = self.bot.handle_kb_list_mine(token)
            self._send_json(code, payload, cors=True)
            return
        # 频道知识库：列本频道已上传文档（?room_id=）
        # 频道文档全文(频道成员;右侧「关于此频道」点开查看)
        if self.path.split("?", 1)[0] == "/cosmac/kb/room/doc":
            from urllib.parse import parse_qs, urlparse
            qs = parse_qs(urlparse(self.path).query)
            code, payload = self.bot.handle_kb_room_doc(
                self._bearer(),
                (qs.get("room_id") or [""])[0],
                (qs.get("id") or [""])[0],
            )
            self._send_json(code, payload, cors=True)
            return
        if self.path.split("?", 1)[0] == "/cosmac/kb/room/list":
            from urllib.parse import parse_qs, urlparse
            token = self._bearer()
            qs = parse_qs(urlparse(self.path).query)
            room_id = (qs.get("room_id") or [""])[0]
            code, payload = self.bot.handle_kb_room_list(token, room_id)
            self._send_json(code, payload, cors=True)
            return
        # 单端在线：查询"我这台设备是不是被别处登录顶掉的"（?user_id=&device_id=）。
        # **公开端点**——查询者的 token 刚被吊销、没法鉴权;只回答 bool,需同时知道
        # user_id+device_id 才能问,泄露面可忽略(device_id 是随机串,外人拿不到)。
        if self.path.split("?", 1)[0] == "/cosmac/session/kicked":
            from urllib.parse import parse_qs, urlparse
            from cosmac import registration
            qs = parse_qs(urlparse(self.path).query)
            kicked = registration.was_kicked(
                (qs.get("user_id") or [""])[0], (qs.get("device_id") or [""])[0]
            )
            self._send_json(200, {"kicked": kicked}, cors=True)
            return
        # 公开页面内容：隐私政策/帮助中心（?key=privacy|help,无需登录——注册页要用）
        if self.path.split("?", 1)[0] == "/cosmac/page":
            from urllib.parse import parse_qs, urlparse
            qs = parse_qs(urlparse(self.path).query)
            code, payload = self.bot.handle_site_page((qs.get("key") or [""])[0])
            self._send_json(code, payload, cors=True)
            return
        # 私信提示：查某用户是否已停用（?user_id=）
        if self.path.split("?", 1)[0] == "/cosmac/user/deactivated":
            from urllib.parse import parse_qs, urlparse
            token = self._bearer()
            qs = parse_qs(urlparse(self.path).query)
            uid = (qs.get("user_id") or [""])[0]
            code, payload = self.bot.handle_user_deactivated(token, uid)
            self._send_json(code, payload, cors=True)
            return
        # 图文教程：列全局页面树（无需 room_id，全平台一份）
        if self.path.split("?", 1)[0] == "/cosmac/doc/tree":
            token = self._bearer()
            code, payload = self.bot.handle_doc_tree(token)
            self._send_json(code, payload, cors=True)
            return
        # 图文教程：读单页（?id=）
        if self.path.split("?", 1)[0] == "/cosmac/doc/page":
            from urllib.parse import parse_qs, urlparse
            token = self._bearer()
            qs = parse_qs(urlparse(self.path).query)
            try:
                page_id = int((qs.get("id") or ["0"])[0])
            except (TypeError, ValueError):
                self._send_json(400, {"error": "无效页面 id"}, cors=True)
                return
            code, payload = self.bot.handle_doc_page(token, page_id)
            self._send_json(code, payload, cors=True)
            return
        # 入驻模板列表（首次引导读；bot 代读私有控制室，普通用户读不到 state，#9）
        if self.path.split("?", 1)[0] == "/cosmac/onboarding/templates":
            code, payload = self.bot.handle_onboarding_templates(self._bearer())
            self._send_json(code, payload, cors=True)
            return
        # 内置预置技能库（后台技能库页展示；代码内置，读控制室看不到）
        if self.path.split("?", 1)[0] == "/cosmac/skills/presets":
            auth = self.headers.get("Authorization", "")
            token = auth[len("Bearer "):] if auth.startswith("Bearer ") else ""
            code, payload = self.bot.handle_preset_skills(token)
            self._send_json(code, payload, cors=True)
            return
        # 内置预置 Agent 库(后台「智能体」页展示;同 slug 后台新建可覆盖)
        if self.path.split("?", 1)[0] == "/cosmac/agents/presets":
            token = self._bearer()
            code, payload = self.bot.handle_preset_agents(token)
            self._send_json(code, payload, cors=True)
            return
        # 平台共享知识库列表（后台页，仅管理员）
        if self.path.split("?", 1)[0] == "/cosmac/platform-kb/list":
            auth = self.headers.get("Authorization", "")
            token = auth[len("Bearer "):] if auth.startswith("Bearer ") else ""
            code, payload = self.bot.handle_platform_kb_list(token)
            self._send_json(code, payload, cors=True)
            return
        # 个人协作人能力名册：列本人维护的协作人（带本人 token）
        # 后台「人员能力」查看全平台个人标注(方案A,仅管理员只读)
        if self.path.split("?", 1)[0] == "/cosmac/admin/people_notes":
            code, payload = self.bot.handle_admin_people_notes(self._bearer())
            self._send_json(code, payload, cors=True)
            return
        if self.path.split("?", 1)[0] == "/cosmac/people/mine":
            auth = self.headers.get("Authorization", "")
            token = auth[len("Bearer "):] if auth.startswith("Bearer ") else ""
            code, payload = self.bot.handle_people_list_mine(token)
            self._send_json(code, payload, cors=True)
            return
        # 我的额度：本人各计量项的 已用/上限（前端「我的额度」展示）
        # 用户自建 智能体/技能:列表
        if self.path.split("?", 1)[0] == "/cosmac/my/agents":
            code, payload = self.bot.handle_my_agents_list(self._bearer())
            self._send_json(code, payload, cors=True)
            return
        if self.path.split("?", 1)[0] == "/cosmac/my/skills":
            code, payload = self.bot.handle_my_skills_list(self._bearer())
            self._send_json(code, payload, cors=True)
            return
        # 可绑定的工作流清单（工坊「绑定工作流」勾选用）。只回 slug/name/输入提示，
        # url 与凭据名一律不出网（连接器定义在控制室，普通用户读不到，由 bot 代读裁剪）。
        if self.path.split("?", 1)[0] == "/cosmac/my/workflows":
            code, payload = self.bot.handle_my_workflows_list(self._bearer())
            self._send_json(code, payload, cors=True)
            return
        # AI Agent 商城目录:平台真实资源(智能体/技能/工作流/知识库)+按发起人标注解锁/已获取
        if self.path.split("?", 1)[0] == "/cosmac/market/catalog":
            code, payload = self.bot.handle_market_catalog(self._bearer())
            self._send_json(code, payload, cors=True)
            return
        # 本人已获取的商城资源(我的AI工坊「已获取」区回显)
        if self.path.split("?", 1)[0] == "/cosmac/market/acquired":
            code, payload = self.bot.handle_market_acquired_list(self._bearer())
            self._send_json(code, payload, cors=True)
            return
        # 存储空间预检(上传附件前调;?bytes=本次文件大小)
        if self.path.split("?", 1)[0] == "/cosmac/usage/storage-check":
            from urllib.parse import parse_qs, urlparse
            token = self._bearer()
            qs = parse_qs(urlparse(self.path).query)
            code, payload = self.bot.handle_storage_check(token, (qs.get("bytes") or ["0"])[0])
            self._send_json(code, payload, cors=True)
            return
        if self.path.split("?", 1)[0] == "/cosmac/usage/mine":
            auth = self.headers.get("Authorization", "")
            token = auth[len("Bearer "):] if auth.startswith("Bearer ") else ""
            code, payload = self.bot.handle_usage_mine(token)
            self._send_json(code, payload, cors=True)
            return
        # 我的 AI 偏好画像（About me / Outputs）：前端「AI 偏好」回显
        if self.path.split("?", 1)[0] == "/cosmac/profile/me":
            code, payload = self.bot.handle_profile_mine(self._bearer())
            self._send_json(code, payload, cors=True)
            return
        # Synapse 查询"这个用户/别名是否归你管"，回 200 表示存在
        if "/users/" in self.path or "/rooms/" in self.path:
            if not self._check_auth():
                self._send_json(403, {"errcode": "M_FORBIDDEN"})
                return
            self._send_json(200, {})
            return
        self._send_json(404, {"errcode": "M_UNRECOGNIZED"})

    def _bearer(self) -> str:
        """从 Authorization 头取 Bearer token（取不到回空串）。"""
        auth = self.headers.get("Authorization", "")
        return auth[len("Bearer "):] if auth.startswith("Bearer ") else ""

    def _client_ip(self) -> str:
        """取请求方真实 IP（公开注册/登录端点限频用）。

        安全要点（直接决定 IP 限频能不能被绕过）：限频按 IP 计数，所以「取哪个 IP」必须取
        客户端**伪造不了**的那个。
        ⚠️ 绝不能信 X-Forwarded-For 的**首段**——XFF 是普通请求头，客户端能随便塞；nginx 用
        `$proxy_add_x_forwarded_for` 时会把客户端自带的 XFF 原样保留在**前面**、把真实 IP 追加在
        **末尾**。所以首段恰恰最不可信：攻击者每次换一个伪造值，就能让限频器把每个请求都当成
        「新 IP」，绕过全部按 IP 的限频（原实现取首段，正是这个漏洞）。

        取值优先级（最可信 → 兜底）：
          1) X-Real-IP：nginx `proxy_set_header X-Real-IP $remote_addr;` 注入的**单值**，等于
             nginx 看到的直连源地址，客户端伪造无效 → **首选**（前提：反代 /cosmac/auth/ 的
             location 配了这行，见 DEPLOY.md）。
          2) X-Forwarded-For 的**最后一段**：最靠近服务端、由可信反代追加的那一跳；仅在没配
             X-Real-IP 时兜底（只有一段时它既是客户端也是唯一可用值）。
          3) TCP 对端地址：完全没过反代（本地直连）时用它。
        """
        real = (self.headers.get("X-Real-IP", "") or "").strip()
        if real:
            return real
        xff = self.headers.get("X-Forwarded-For", "")
        if xff:
            # 取**最后一段**（可信跳），而非首段（客户端可伪造）
            parts = [p.strip() for p in xff.split(",") if p.strip()]
            if parts:
                return parts[-1]
        try:
            return self.client_address[0]
        except Exception:
            return ""

    def _read_json_body(self, max_len: int) -> Optional[Dict[str, Any]]:
        """按上限读 + 解析 JSON 请求体；超限/超时/非法返回 None（调用方回对应错误）。"""
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            return None
        if length < 0 or length > max_len:
            return None
        raw = self._read_body(length) if length else b"{}"
        if raw is None:
            return None
        try:
            data = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]

        if path == "/cosmac/admin/node-settings":
            body = self._read_json_body(900_000)
            if body is None:
                self._send_json(400, {"error": "请求无效或 Logo 文件过大"}, cors=True)
                return
            code, payload = self.bot.handle_node_settings_save(self._bearer(), body)
            self._send_json(code, payload, cors=True)
            return
        if path == "/cosmac/admin/node-update/approve":
            body = self._read_json_body(_MAX_CALLBACK_BODY)
            if body is None:
                self._send_json(400, {"error": "请求无效"}, cors=True)
                return
            code, payload = self.bot.handle_node_update_approve(self._bearer(), body)
            self._send_json(code, payload, cors=True)
            return

        # 后台频道管理:批量判房型(space/ai/dm/channel,仅平台管理员)
        if path == "/cosmac/admin/room_kinds":
            auth = self.headers.get("Authorization", "")
            token = auth[len("Bearer "):] if auth.startswith("Bearer ") else ""
            body = self._read_json_body(_MAX_CALLBACK_BODY)
            if body is None:
                self._send_json(400, {"error": "请求无效"}, cors=True)
                return
            code, payload = self.bot.handle_admin_room_kinds(token, body)
            self._send_json(code, payload, cors=True)
            return
        # 任务看板：改任务状态/进度（带本人 token）
        if path == "/cosmac/tasks/update":
            auth = self.headers.get("Authorization", "")
            token = auth[len("Bearer "):] if auth.startswith("Bearer ") else ""
            body = self._read_json_body(_MAX_CALLBACK_BODY)
            if body is None:
                self._send_json(400, {"error": "请求无效"}, cors=True)
                return
            code, payload = self.bot.handle_task_update(token, body)
            self._send_json(code, payload, cors=True)
            return

        # 我的 AI 偏好画像：保存 About me / Outputs（带本人 token）
        if path == "/cosmac/profile/me":
            body = self._read_json_body(_MAX_CALLBACK_BODY)
            if body is None:
                self._send_json(400, {"error": "请求无效"}, cors=True)
                return
            code, payload = self.bot.handle_profile_save(self._bearer(), body)
            self._send_json(code, payload, cors=True)
            return

        # 文档教学频道：建/改/删/移动页面（带本人 token；写权限服务端按房间 power 强制）
        if path in (
            "/cosmac/doc/page", "/cosmac/doc/page/update",
            "/cosmac/doc/page/delete", "/cosmac/doc/page/move",
        ):
            token = self._bearer()
            body = self._read_json_body(_MAX_CALLBACK_BODY)
            if body is None:
                self._send_json(400, {"error": "请求无效"}, cors=True)
                return
            if path == "/cosmac/doc/page":
                code, payload = self.bot.handle_doc_create(token, body)
            elif path == "/cosmac/doc/page/update":
                code, payload = self.bot.handle_doc_update(token, body)
            elif path == "/cosmac/doc/page/delete":
                code, payload = self.bot.handle_doc_delete(token, body)
            else:
                code, payload = self.bot.handle_doc_move(token, body)
            self._send_json(code, payload, cors=True)
            return

        # 频道规则文档「AI 一键写」(返回 Markdown,前端编辑区填入)
        if path == "/cosmac/channel/ruledoc_draft":
            body = self._read_json_body(_MAX_CALLBACK_BODY)
            if body is None:
                self._send_json(400, {"error": "请求无效"}, cors=True)
                return
            code, payload = self.bot.handle_ruledoc_draft(self._bearer(), body)
            self._send_json(code, payload, cors=True)
            return
        # 图文教程：让 AI 按主题写草稿（返回 Markdown，后台编辑器填入）
        if path == "/cosmac/doc/draft":
            token = self._bearer()
            body = self._read_json_body(_MAX_CALLBACK_BODY)
            if body is None:
                self._send_json(400, {"error": "请求无效"}, cors=True)
                return
            code, payload = self.bot.handle_doc_draft(token, body)
            self._send_json(code, payload, cors=True)
            return

        # 自建邮箱注册：发验证码（公开、浏览器调，需 CORS）。无 token——用户还没账号。
        if path == "/cosmac/register/request-code":
            body = self._read_json_body(_MAX_CALLBACK_BODY)
            if body is None:
                self._send_json(400, {"error": "请求无效"}, cors=True)
                return
            code, payload = self.bot.handle_register_request_code(body, self._client_ip())
            self._send_json(code, payload, cors=True)
            return

        # 自建邮箱注册：验码 + 建号（公开、浏览器调，需 CORS）。
        if path == "/cosmac/register/verify":
            body = self._read_json_body(_MAX_CALLBACK_BODY)
            if body is None:
                self._send_json(400, {"error": "请求无效"}, cors=True)
                return
            code, payload = self.bot.handle_register_verify(body, self._client_ip())
            self._send_json(code, payload, cors=True)
            return

        # 找回密码：发验证码（公开、浏览器调，需 CORS）。
        if path == "/cosmac/reset/request-code":
            body = self._read_json_body(_MAX_CALLBACK_BODY)
            if body is None:
                self._send_json(400, {"error": "请求无效"}, cors=True)
                return
            code, payload = self.bot.handle_reset_request_code(body, self._client_ip())
            self._send_json(code, payload, cors=True)
            return

        # 找回密码：验码 + 重置密码（公开、浏览器调，需 CORS）。
        if path == "/cosmac/reset/verify":
            body = self._read_json_body(_MAX_CALLBACK_BODY)
            if body is None:
                self._send_json(400, {"error": "请求无效"}, cors=True)
                return
            code, payload = self.bot.handle_reset_verify(body, self._client_ip())
            self._send_json(code, payload, cors=True)
            return

        # 邮箱登录（公开、浏览器调，需 CORS）。
        if path == "/cosmac/login/email":
            body = self._read_json_body(_MAX_CALLBACK_BODY)
            if body is None:
                self._send_json(400, {"error": "请求无效"}, cors=True)
                return
            code, payload = self.bot.handle_login_email(body, self._client_ip())
            self._send_json(code, payload, cors=True)
            return

        # 账号登录收口（用户名+密码 → 后端代理 Synapse + 限频 + 审计）。CORS 走 /cosmac/login/ 白名单。
        if path == "/cosmac/login/account":
            body = self._read_json_body(_MAX_CALLBACK_BODY)
            if body is None:
                self._send_json(400, {"error": "请求无效"}, cors=True)
                return
            code, payload = self.bot.handle_login_account(body, self._client_ip())
            self._send_json(code, payload, cors=True)
            return

        if path == "/cosmac/node/activate":
            # 浏览器只提交自己的 Matrix access token；OEM KEY 由服务器读取环境变量。
            code, payload = self.bot.handle_node_activate(self._bearer())
            self._send_json(code, payload, cors=True)
            return

        # 入驻引导：把模板文档灌进本人个人知识库（带本人 token、浏览器调，需 CORS）。
        if path == "/cosmac/onboard/ingest-kb":
            auth = self.headers.get("Authorization", "")
            token = auth[len("Bearer "):] if auth.startswith("Bearer ") else ""
            body = self._read_json_body(_MAX_CALLBACK_BODY)
            if body is None:
                self._send_json(400, {"error": "请求无效"}, cors=True)
                return
            code, payload = self.bot.handle_onboard_ingest_kb(token, body)
            self._send_json(code, payload, cors=True)
            return

        # 知识库管理（个人库）：添加一篇文档（带本人 token、浏览器调，需 CORS）。
        if path == "/cosmac/kb/add":
            auth = self.headers.get("Authorization", "")
            token = auth[len("Bearer "):] if auth.startswith("Bearer ") else ""
            body = self._read_json_body(_MAX_CALLBACK_BODY)
            if body is None:
                self._send_json(400, {"error": "请求无效"}, cors=True)
                return
            code, payload = self.bot.handle_kb_add(token, body)
            self._send_json(code, payload, cors=True)
            return

        # 知识库管理（个人库）：删除一篇文档（按 id，越权防护在 handler 内）。
        if path == "/cosmac/kb/delete":
            auth = self.headers.get("Authorization", "")
            token = auth[len("Bearer "):] if auth.startswith("Bearer ") else ""
            body = self._read_json_body(_MAX_CALLBACK_BODY)
            if body is None:
                self._send_json(400, {"error": "请求无效"}, cors=True)
                return
            code, payload = self.bot.handle_kb_delete(token, body)
            self._send_json(code, payload, cors=True)
            return

        # 用户自建 智能体/技能:保存/删除(归属=本人,天然越权隔离;存储配额硬管控)
        if path in ("/cosmac/my/agents/save", "/cosmac/my/agents/delete",
                    "/cosmac/my/skills/save", "/cosmac/my/skills/delete",
                    # 从 GitHub 导入 manifest：preview 只取回不落库，confirm 才写
                    "/cosmac/my/import/preview", "/cosmac/my/import/confirm"):
            token = self._bearer()
            body = self._read_json_body(_MAX_CALLBACK_BODY)
            if body is None:
                self._send_json(400, {"error": "请求无效"}, cors=True)
                return
            fn = {
                "/cosmac/my/agents/save": self.bot.handle_my_agents_save,
                "/cosmac/my/agents/delete": self.bot.handle_my_agents_delete,
                "/cosmac/my/skills/save": self.bot.handle_my_skills_save,
                "/cosmac/my/skills/delete": self.bot.handle_my_skills_delete,
                "/cosmac/my/import/preview": self.bot.handle_my_import_preview,
                "/cosmac/my/import/confirm": self.bot.handle_my_import_confirm,
            }[path]
            code, payload = fn(token, body)
            self._send_json(code, payload, cors=True)
            return

        # 工作区挂接：把"我在的频道"挂进"我在的工作区"(普通成员写不了 Space state,bot 代写)。
        if path == "/cosmac/space/adopt":
            token = self._bearer()
            body = self._read_json_body(_MAX_CALLBACK_BODY)
            if body is None:
                self._send_json(400, {"error": "请求无效"}, cors=True)
                return
            code, payload = self.bot.handle_space_adopt(token, body)
            self._send_json(code, payload, cors=True)
            return

        # 频道知识库：上传 / 删除本频道文档（频道管理员，越权防护在 handler 内）。
        if path in ("/cosmac/kb/room/add", "/cosmac/kb/room/delete"):
            token = self._bearer()
            body = self._read_json_body(_MAX_CALLBACK_BODY)
            if body is None:
                self._send_json(400, {"error": "请求无效"}, cors=True)
                return
            if path == "/cosmac/kb/room/add":
                code, payload = self.bot.handle_kb_room_add(token, body)
            else:
                code, payload = self.bot.handle_kb_room_delete(token, body)
            self._send_json(code, payload, cors=True)
            return

        # 平台共享知识库（阶段2，仅管理员）：加/删一篇文档。
        if path == "/cosmac/platform-kb/add":
            auth = self.headers.get("Authorization", "")
            token = auth[len("Bearer "):] if auth.startswith("Bearer ") else ""
            body = self._read_json_body(_MAX_CALLBACK_BODY)
            if body is None:
                self._send_json(400, {"error": "请求无效"}, cors=True)
                return
            code, payload = self.bot.handle_platform_kb_add(token, body)
            self._send_json(code, payload, cors=True)
            return
        if path == "/cosmac/platform-kb/delete":
            auth = self.headers.get("Authorization", "")
            token = auth[len("Bearer "):] if auth.startswith("Bearer ") else ""
            body = self._read_json_body(_MAX_CALLBACK_BODY)
            if body is None:
                self._send_json(400, {"error": "请求无效"}, cors=True)
                return
            code, payload = self.bot.handle_platform_kb_delete(token, body)
            self._send_json(code, payload, cors=True)
            return

        # 注册引导:记录本人选的入驻模板(资源「可用范围」的 tpl: 判定据此生效)。
        if path == "/cosmac/onboarding/select":
            auth = self.headers.get("Authorization", "")
            token = auth[len("Bearer "):] if auth.startswith("Bearer ") else ""
            body = self._read_json_body(_MAX_CALLBACK_BODY)
            if body is None:
                self._send_json(400, {"error": "请求无效"}, cors=True)
                return
            code, payload = self.bot.handle_onboarding_select(token, body)
            self._send_json(code, payload, cors=True)
            return

        # AI Agent 商城:获取/移除某个资源(记入本人账号,主 AI 名册据此优先派单)。
        if path == "/cosmac/market/acquire":
            auth = self.headers.get("Authorization", "")
            token = auth[len("Bearer "):] if auth.startswith("Bearer ") else ""
            body = self._read_json_body(_MAX_CALLBACK_BODY)
            if body is None:
                self._send_json(400, {"error": "请求无效"}, cors=True)
                return
            code, payload = self.bot.handle_market_acquire(token, body)
            self._send_json(code, payload, cors=True)
            return

        # 个人协作人能力名册：添加/更新一条（带本人 token、浏览器调，需 CORS）。
        # 个人标注一键提升为平台能力(方案B,仅管理员)
        if path == "/cosmac/people/promote":
            auth = self.headers.get("Authorization", "")
            token = auth[len("Bearer "):] if auth.startswith("Bearer ") else ""
            body = self._read_json_body(_MAX_CALLBACK_BODY)
            if body is None:
                self._send_json(400, {"error": "请求无效"}, cors=True)
                return
            code, payload = self.bot.handle_people_promote(token, body)
            self._send_json(code, payload, cors=True)
            return
        if path == "/cosmac/people/add":
            auth = self.headers.get("Authorization", "")
            token = auth[len("Bearer "):] if auth.startswith("Bearer ") else ""
            body = self._read_json_body(_MAX_CALLBACK_BODY)
            if body is None:
                self._send_json(400, {"error": "请求无效"}, cors=True)
                return
            code, payload = self.bot.handle_people_add(token, body)
            self._send_json(code, payload, cors=True)
            return

        # 平台管理员「接管」频道:给自己在该频道授 power=100,以便改频道配置/技能(bug14)。
        if path == "/cosmac/channel/claim-admin":
            auth = self.headers.get("Authorization", "")
            token = auth[len("Bearer "):] if auth.startswith("Bearer ") else ""
            body = self._read_json_body(_MAX_CALLBACK_BODY)
            if body is None:
                self._send_json(400, {"error": "请求无效"}, cors=True)
                return
            code, payload = self.bot.handle_channel_claim_admin(token, body)
            self._send_json(code, payload, cors=True)
            return

        # 个人协作人能力名册：删除一条（按 person_id）。
        if path == "/cosmac/people/delete":
            auth = self.headers.get("Authorization", "")
            token = auth[len("Bearer "):] if auth.startswith("Bearer ") else ""
            body = self._read_json_body(_MAX_CALLBACK_BODY)
            if body is None:
                self._send_json(400, {"error": "请求无效"}, cors=True)
                return
            code, payload = self.bot.handle_people_delete(token, body)
            self._send_json(code, payload, cors=True)
            return

        # 模块4：下单（前端「升级会员」调）。用用户自己的 access token 验明身份再建单。
        if path == "/cosmac/member/lifetime-activate":
            body = self._read_json_body(_MAX_CALLBACK_BODY)
            if body is None:
                self._send_json(400, {"error": "请求无效"}, cors=True)
                return
            code, payload = self.bot.handle_lifetime_activate(self._bearer(), body)
            self._send_json(code, payload, cors=True)
            return

        if path == "/cosmac/pay/checkout":
            auth = self.headers.get("Authorization", "")
            token = auth[len("Bearer "):] if auth.startswith("Bearer ") else ""
            body = self._read_json_body(_MAX_CALLBACK_BODY)
            if body is None:
                self._send_json(400, {"error": "请求无效"}, cors=True)
                return
            code, payload = self.bot.handle_pay_checkout(token, body)
            self._send_json(code, payload, cors=True)
            return

        # Token 钱包：充值下单（前端「Token 充值」调；回调复用 /cosmac/pay/callback/*）
        if path == "/cosmac/wallet/checkout":
            body = self._read_json_body(_MAX_CALLBACK_BODY)
            if body is None:
                self._send_json(400, {"error": "请求无效"}, cors=True)
                return
            code, payload = self.bot.handle_wallet_checkout(self._bearer(), body)
            self._send_json(code, payload, cors=True)
            return
        # 创作者认证：提交/重新提交申请（P3）
        if path == "/cosmac/creator/apply":
            body = self._read_json_body(_MAX_CALLBACK_BODY)
            if body is None:
                self._send_json(400, {"error": "请求无效"}, cors=True)
                return
            code, payload = self.bot.handle_creator_apply_submit(self._bearer(), body)
            self._send_json(code, payload, cors=True)
            return
        # 创作者认证：管理员审核（P3）
        if path == "/cosmac/creator/admin/review":
            body = self._read_json_body(_MAX_CALLBACK_BODY)
            if body is None:
                self._send_json(400, {"error": "请求无效"}, cors=True)
                return
            code, payload = self.bot.handle_creator_admin_review(self._bearer(), body)
            self._send_json(code, payload, cors=True)
            return
        # 上架审核：管理员通过/拒绝（P3）
        if path == "/cosmac/creator/admin/listing_review":
            body = self._read_json_body(_MAX_CALLBACK_BODY)
            if body is None:
                self._send_json(400, {"error": "请求无效"}, cors=True)
                return
            code, payload = self.bot.handle_creator_admin_listing_review(
                self._bearer(), body
            )
            self._send_json(code, payload, cors=True)
            return
        # 创作者商城：上架/更新（P2）
        if path == "/cosmac/creator/publish":
            body = self._read_json_body(_MAX_CALLBACK_BODY)
            if body is None:
                self._send_json(400, {"error": "请求无效"}, cors=True)
                return
            code, payload = self.bot.handle_creator_publish(self._bearer(), body)
            self._send_json(code, payload, cors=True)
            return
        # 创作者商城：上/下架（创作者 on/off；管理员可 banned）
        if path == "/cosmac/creator/status":
            body = self._read_json_body(_MAX_CALLBACK_BODY)
            if body is None:
                self._send_json(400, {"error": "请求无效"}, cors=True)
                return
            code, payload = self.bot.handle_creator_listing_status(self._bearer(), body)
            self._send_json(code, payload, cors=True)
            return
        # Token 钱包：管理员手动加/减 token（后台「Token 经济」页）
        if path == "/cosmac/wallet/admin/adjust":
            body = self._read_json_body(_MAX_CALLBACK_BODY)
            if body is None:
                self._send_json(400, {"error": "请求无效"}, cors=True)
                return
            code, payload = self.bot.handle_wallet_admin_adjust(self._bearer(), body)
            self._send_json(code, payload, cors=True)
            return

        # 模块4：支付回调 /cosmac/pay/callback/<provider>。真实渠道是平台服务端验签调用；
        # 但 manual(测试)通道是**浏览器**调的 → 响应必须带 CORS 头，否则前端报 Failed to fetch。
        # 给真实渠道带 CORS 也无害（它们是服务端调用、忽略该头）。
        if path.startswith("/cosmac/pay/callback/"):
            provider = path.split("/cosmac/pay/callback/", 1)[1].split("/", 1)[0]
            try:
                length = int(self.headers.get("Content-Length", 0))
            except (TypeError, ValueError):
                self._send_json(400, {"error": "bad content-length"}, cors=True)
                return
            if length < 0 or length > _MAX_CALLBACK_BODY:
                self._send_json(413, {"error": "bad body length"}, cors=True)
                return
            raw = self._read_body(length) if length else b"{}"
            if raw is None:
                self._send_json(408, {"error": "request timeout"}, cors=True)
                return
            hdrs = {k: v for k, v in self.headers.items()}
            code = self.bot.handle_pay_callback(provider, hdrs, raw or b"{}")
            self._send_json(code, {} if code == 200 else {"error": code}, cors=True)
            return

        # 外部工作流平台的异步回调：/cosmac/wf/callback/<run_id>?token=...
        # **不**用 hs_token 鉴权（这是外部平台调的，不是 Synapse）；用每次运行的一次性 token。
        if "/cosmac/wf/callback/" not in self.path:
            self._send_json(404, {"errcode": "M_UNRECOGNIZED"})
            return
        # 路径形如 /cosmac/wf/callback/<run_id>[/<token>][?token=...]
        try:
            tail = self.path.split("/cosmac/wf/callback/", 1)[1].split("?", 1)[0]
            parts = tail.split("/")
            run_id = int(parts[0])
        except (ValueError, IndexError):
            self._send_json(400, {"error": "bad run id"})
            return
        # #4：token 优先请求头（不进 URL/日志）；其次 URL 路径段；最后兼容老 ?token=。
        token = (self.headers.get("X-Cosmac-Token") or "").strip()
        if not token and len(parts) > 1 and parts[1]:
            token = parts[1]
        if not token and "token=" in self.path:
            token = self.path.split("token=", 1)[1].split("&", 1)[0]
        # #3 防 DoS：验证前就按 Content-Length 限制请求体大小，绝不把超大请求整个读进内存。
        # **负数/非法值要拒**：Content-Length:-1 不会 >上限、read(-1) 会读到 EOF（无界）；
        # 非整数会让 int() 抛 ValueError。故要求 0 ≤ length ≤ 上限，否则直接拒、不读 body。
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            self._send_json(400, {"error": "bad content-length"})
            return
        if length < 0 or length > _MAX_CALLBACK_BODY:
            self._send_json(413, {"error": "bad body length"})
            return
        # #1：按总时限分块读，防 Slowloris 慢速占住线程
        raw = self._read_body(length) if length else b"{}"
        if raw is None:
            self._send_json(408, {"error": "request timeout"})
            return
        # #4：JSON 非法 → 回 400 且**不动 pending**。绝不能把解析失败当成"无内容的成功"——
        # 那样会发"（无内容）"并结清运行，平台收到 200 后再也无法重投正确结果。
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid json"})
            return
        if not isinstance(body, dict):
            self._send_json(400, {"error": "expected json object"})
            return
        code = self.bot.handle_wf_callback(run_id, token, body)
        self._send_json(code, {} if code == 200 else {"error": code})


class _BoundedThreadingHTTPServer(ThreadingHTTPServer):
    """带**并发连接上限**的 ThreadingHTTPServer（#3 防连接洪泛耗尽线程）。

    ThreadingHTTPServer 每个连接开一个线程；单纯靠每请求 20s 时限，攻击者只要持续高频
    建连，仍能在窗口内堆出大量线程。这里用 BoundedSemaphore 卡住"同时在处理的连接数"：
    超限的新连接**直接关闭、不开线程**，从源头封住线程膨胀。
    （仍建议在 nginx 加 limit_conn 做网关层兜底；这里是应用层的最后一道。）
    """

    _max_conns = 128  # 同时在处理的连接上限（appservice 正常并发远低于此）

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._conn_sem = threading.BoundedSemaphore(self._max_conns)

    def process_request(self, request: Any, client_address: Any) -> None:
        # 抢不到名额 = 并发已满：直接关连接、不开线程（防线程耗尽）
        if not self._conn_sem.acquire(blocking=False):
            logger.warning("并发连接达上限 %d，拒绝新连接（防线程耗尽）", self._max_conns)
            self.shutdown_request(request)
            return
        super().process_request(request, client_address)

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._conn_sem.release()  # 处理完归还名额


def run(config: CosmacConfig) -> None:
    """启动主 AI Bot 的 HTTP 服务，开始监听 Synapse 推来的事件。"""
    bot = CosmacBot(config)
    # 启动时把主 AI 的群内显示名设为品牌名（用户看到的是它，而非 @guduu 用户 id）
    bot.client.set_displayname(config.bot_displayname)
    # #2：清理上次进程遗留的未完成工作流运行（in-flight 随重启消失），通知用户别干等
    bot.recover_interrupted_runs()
    # #3：预热门控策略缓存——避免"首读失败→暂用默认→付费门控被绕过"的窗口（best-effort）
    bot.gating.warm()
    # #4：启动时按控制室「期望管理员集」对齐一次成员权限。对齐平时只在期望集**事件到达时**
    # 触发——若当时 bot 没收到(掉线/旧版只删不加的缺口)，新管理员会一直卡在"控制室 power<50、
    # 接管频道 403"。启动兜底一次，重启即自愈（best-effort，失败不阻断启动）。
    try:
        ctrl = bot.client.resolve_alias(config.control_room_alias)
        if ctrl:
            ev = bot.client.get_state_event(ctrl, CONTROL_ADMINS_EVENT_TYPE) or {}
            if ev.get("admins"):
                bot._reconcile_control_members(ctrl, ev)
    except Exception:
        logger.debug("启动时对齐控制室成员失败（忽略）", exc_info=True)
    # 生产红线：manual(测试/线下确认)支付通道一旦开启，浏览器即可触发开通会员。启动时大声告警，
    # 避免误把 COSMAC_PAY_ALLOW_MANUAL 带上生产（上线前必须关）。
    if os.environ.get("COSMAC_PAY_ALLOW_MANUAL", "").lower() in ("1", "true", "yes"):
        logger.warning(
            "⚠️ COSMAC_PAY_ALLOW_MANUAL 已开启：manual 支付通道可被浏览器触发开通会员，"
            "仅供测试！生产环境务必关闭此开关。"
        )

    # #5：启动任务时效提醒扫描线程——周期性扫"快到期/逾期"未完成任务，在其频道内 @ 负责人提醒。
    bot.start_reminder_scanner()
    bot.start_rules_backfill()   # 存量频道补默认「频道资源边界」规则(一次性,幂等)
    # 模块6：实例→GuDuu Nexus 母舰心跳（COSMAC_NEXUS_URL+COSMAC_OEM_KEY 齐备才启动）
    nexus_link.start(config, bot.operating_stats)

    # 把 bot 和 hs_token 注入到 Handler 类上（http.server 用类、不便传参，用 partial 构造）
    handler_cls = partial(_make_handler, bot=bot, hs_token=config.hs_token)

    server = _BoundedThreadingHTTPServer(
        (config.listen_host, config.listen_port), handler_cls
    )
    logger.info(
        "GuDuu OS 主 AI Bot 已启动: 监听 http://%s:%d ，连接 Synapse %s ，模型后端=%s",
        config.listen_host,
        config.listen_port,
        config.homeserver_url,
        config.llm_provider,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在关闭…")
        server.shutdown()


def _make_handler(*args: Any, bot: CosmacBot, hs_token: str, **kwargs: Any) -> _Handler:
    """构造一个带有 bot/hs_token 的请求处理器实例。"""
    handler = _Handler.__new__(_Handler)
    handler.bot = bot
    handler.hs_token = hs_token
    _Handler.__init__(handler, *args, **kwargs)
    return handler
