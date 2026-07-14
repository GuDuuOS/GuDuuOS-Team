"""CosMac Star 主 AI —— Application Service Bot（最小骨架）。

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
import json
import logging
import os
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
from cosmac.config import (
    AGENTS_EVENT_TYPE,
    AI_CONFIG_EVENT_TYPE,
    CHANNEL_CONFIG_EVENT_TYPE,
    CONTROL_ADMINS_EVENT_TYPE,
    ONBOARDING_TEMPLATES_EVENT_TYPE,
    PEOPLE_EVENT_TYPE,
    RULES_EVENT_TYPE,
    SKILLS_EVENT_TYPE,
    WORKFLOWS_EVENT_TYPE,
    CosmacConfig,
)
from cosmac.members import (
    GATE_ADMIN,
    MEMBER_TIERS,
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
    "5. 每次回复尽量落一个明确的「下一步」，把事情向前推进。"
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
        # 模块4 交易系统：订单服务（读控制室套餐 cosmac.plans + 建订单 + 支付成功开会员）。
        # 前端「升级会员」走 bot 的 /cosmac/pay/* 端点调它（前端够不到 cosmac DB）。
        from cosmac.trading.service import OrderService

        self.orders = OrderService(
            self.members, self.client, config.control_room_alias
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
        # 频道清单可见范围：管理员/负责人可跨工作区看全部频道，普通用户只看自己在的（隐私边界）。
        self.toolbox.is_admin = self._is_platform_admin
        # 资源存在性校验(组班链路完善):assemble_team 据此识别"库里没有的 Agent/Skill"并提醒缺口。
        # M2 越权修复:带 for_user 时按发起人 access 过滤——发起人**够不到**的受限智能体不进可见集,
        # assemble_team 里点名它当 lead/worker 会被当"缺口"剔除(不注入其付费人设),堵住"点名绕过
        # 名册过滤"。for_user=None 保持全量(供无发起人上下文的场景)。
        self.toolbox.known_agents = lambda for_user=None: {
            str(a.get("slug") or "")
            for a in self._global_agent_items()
            if a.get("slug") and (for_user is None or self._resource_visible(a, for_user))
        }
        # 用 _skill_library(含预置技能):否则主 AI 组班时绑预置技能会被误报"库里没有"
        self.toolbox.known_skills = lambda for_user=None: {
            str(s.get("slug") or "")
            for s in self._skill_library()
            if s.get("slug") and (for_user is None or self._resource_visible(s, for_user))
        }
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
        # SDK 引擎回退告警的节流时间戳(1小时最多向控制室发一条,防刷屏)
        self._engine_alert_ts: float = 0.0        # 上次读到的配置覆盖
        # —— 任务时效提醒（定时扫描）——扫描间隔 + "快到期"窗口，都可用 env 调；单实例内定时够用。
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

        # 忽略主 AI 自己发的消息，否则会无限自我回复
        if sender == self.config.bot_user_id:
            return

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
            if (not is_dm and not self._is_bot_mentioned(content)
                    and not self._agent_mention_hit(room_id, sender, user_text)):
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
            # 用量配额（变现第二步）：每天 AI 对话条数。超额提示升级并停在这（不消耗 LLM）。
            # L2：这里**只查不扣**——真正出成回复后才计数(见下方 send_text 成功之后)。否则 LLM
            # 报错/超时/工具循环崩了也照扣，用户白白少一次额度却没得到任何回复(与工具路径"成功
            # 才扣"、#7 失败兜底同口径)。
            quota_msg = self._rate_quota_blocked(sender, "ai_msg_daily", consume=False)
            if quota_msg:
                self.client.send_text(room_id, quota_msg)
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
                # 档3b：专班里若点名了某协作 Agent（按名/slug），改用该 worker 的人设/技能/模型
                # 回这条（任务RULE 不变、仍受约束）；没点名则维持 lead（项目主AI）。
                gctx = self._apply_worker_routing(text or user_text, gctx, sender=sender)
                # 按 (本群, 发起人) 算出本轮 system addendum：人设 + 技能 + 知识库检索片段(RAG)。
                # 任何失败（DB 没装/没数据/出错）都返回空串、绝不阻断回复（见 _skill_addendum）。
                # 图文教程答疑：全局图文(付费可读)会在 _kb_context 里按 doc_read 门控自动纳入 RAG，
                # 让中枢 AI 也能基于平台图文内容作答（无需前端传作用域）。
                extra_system = self._skill_addendum(
                    room_id, sender, query=text or user_text, gctx=gctx,
                )
                # 双层作用域指令(频道分身 vs 全局助理):告诉 AI 它现在是哪种身份、边界在哪。
                # 智能水平两种模式相同(同一引擎/能同样拆任务建专班),只是"能拿到的原料"不同。
                extra_system = self._scope_directive(is_dm) + (
                    ("\n\n" + extra_system) if extra_system else ""
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
                )
                reply = self._run_agent_engine(
                    agent, text or user_text, tool_ctx, extra_system, history,
                    model_override=gctx.get("model", ""),  # 群级模型联动:SDK 引擎也认群模型
                )
                # 幂等发送：用 event_id 派生固定 txn_id，让 Synapse 据此去重。
                # 场景：同一事务里若有别的事件失败，handle_transaction 会让 Synapse 重发**整批**，
                # 已成功的这条 AI 回复会被重新处理；固定 txn_id 保证群里不会冒出两条同样的回复。
                self.client.send_text(
                    room_id, reply,
                    txn_id=f"cosmac-ai-{event_id}" if event_id else None,
                )
                # L2：回复真正发出后才消费当日 AI 对话额度（失败走下面的 except 分支、不扣）。
                self._rate_quota_blocked(sender, "ai_msg_daily", consume=True)
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

    # 短期记忆窗口：最多带最近这么多条历史；单条正文截断长度（控 token）。
    _HISTORY_LIMIT = 12

    # 长期记忆：每多少轮回复后台重摘要一次（攒一批再摘，省 LLM 调用）；摘要字数上限。
    _MEMORY_SUMMARIZE_EVERY = 8
    _MEMORY_SUMMARY_CHARS = 400

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
            agent_slugs = gctx.get("skill_slugs", [])
            items = (
                # 全局技能按发起人的「可用范围」过滤(资源级权限:等级/模板/仅管理员);
                # 群绑定的(_agent_skill_items)不过滤——绑定是管理员显式配置,即授权。
                self._global_skill_items(for_user=sender)
                + self._db_skill_items(room_id, sender)
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
            kb_text = self._kb_context(
                room_id, sender, query, extra_scopes,
                bound_sources=gctx.get("kb_scopes"),
            )
            wf_text = self._preset_workflows_text(gctx.get("workflow_slugs") or [])
            # 当前时间：让模型能把"3天后/下周五"这类相对期限换算成绝对日期（拆任务设 due 用）。
            now_text = "【当前时间】" + time.strftime("%Y-%m-%d %H:%M（%A）", time.localtime())
            # 时间 → 交互准则(内置基线) → 平台规则 → 任务RULE → 人设 → 用户偏好 → 长期记忆 → 技能 → 知识库 → 预置工作流
            return "\n\n".join(
                p for p in (
                    now_text, _INTERACTION_POLICY,
                    rules_text, task_rule_text, persona, user_pref_text,
                    mem_text, skills_text, kb_text, wf_text,
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
        user_scopes: List[str] = [sender] if sender else []
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
        if self._doc_can_read(sender) and self._GLOBAL_DOC_ROOM not in scopes:
            scopes.append(self._GLOBAL_DOC_ROOM)
        hits = self._kb_retrieve(
            room_id, sender, query, extra_scopes=scopes, bound_sources=bound_sources,
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
        hits = self._kb_retrieve(ctx.room_id, ctx.sender, query, room_k=4, user_k=3)
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
        """
        out: Dict[str, Any] = {
            "persona": "", "skill_slugs": [], "model": "", "task_rule": "",
            "worker_slugs": [], "workflow_slugs": [], "kb_scopes": [],
        }
        try:
            cfg = self.client.get_state_event(room_id, CHANNEL_CONFIG_EVENT_TYPE) or {}
            # 本专班任务 RULE（档3）：项目主AI 的缰绳，最高优先级注入（见 _skill_addendum）。
            # 先于 persona 取出，确保两条返回路径都带上它。
            out["task_rule"] = str(cfg.get("taskRule") or "").strip()
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

    def _apply_worker_routing(
        self, text: str, gctx: Dict[str, Any], sender: str = ""
    ) -> Dict[str, Any]:
        """档3b：专班里若消息点名了某个绑定的协作 Agent（按 slug 或显示名），就改用该 worker
        的人设/技能/模型回这条；**任务 RULE 不变**（worker 仍在专班、受同一约束）。

        没点名、或非专班（worker_slugs 为空）→ 原样返回 lead（项目主AI）的 gctx。
        方案A（单 bot 多人设）：worker 不是独立 Matrix 账号，靠在正文里匹配名/slug 路由。
        匹配多个时取第一个；全程兜异常，绝不阻断回复。
        """
        slugs = gctx.get("worker_slugs") or []
        body = (text or "").strip()
        if not body:
            return gctx
        low = body.lower()
        try:
            for slug in slugs:
                agent = self._find_global_agent(str(slug))
                if not agent:
                    continue
                name = str(agent.get("name") or "").strip()
                hit = (str(slug).lower() in low) or (bool(name) and name in body)
                if not hit:
                    continue
                sp = (agent.get("system_prompt") or "").strip()
                out = dict(gctx)
                out["persona"] = (
                    f"本条由你以协作智能体「{name or slug}」的身份回应，"
                    f"请按下述人设履职：\n{sp}"
                )
                out["skill_slugs"] = [str(s) for s in (agent.get("skill_slugs") or [])]
                out["model"] = (agent.get("model") or "").strip()
                return out
        except Exception as e:
            logger.debug("协作 Agent 路由失败（忽略，用 lead 回应）：%s", e)
        # 专班 worker 未命中 → 试**发起人自建**智能体(用户自己的"私人 AI 同事",点名即应答)。
        try:
            for m in self._my_agent_items(sender):
                name = str(m.get("name") or "").strip()
                if (m["slug"] in low) or (bool(name) and name in body):
                    out = dict(gctx)
                    out["persona"] = (
                        f"本条由你以用户自建智能体「{name or m['slug']}」的身份回应，"
                        f"请按下述人设履职：\n{(m.get('system_prompt') or '').strip()}"
                    )
                    out["skill_slugs"] = [str(x) for x in (m.get("skill_slugs") or [])]
                    out["model"] = (m.get("model") or "").strip()
                    return out
        except Exception as e:
            logger.debug("个人智能体路由失败（忽略）：%s", e)
        # 自建也未命中 → 试发起人**商城已获取**的全局智能体。只认显式 @点名(@slug/@名字):
        # 名字常是"文案"这类日常词,若按"正文包含"匹配,用户请主 AI"帮我写文案"就会被
        # 错切到 copywriter 人设。access 无需再查——已获取入库时服务端已校验解锁。
        try:
            for slug in self._acquired_agent_slugs(sender):
                agent = self._find_global_agent(slug)
                if not agent:
                    continue
                name = str(agent.get("name") or "").strip()
                if (f"@{slug.lower()}" not in low) and not (name and f"@{name}" in body):
                    continue
                out = dict(gctx)
                out["persona"] = (
                    f"本条由你以协作智能体「{name or slug}」的身份回应，"
                    f"请按下述人设履职：\n{(agent.get('system_prompt') or '').strip()}"
                )
                out["skill_slugs"] = [str(s) for s in (agent.get("skill_slugs") or [])]
                out["model"] = (agent.get("model") or "").strip()
                return out
        except Exception as e:
            logger.debug("已获取智能体路由失败（忽略）：%s", e)
        return gctx

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
            llm = build_provider(
                provider, api_key="", model=model, system_prompt=applied_sys
            )
            ag = Agent(llm=llm, toolbox=self.toolbox, system_prompt=applied_sys)
            self._model_agents[model] = ag
            logger.info("按群模型构建 Agent: provider=%s model=%s", provider, model)
            return ag
        except Exception:
            logger.exception("按群模型 %s 构建失败，回退默认模型", model)
            return self.agent

    def _run_agent_engine(
        self, agent, user_text, tool_ctx, extra_system, history, model_override=""
    ):
        """按 COSMAC_AGENT_ENGINE 选执行引擎跑一条消息。

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
                    progress_cb=reporter,
                )
                reporter.finish()
                return reply
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
                    return (
                        "⚠️ 我在执行过程中已经做了部分操作，但随后遇到故障。为避免重复建群/"
                        "重复派单，这条先停在这里。请看下已完成的部分，需要我接着把剩下的做完就说一声。"
                    )
        try:
            reply = agent.run(
                user_text, tool_ctx, extra_system=extra_system, history=history,
                progress_cb=reporter,
            )
        finally:
            # legacy 引擎抛异常时也要定格"正在执行"卡片，否则它永久卡在"⏳ 正在执行"（#7 连带）。
            # finish() 自带 event_id/steps 守卫并自兜异常，任何时候调用都安全。
            reporter.finish()
        return reply

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
        return [s for s in merged.values() if s.get("enabled", True)]

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
        out = [a for a in merged.values() if a.get("enabled", True)]
        if for_user:
            out = [a for a in out if self._resource_visible(a, for_user)]
        return out

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
                    # 只取我们认识的字段，避免脏数据。
                    # 安全：**绝不**从控制室事件读 api_key——state event 无法加密、会明文
                    # 进 DB/历史/被全员可读。密钥只走服务端环境变量/Secret Manager。
                    for k in (
                        "provider", "model", "system_prompt", "enabled_tools"
                    ):
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

        管理后台可下发 provider / model / 人设 / 工具开关。任一缺省时用启动配置兜底。
        **api_key 永远不从网页/控制室来**：密钥只走服务端环境变量/Secret Manager
        （build_provider 传 api_key="" 即让各 SDK 自己读环境变量）。
        """
        ov = self._read_overrides()
        provider = ov.get("provider") or self.config.llm_provider
        model = ov.get("model") or self.config.llm_model
        system_prompt = ov.get("system_prompt") or self.config.system_prompt
        sig = (provider, model, system_prompt, "")
        if sig != self._applied_sig:
            try:
                # api_key="" → 各 provider SDK 从环境变量读密钥（绝不接受网页传入的 key）
                self.llm = build_provider(
                    provider, api_key="", model=model, system_prompt=system_prompt
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
        """从完整用户 id（@guduu:cosmac.cc）取出 localpart（guduu）。"""
        return self.config.bot_user_id.split(":", 1)[0].lstrip("@")

    def _mention_tokens(self) -> List[str]:
        """所有"算作在叫主 AI"的开头词（大小写不敏感比较）。

        这样用户不用跟 Element 的 @ 弹窗较劲——消息开头直接打 'CosMac' 即可。
        """
        lp = self._bot_localpart()
        return [
            self.config.bot_user_id,        # @guduu:cosmac.cc（@pill）
            f"@{lp}",                        # @guduu
            self.config.bot_displayname,     # CosMac Star
            "CosMac Star",
            "@CosMac",
            "CosMac",                        # 直接打名字开头就算叫它
        ]

    def _agent_mention_hit(self, room_id: str, sender: str, body: str) -> bool:
        """群聊补充触发:这条消息是否**点名**了一个可路由的智能体。

        与 _apply_worker_routing 配对:这里判"要不要应答",那里判"以谁的人设答"。
        可路由集合 = 本频道绑定的专班 worker ∪ 发起人自建 ∪ 发起人商城「已获取」。
        命中规则(防误触发,比路由的"正文包含"严):
          - worker/自建(显式绑定,预期强):消息以 名字/slug 开头,或正文任意处 @名字/@slug;
          - 已获取的全局智能体:只认显式 @点名(名字可能是"文案"这类常用词,
            正文包含或开头匹配都会让 AI 在人聊天时乱入)。
        全程兜异常返回 False——本判定失败只是退回"要 @ 主 AI 才应答"的旧行为。
        """
        body = (body or "").strip()
        if not body:
            return False
        low = body.lower()

        def _hit(slug: str, name: str, at_only: bool) -> bool:
            """单个候选的命中判定。at_only=True 时只认 @点名。"""
            slug = (slug or "").strip().lower()
            name = (name or "").strip()
            if slug and (f"@{slug}" in low or (not at_only and low.startswith(slug))):
                return True
            if name and (f"@{name}" in body or (not at_only and body.startswith(name))):
                return True
            return False

        try:
            # ① 本频道绑定的专班 worker(读一次 room state;非专班频道列表为空、开销即止)
            for slug in (self._group_context(room_id).get("worker_slugs") or []):
                agent = self._find_global_agent(str(slug))
                if _hit(str(slug), str((agent or {}).get("name") or ""), at_only=False):
                    return True
            # ② 发起人自建智能体(工坊承诺"任意频道输入它的名字就由它应答")
            for m in self._my_agent_items(sender):
                if _hit(str(m.get("slug") or ""), str(m.get("name") or ""), at_only=False):
                    return True
            # ③ 发起人商城「已获取」的全局智能体(商城指引"在频道里 @它")——只认 @点名
            for slug in self._acquired_agent_slugs(sender):
                agent = self._find_global_agent(slug)
                if _hit(slug, str((agent or {}).get("name") or ""), at_only=True):
                    return True
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
        for prefix in ("建专班", "/专班", "专班"):
            if text.startswith(prefix):
                # 建群/开专班门控：低于门槛者拦下并提示升级（仍算"命中命令"，return True）
                if not self._gate_allows(sender, "create_room"):
                    self.client.send_text(room_id, self._gate_denied_text("create_room"))
                    return True
                # 「建专班」命令与自然语言 assemble_team 工具是**同一动作**，必须过同一道
                # 付费门控 + teams 配额——否则命令成了付费墙旁路（审查 bug#11）。
                if not self._gate_allows(sender, "assemble_team"):
                    self.client.send_text(room_id, self._gate_denied_text("assemble_team"))
                    return True
                over = self._rate_quota_blocked(sender, "teams", consume=False)
                if over:
                    self.client.send_text(room_id, over)
                    return True
                name = text[len(prefix):].strip(" :：") or "新专班"
                self._launch_campaign(room_id, sender, name)
                return True
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
        """入驻模板给本工作区预置的默认工作流（P2）：渲染成一段引导，让 AI 知道有现成工作流可跑。

        只是「告诉 AI 有这些、可用 run_workflow 调用」，不改变 run_workflow 的权限（它本就能跑
        任意全局工作流）。把 slug 解析成名字更友好；解析不到的 slug 跳过（可能已被后台删）。
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
                "【本工作区预置的工作流】：用户选的入驻模板预置了以下现成工作流，"
                "需要时可用 run_workflow 直接调用：\n" + "\n".join(lines)
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

    def handle_stats(self, access_token: str) -> Tuple[int, Dict[str, Any]]:
        """平台**真实运营指标**（给数据看板用，替掉演示假数据）。**仅平台管理员**可读。

        只统计 CosMac 真正拥有的数据：会员（控制室）+ 工作流运行/订单/知识库（cosmac DB）。
        影视业务数据（播放量/集数等）CosMac 不拥有，不在此处编造。每项独立兜底，缺 DB 不报错。

        权限：这些是**全平台**聚合（总付费会员数/总订单数等），属运营敏感数据，普通登录用户
        不该看到。故限平台管理员；非管理员回 403，前端据此回退占位（不报错）。
        """
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        if not self._is_platform_admin(user_id):
            return 403, {"error": "仅平台管理员可查看平台运营指标"}
        out: Dict[str, Any] = {
            "members_paid": 0, "members_creator": 0,
            "workflow_runs": 0, "orders_paid": 0, "kb_docs": 0,
        }
        try:
            mp = self.members.get_all()
            out["members_paid"] = sum(1 for r in mp.values() if r.get("tier") == "paid")
            out["members_creator"] = sum(
                1 for r in mp.values() if r.get("tier") == "creator"
            )
        except Exception:
            logger.debug("统计会员失败", exc_info=True)
        try:
            from sqlalchemy import func, select

            from cosmac.db import session_scope
            from cosmac.db.models import KnowledgeDoc, Order, WorkflowRun

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
        except Exception:
            logger.debug("统计 DB 指标失败", exc_info=True)
        return 200, out

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
        """user_id 是否是这条任务的**被指派者**（executor_ref 指向本人）。

        与 handle_tasks_list 的可见性口径**完全一致**：比对 localpart，兼容 executor_ref 存
        全 id / 纯 localpart / 带不带 @；旧任务无 executor_ref 时按 assignee 首词兜底。
        —— 这是「看得到 = 改得动」的关键：可见性放行了被指派者，改状态的鉴权也必须同样放行，
        否则被派单的人在看板点「开始」会 403（线上实测）。
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
        if not ref:  # 旧任务无类型化执行者：按 assignee 首词兜底
            a = str(getattr(task, "assignee", "") or "").strip()
            first = a.split()[0] if a else ""
            return bool(first) and _lp(first) == localpart
        return False

    def _can_access_task(self, user_id: str, task: Any) -> bool:
        """判断 user_id 是否有权读/改这条任务。

        授权规则（任一成立即可）：① 平台管理员；② 任务由本人下达（task.sender）；
        ③ 任务**派给本人**（executor_ref/assignee 指向本人）——被指派者要能在看板推进自己的卡；
        ④ 本人是任务所属房间(task.room_id)的成员。任何不确定一律拒绝（fail-closed），
        防止任意登录用户靠遍历 id 越权读写别人工作区的任务看板。
        """
        if not user_id:
            return False
        if task.sender and task.sender == user_id:
            return True
        # 被指派者可改自己的任务（与看板可见性同口径，修「看得到却点不动 403」）。
        if self._is_task_assignee(user_id, task):
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
                    # 可见性 = 本人下达 或 派给本人；与 _can_access_task(改状态鉴权)**共用同一口径**
                    # (_is_task_assignee),保证「看得到 == 改得动」,不再各写一份而悄悄跑偏(线上踩过)。
                    visible = [
                        t for t in candidates
                        if (t.sender and t.sender == user_id)
                        or self._is_task_assignee(user_id, t)
                    ]
                for t in visible:
                    out.append({
                        "id": t.id, "title": t.title, "assignee": t.assignee,
                        "status": t.status, "progress": t.progress,
                        "goal": t.goal, "result": t.result,
                        # 类型化执行者（档2）：看板据此显示"派给谁/什么"
                        "executor_kind": t.executor_kind, "executor_ref": t.executor_ref,
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
            return 400, {"error": "任务状态非法（只能是 待办/进行中/已完成）"}
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
                ok = update_task(
                    s, task_id,
                    status=status,
                    progress=body.get("progress"),
                    result=body.get("result"),
                )
        except Exception:
            logger.exception("更新任务失败 id=%s", task_id)
            return 500, {"error": "更新失败"}
        # 任务确实存在（上面已 get 到）：ok=False 只能是「没有可更新字段」→ 400 而非误导性 404。
        return (200, {"ok": True}) if ok else (400, {"error": "没有可更新的内容"})

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

    def handle_register_request_code(
        self, body: Dict[str, Any], client_ip: str = ""
    ) -> Tuple[int, Dict[str, Any]]:
        """自建邮箱注册：给邮箱发验证码（公开端点，无 token——用户还没账号）。限频在 registration 内强制。"""
        from cosmac import registration
        b0 = body or {}
        return registration.request_code(
            str(b0.get("email") or ""), client_ip=client_ip, turnstile=str(b0.get("turnstile") or ""),
        )

    def handle_register_verify(
        self, body: Dict[str, Any], client_ip: str = ""
    ) -> Tuple[int, Dict[str, Any]]:
        """自建邮箱注册：验码 + 用共享密钥建号（公开端点）。成功回 {user_id, access_token...}。"""
        from cosmac import registration
        b = body or {}
        return registration.verify_and_register(
            b.get("email", ""), b.get("code", ""), b.get("username", ""), b.get("password", ""),
            hs_url=self.config.homeserver_url, client_ip=client_ip,
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
        b = body or {}
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
        b = body or {}
        # str() 归一:JSON 里 username 传成数字/对象时,registration 端的 .strip() 会 AttributeError
        # → 连接被掐(无响应)。这里统一成字符串(低⑤)。
        return registration.login_account(
            str(b.get("username") or ""), str(b.get("password") or ""),
            hs_url=self.config.homeserver_url, client_ip=client_ip,
            code=str(b.get("code") or ""),   # 阶段2:异地二次验证的邮箱验证码(第二步才带)
            server_name=self.config.server_name,  # 停用检测要用它拼 @user:server_name
        )

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
                cur = len(kb.list_docs(s, scope=SCOPE_USER, scope_id=user_id))
                if kb_limit >= 0 and cur >= kb_limit:
                    return 400, {"error": f"知识库已满（{cur}/{kb_limit} 篇）。升级会员可扩容。"}
                if cur >= MAX_DOCS_PER_SCOPE:  # 不限额(creator/admin)也别无限堆，留个硬上限兜底
                    return 400, {"error": f"知识库已达系统上限（{MAX_DOCS_PER_SCOPE} 篇），先删一些再加"}
                doc = kb.ingest_document(
                    s, scope=SCOPE_USER, scope_id=user_id,
                    title=title, source="upload", text=content,
                )
                # 在 session 内取出需要的标量值返回（关闭后惰性加载会报错）
                out = {"ok": True, "id": doc.id, "title": doc.title, "chunks": len(doc.chunks)}
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
        from cosmac.db.kb_cmd import MAX_DOC_CHARS, MAX_DOCS_PER_SCOPE

        if len(content) > MAX_DOC_CHARS:
            return 400, {
                "error": f"文件太长（{len(content)} 字），上限 {MAX_DOC_CHARS} 字，请拆分后再传"
            }
        try:
            from cosmac.db import kb, session_scope
            from cosmac.db.models import SCOPE_ROOM

            with session_scope() as s:
                cur = len(kb.list_docs(s, scope=SCOPE_ROOM, scope_id=room_id))
                if cur >= MAX_DOCS_PER_SCOPE:
                    return 400, {
                        "error": f"本频道知识库已达上限（{MAX_DOCS_PER_SCOPE} 篇），先删一些再传"
                    }
                doc = kb.ingest_document(
                    s, scope=SCOPE_ROOM, scope_id=room_id,
                    title=title or "未命名文档", source="upload", text=content,
                )
                return 200, {"ok": True, "id": doc.id, "title": doc.title, "chunks": len(doc.chunks)}
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
                "CosMac Star 隐私政策\n\n最后更新：2026年7月\n\n"
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
                "· 平台内私信管理员，或发邮件至 support@cosmac.cc。"
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
                "· 其它问题：私信管理员或发邮件 support@cosmac.cc。"
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
                    "enabled": a.enabled,
                } for a in list_agents(s, scope=SCOPE_USER, scope_id=user_id)]
            return 200, {"agents": out}
        except Exception:
            logger.exception("列个人智能体失败")
            return 500, {"error": "读取失败"}

    def handle_my_agents_save(
        self, access_token: str, body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """新建/更新本人自建智能体。校验:slug 规范、字段长度、每人 50 个、存储空间。"""
        user_id = self.client.whoami(access_token)
        if not user_id:
            return 401, {"error": "登录已失效，请重新登录"}
        slug = str((body or {}).get("slug") or "").strip().lower()
        if not self._valid_slug(slug):
            return 400, {"error": "标识(slug)需为小写字母/数字/中划线,64 字符内"}
        name = str(body.get("name") or "").strip()[:80]
        description = str(body.get("description") or "").strip()[:300]
        prompt = str(body.get("system_prompt") or "").strip()
        model = str(body.get("model") or "").strip()[:128]
        enabled = body.get("enabled") is not False
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
                    model=model, enabled=enabled,
                )
            self._storage_cache = {}  # 内容变了,存量缓存作废
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
                    "instructions": k.instructions, "enabled": k.enabled,
                } for k in list_skills(s, scope=SCOPE_USER, scope_id=user_id)]
            return 200, {"skills": out}
        except Exception:
            logger.exception("列个人技能失败")
            return 500, {"error": "读取失败"}

    def handle_my_skills_save(
        self, access_token: str, body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """新建/更新本人自建技能。个人技能会注入本人每轮对话——单条与总量都有上限。"""
        user_id = self.client.whoami(access_token)
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
        """本人自建且启用的智能体(名册/@ 路由用)。失败返回空,绝不阻断。"""
        if not owner:
            return []
        try:
            from cosmac.db import session_scope
            from cosmac.db.models import SCOPE_USER
            from cosmac.db.repo import list_agents

            with session_scope() as s:
                return [{
                    "slug": a.slug, "name": a.name, "description": a.description,
                    "system_prompt": a.system_prompt, "model": a.model,
                    "skill_slugs": list(a.skill_slugs or []),
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

    def _market_catalog_items(self, user_id: str, is_admin: bool) -> List[Dict[str, Any]]:
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
        agents = self._global_agent_items()
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

    # 商城资源类型全集(acquire 端点校验用)
    _MARKET_KINDS = ("agent", "skill", "workflow", "knowledge")

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
            is_admin = self._is_platform_admin(user_id)
            match = next(
                (i for i in self._market_catalog_items(user_id, is_admin)
                 if i["kind"] == kind and i["slug"] == slug),
                None,
            )
            if match is None:
                return 404, {"error": "商城里没有这个资源(可能已下架)"}
            if not match.get("unlocked"):
                return 403, {"error": "该资源需要升级会员后才能获取"}
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
            return 400, {"error": "请填写完整的用户 ID（如 @bob:cosmac.cc）"}
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
            from cosmac.db import kb, session_scope
            from cosmac.db.models import SCOPE_USER
            from cosmac.db.quota_repo import get_count, period_key

            with session_scope() as s:
                for q in QUOTA_CATALOG:
                    metric = q["key"]
                    limit = self._quota_limit(user_id, metric)
                    if q.get("track") == "existing" and metric == "kb_docs":
                        used = len(kb.list_docs(s, scope=SCOPE_USER, scope_id=user_id))
                    elif q.get("track") == "existing" and metric == "storage_mb":
                        used = round(self._storage_bytes(user_id) / 1048576, 1)
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
            is_dm = self.client.joined_member_count(room_id) <= 2
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
            is_dm = self.client.joined_member_count(room_id) <= 2
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
        """把截止 epoch 秒格式化成 'MM-DD HH:MM'（服务器本地时区），给提醒文案用。"""
        if not ts:
            return "截止时间"
        try:
            return time.strftime("%m-%d %H:%M", time.localtime(int(ts)))
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

    def start_reminder_scanner(self) -> None:
        """启动后台守护线程，周期性扫描任务时效并发提醒。

        单实例内定时即可（见 memory wf-reliability-scope：durable 队列/多实例是已知边界、本期不做）。
        """
        interval = self._reminder_interval_secs

        def _loop() -> None:
            time.sleep(min(60, interval))  # 启动后先等一会儿，让服务/sync 就绪
            while True:
                self.scan_task_reminders()
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
        """
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
        "assemble_team": "assemble_team",  # 一键建专班：独立门控（默认免费，可在后台调成付费）
        "create_tasks": "task_board",      # AI 拆解任务到看板：独立门控（默认免费）
        "query_hr": "hr_data",             # 人事数据查询：敏感数据，默认仅管理员（见 GATE_CATALOG）
        "query_sales": "sales_data",       # 销售业绩查询：经营敏感数据，默认仅管理员
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
            from cosmac.db.quota_repo import get_count, incr, period_key

            pkey = period_key(period)
            with session_scope() as s:
                used = get_count(s, user_id, metric, pkey)
                if used >= limit:
                    span = "今天" if period == "day" else ("本月" if period == "month" else "")
                    return (
                        f"你{span}的「{label}」额度已用完（{used}/{limit}）。"
                        "升级会员可解锁更多 —— 私聊发「会员」查看，或在「升级会员」里订阅。"
                    )
                if consume:
                    incr(s, user_id, metric, pkey)
        except Exception:
            logger.debug("配额计数失败（放行）：metric=%s", metric, exc_info=True)
        return None

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
        "assemble_team": "teams",       # 专班数（单调累计）
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
        检查与消费之间有并发窗口（可能偶发超放 1 次）——与配额计数既有的"够用即止"口径一致。
        """
        metric = self._TOOL_QUOTA_MAP.get(tool_name)
        if not metric:
            return
        try:
            from cosmac.quotas import metric_meta

            from cosmac.db import session_scope
            from cosmac.db.quota_repo import incr, period_key

            limit = self._quota_limit(sender, metric)
            if limit < 0:
                return  # 管理员/不限额：check 时没拦，也无需计数
            meta = metric_meta(metric) or {}
            pkey = period_key(str(meta.get("period") or "day"))
            with session_scope() as s:
                incr(s, sender, metric, pkey)
        except Exception:
            logger.debug("配额消费失败（忽略）：metric=%s", metric, exc_info=True)

    def _launch_campaign(self, origin_room: str, requester: str, name: str) -> None:
        """建一个专班群、拉发起人进来，并在群里发一张"派单"富卡。

        L12：与 assemble_team 工具对齐关键行为——① 建房时把发起人提成管理员(power=100)，否则
        他改不了频道名/配置(403)；② 建成后给发起人所在房发 team_created 信号卡，客户端据此把
        新专班自动挂进当前工作区（否则 FEATURES 宣称的"自动挂工作区"对本命令入口不成立）。
        （派单富卡仍是演示卡：本命令是"一句话出富卡"的演示路径，真实任务编排走自然语言→工具。）
        """
        new_room = self.client.create_room(name, invitees=[requester], admins=[requester])
        if not new_room:
            self.client.send_text(origin_room, f"抱歉，建专班「{name}」失败了，请稍后再试。")
            return
        # 专班房真建成才消费 teams 配额（与 assemble_team 工具同一本账，失败不扣）
        self._tool_quota_consume(requester, "assemble_team")

        # 派单富卡：body 是纯文本兜底（Element 显示这个），card 是结构化数据（CosMac 客户端渲染）
        card = {
            "kind": "dispatch",
            "title": f"{name} · 专班已建立",
            "subtitle": "由 CosMac Star 中枢自动派单",
            "rows": [
                {"task": "选题锁定", "owner": "选题 Agent", "type": "ai"},
                {"task": "脚本撰写", "owner": "文案 Agent", "type": "ai"},
                {"task": "数据排期", "owner": "数据 Agent", "type": "ai"},
                {"task": "拍板确认", "owner": requester, "type": "human"},
            ],
        }
        body = (
            f"【{name}】专班已建立，派单如下：\n"
            "· 选题锁定 → 选题 Agent\n"
            "· 脚本撰写 → 文案 Agent\n"
            "· 数据排期 → 数据 Agent\n"
            f"· 拍板确认 → {requester}"
        )
        self.client.send_card(new_room, body, card)
        # 让客户端把这个专班自动挂进发起人当前工作区（与 assemble_team 工具一致，L12）
        try:
            self.client.send_card(
                origin_room,
                f"专班「{name}」已建好（room_id={new_room}）。",
                {"kind": "team_created", "team_room": new_room, "project": name},
            )
        except Exception:
            logger.debug("发送 team_created 信号卡失败（忽略）", exc_info=True)
        self.client.send_text(
            origin_room, f"已为你建立专班「{name}」并把你拉进群，派单已发到新群里。"
        )


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
        if cors:
            # 跨源：前端在 app.cosmac.cc，bot 在 hs.cosmac.cc，浏览器要 CORS 头才放行。
            # 默认 *（这些端点要么公开、要么自带 token 校验）；可用 COSMAC_APP_ORIGIN 收紧到具体域名。
            origin = os.environ.get("COSMAC_APP_ORIGIN", "") or "*"
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self) -> None:  # noqa: N802
        # 给浏览器调的端点回 CORS 预检（带 Authorization 头的请求会先发 OPTIONS）
        p = self.path.split("?", 1)[0]
        if (p.startswith("/cosmac/pay/") or p == "/cosmac/stats"
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
                or p.startswith("/cosmac/admin/")      # 后台用户列表拉邮箱（GET 带 Authorization 也要预检）
                or p.startswith("/cosmac/channel/")     # 平台管理员接管频道（bug14）
                or p.startswith("/cosmac/auth/")):     # 认证前端配置（Turnstile 开关）；都走浏览器，需预检
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

        # 组织/人事页：员工花名册（仅平台管理员；带本人 token）
        if self.path.split("?", 1)[0] == "/cosmac/hr/employees":
            auth = self.headers.get("Authorization", "")
            token = auth[len("Bearer "):] if auth.startswith("Bearer ") else ""
            code, payload = self.bot.handle_hr_employees(token)
            self._send_json(code, payload, cors=True)
            return

        # 管理后台：用户名→邮箱 映射（仅平台管理员;用户列表显示邮箱用）
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
        if self.path.split("?", 1)[0] == "/cosmac/kb/room/list":
            from urllib.parse import parse_qs, urlparse
            token = self._bearer()
            qs = parse_qs(urlparse(self.path).query)
            room_id = (qs.get("room_id") or [""])[0]
            code, payload = self.bot.handle_kb_room_list(token, room_id)
            self._send_json(code, payload, cors=True)
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
                    "/cosmac/my/skills/save", "/cosmac/my/skills/delete"):
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

    # 把 bot 和 hs_token 注入到 Handler 类上（http.server 用类、不便传参，用 partial 构造）
    handler_cls = partial(_make_handler, bot=bot, hs_token=config.hs_token)

    server = _BoundedThreadingHTTPServer(
        (config.listen_host, config.listen_port), handler_cls
    )
    logger.info(
        "CosMac Star 主 AI Bot 已启动: 监听 http://%s:%d ，连接 Synapse %s ，模型后端=%s",
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
