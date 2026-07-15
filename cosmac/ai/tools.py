"""主 AI 的工具箱：把"工具"映射到真实的 IM 操作。

这是"让 AI 真正动手"的关键一层：
  - 每个工具 = 一份给模型看的 ``ToolSpec``（说明书）+ 一个真正执行的 Python 函数。
  - 执行函数把调用转发到 ``MatrixClient``（主 AI 的"手"），从而真的建群/发消息/查记录。

设计原则：
  - 工具定义（ToolSpec）是厂商中立的，由各 provider 翻译成自家格式。
  - 工具的"执行"统一返回一段**给模型读的文本结果**（成功与否、关键信息），
    Agent 会把它回灌给模型，让模型据此决定下一步或给用户最终答复。
  - 涉及"当前所在房间 / 发起人是谁"的上下文，通过 ``ToolContext`` 传入，
    不让模型去猜这些它不该知道的内部 id。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from cosmac.ai.base import ToolCall, ToolSpec
from cosmac.bots.matrix_client import MatrixClient
from cosmac.config import CHANNEL_CONFIG_EVENT_TYPE, WORKFLOWS_EVENT_TYPE

logger = logging.getLogger("cosmac.ai.tools")


# 任务状态白名单 + 模型/用户可能给的同义词归一化（M6：非法 status 曾被 task_repo 静默丢弃 →
# 工具却回"已更新→<非法值>"的假成功，审核打回等流程静默失效）。
_TASK_STATUSES = ("todo", "doing", "done")
_STATUS_ALIASES = {
    "todo": "todo", "待办": "todo", "todo列": "todo", "backlog": "todo", "pending": "todo",
    "doing": "doing", "进行中": "doing", "in_progress": "doing", "inprogress": "doing",
    "in-progress": "doing", "wip": "doing", "处理中": "doing",
    "done": "done", "已完成": "done", "完成": "done", "completed": "done",
    "complete": "done", "finished": "done", "closed": "done",
}


def _resolve_resource_slugs(
    wanted: List[str], known: Any
) -> Tuple[List[str], List[str]]:
    """把模型给的资源标识解析成库里的**真 slug**(assemble_team 绑 Agent/Skill 用)。

    背景(负责人线上实测):库里是 ``marketing-campaign``,模型凭记忆写成
    ``marketing_campaign``,精确匹配判"库里没有"→技能被剔、绑定失败。LLM 生成的
    标识常有 下划线/中划线、大小写 这类无害变体,匹配必须宽容:
      - 规范化比较:两边都 strip+小写+``_``→``-`` 后再比;
      - 名称兜底:known 若是 dict[slug→名称],还可按中文名(如「营销活动策划」)匹配。

    参数 known: set[slug] 或 dict[slug→名称]。
    返回 (resolved, bad):resolved=解析成功的真 slug(保序去重);bad=真没有的原词。
    """
    names: Dict[str, str] = (
        dict(known) if isinstance(known, dict) else {str(k): "" for k in (known or set())}
    )

    def norm(x: Any) -> str:
        return str(x or "").strip().lower().replace("_", "-")

    idx: Dict[str, str] = {}
    for slug, name in names.items():
        idx.setdefault(norm(slug), slug)
        if norm(name):
            idx.setdefault(norm(name), slug)
    resolved: List[str] = []
    bad: List[str] = []
    seen: Set[str] = set()
    for w in wanted:
        hit = idx.get(norm(w))
        if hit is None:
            bad.append(w)
        elif hit not in seen:
            seen.add(hit)
            resolved.append(hit)
    return resolved, bad


def _normalize_task_status(raw: Any) -> Any:
    """把模型/用户给的状态词归一化到合法值；空→None(不改)；非法→原样返回(调用方据此报错)。"""
    s = str(raw or "").strip().lower()
    if not s:
        return None
    return _STATUS_ALIASES.get(s, s)


def _parse_due_to_ts(due: Any) -> Optional[int]:
    """把主 AI 填的截止时间字符串解析成 epoch 秒（=无时限则 None）。

    L10：曾经建任务(本函数)用「当天 18:00」、改期用「当天 23:59」两套口径——同一个日期两条路径
    解析出的时刻差近 6 小时（用户没改日期、截止时刻却漂移，还影响到期提醒扫描）。现统一委托到
    :func:`_parse_due_to_epoch`（date-only → 当天 23:59，且格式支持更全），只此一套口径。
    """
    return _parse_due_to_epoch(str(due or ""))


@dataclass
class ToolContext:
    """一次工具调用的上下文（模型不该感知的内部信息从这里注入）。

    room_id: 当前对话所在房间（"发到这个群""查本群记录"等默认指向它）。
    sender:  发起人用户 id（建群时默认把他拉进去）。
    source_key: 可选的来源幂等键（通常来自 Matrix event_id），给外部工作流防重放。
    """

    room_id: str
    sender: str
    source_key: str = ""
    # 当前对话是否「私聊/AI 会话房」(用户与主AI的一对一会话)。工具用它防语义事故:
    # 用户在私聊里说"邀请xx进本群","本群"其实是私聊房——把人拉进用户的私人对话是灾难。
    is_dm: bool = False
    # 发起人当前所在的工作区(Space room_id)——前端随消息带上的 `cosmac.doc_space`。
    # 拆任务时盖在任务上，任务看板据此按工作区过滤(私聊房的 room_id 归不了工作区)。
    space_id: str = ""


def _parse_due_to_epoch(raw: str) -> Optional[int]:
    """把日期字符串解析成 epoch 秒（任务截止时间）。解析不了返回 None。

    支持：'YYYY-MM-DD'（只给日期 → 默认当天 23:59）/ 'YYYY-MM-DD HH:MM' / 'YYYY-MM-DD HH:MM:SS'，
    '/' 与 'T' 分隔也认。按**产品时区**(tzutil,默认北京时间)换算——模型给的时刻语义上是
    用户时区;此前按服务器本地时区,UTC 服务器上会偏 8 小时(负责人实测:AI 报时差 8 小时)。
    """
    from cosmac.tzutil import parse_local_to_epoch

    s = (raw or "").strip().replace("/", "-").replace("T", " ")
    for fmt, date_only in (
        ("%Y-%m-%d %H:%M:%S", False),
        ("%Y-%m-%d %H:%M", False),
        ("%Y-%m-%d", True),
    ):
        if date_only:
            ts = parse_local_to_epoch(s + " 23:59", "%Y-%m-%d %H:%M")
        else:
            ts = parse_local_to_epoch(s, fmt)
        if ts is not None:
            return ts
    return None


class Toolbox:
    """主 AI 可用工具的注册表 + 执行器。

    第一版工具（够验证"AI 真能动手"且实用）：
      - create_room          建一个新群，并把发起人拉进去
      - send_message_to_room  往指定房间发一条消息
      - list_room_members     看某房间都有谁（默认当前房间）
      - get_recent_messages   读某房间最近的聊天记录（默认当前房间）
    """

    def __init__(self, client: MatrixClient, control_room_alias: str = ""):
        self.client = client
        # 控制室别名：run_workflow 工具据此读「工作流连接器」定义（state event）。
        self._control_room_alias = control_room_alias
        # 异步连接器(async=true)的提交回调：由 bot 注入 self._dispatch_async；
        # 签名 (conn, user_input, room_id, sender, name) -> 提交结果文本。None 则回退后台同步跑。
        self.dispatch_async: Optional[Callable[..., str]] = None
        # 功能门控钩子：由 bot 注入。签名 (sender, tool_name) -> 拒绝文案 或 None(放行)。
        # 在 execute() 里、真正跑工具前调用——让"让 AI 帮我建群/跑工作流"也受会员门控约束
        # （与聊天命令同一道闸，防止绕过命令直接走自然语言）。None = 不做门控（如单测）。
        self.gate_check: Optional[Callable[[str, str], Optional[str]]] = None
        # 用量配额钩子：由 bot 注入。签名 (sender, tool_name) -> 超额提示文案 或 None(放行)。
        # 在 execute() 门控之后调用。⚠️ 只做**检查**不计数——计数由工具在**成功路径**上调
        # quota_consume（否则"先扣后执行"会把失败/纯列表查询也扣掉；teams 是终身配额，免费
        # 用户被一次 Synapse 抖动扣光就永久锁死，审查 bug#7）。
        self.quota_check: Optional[Callable[[str, str], Optional[str]]] = None
        # 用量配额**消费**钩子：由 bot 注入。签名 (sender, tool_name) -> None。工具在真正
        # 做成事的那一刻调用（如专班房建成、工作流真正提交），失败路径不扣。
        self.quota_consume: Optional[Callable[[str, str], None]] = None
        # 资源存在性校验回调(bot 注入):返回库里现有的 Agent/Skill——
        # 集合 set[slug] 或映射 dict[slug→名称] 都接受(映射可支持按中文名匹配)。
        # assemble_team 用它识别"库里没有的资源"并**提醒用户缺口**,而不是静默写进配置后失效
        # (负责人设计:组班资源必须来自库;没有的要提醒,可能需要先到后台添加)。None=跳过校验。
        # 可选 for_user 参数:传发起人 id → 只返回其 access 够得到的资源(M2 越权过滤);
        # 不传 → 全量(无发起人上下文的场景)。
        self.known_agents: Optional[Callable[..., Any]] = None
        self.known_skills: Optional[Callable[..., Any]] = None
        # AI 任务自动执行器(bot 注入):专班派单后,executor_kind='agent' 的任务交给对应
        # AI 同事**自动执行**(后台线程:人设+任务生成产出→发进专班→回填看板)。
        # 签名 (room_id, sender, task_ids, task_rule) -> None。None=不自动执行(仅落看板)。
        # 负责人需求:任务分配给 Agent 后要真的被执行,而不是躺在看板上等人 @。
        self.auto_execute_agent_tasks: Optional[Callable[..., None]] = None
        # 方案B(bot 注入):把协作 Agent 的**傀儡账号**拉进专班频道(注册→邀请→join)。
        # 签名 (room_id, slug) -> 傀儡MXID(失败空串)。None/失败=退回方案A(人设应答),不阻断。
        self.ensure_worker_in_room: Optional[Callable[[str, str], str]] = None
        # 「群名→room_id」解析用的房名缓存(room_id → (名字, 时间戳);5 分钟 TTL,见 _resolve_room_by_name)
        self._room_name_cache: Dict[str, tuple] = {}
        # 房间类型缓存(room_id → 'ai'/'dm'/'channel';建房标记不变,永久缓存,见 _room_kind)
        self._room_kind_cache: Dict[str, str] = {}
        # 知识库检索回调：由 bot 注入 self._kb_search_for_tool。签名 (query, ctx) -> 结果文本。
        # 让 search_knowledge 工具的检索逻辑(embedder/DB/作用域)留在 bot 一侧，Toolbox 保持薄。
        # None（如单测/未注入）→ search_knowledge 工具返回"暂不可用"，绝不报错。
        self.kb_search: Optional[Callable[["str", ToolContext], str]] = None
        # 能力名册回调（模块3.5 档1）：由 bot 注入 _list_capabilities_for_tool。签名 (ctx)->文本。
        # 让 list_capabilities 工具能列出"可调配的 人/Agent/Skill/知识库"，供主AI 拆任务匹配。
        self.list_capabilities: Optional[Callable[[ToolContext], str]] = None
        # 是否平台管理员回调（bot 注入 _is_platform_admin）。签名 (user_id)->bool。
        # 用于 list_my_rooms 的可见范围：普通用户只看自己在的频道(隐私边界)；管理员/负责人看
        # 全部 bot 频道(跨工作区统筹——否则他查不到自己没加入、但组织里存在的频道)。None=当作非管理员。
        self.is_admin: Optional[Callable[[str], bool]] = None
        # 工具名 → (说明书, 执行函数)。执行函数签名: (arguments, ctx) -> 结果文本
        self._tools: Dict[str, Dict[str, Any]] = {}
        # 启用集合：None = 全部启用（默认）；否则只启用集合内的工具。
        # 管理后台「AI 配置」可下发工具开关，运行时由 bot 调 set_enabled 更新。
        self._enabled: Optional[Set[str]] = None
        self._register_default_tools()

    # —— 工具开关 ——

    def set_enabled(self, names: Optional[Set[str]]) -> None:
        """设置启用的工具集合。传 None = 全部启用（不限制）。

        只对"已注册的工具名"生效；未知名字忽略。这样管理后台即使下发了已废弃的
        工具名也不会出错。
        """
        if names is None:
            self._enabled = None
        else:
            # 只保留确实存在的工具名
            self._enabled = {n for n in names if n in self._tools}

    # 核心能力，**永远启用**、不受后台「工具开关」约束。
    # 为什么：后台 AI 配置存的是"勾选的工具名列表"，新加的工具(如 create_tasks)不在旧配置里，
    # 会被当成"未勾选=禁用"。这类核心、低风险工具放这里，避免旧配置一存就把它们关掉。
    # search_knowledge 只读、按 knowledge 门控、且是"智能问答"的核心，也放这里默认常开
    # （旧 AI 配置的工具白名单里没有它，不放这会被当未勾选=禁用）。
    # web_search 也默认常开——它本身受 web_search 门控(默认仅管理员)+ 无 key 自动降级，
    # 双保险，不靠工具开关来拦；放这里免得旧 AI 配置白名单没有它而被当禁用。
    _ALWAYS_ON: Set[str] = {
        "create_tasks", "search_knowledge", "web_search", "list_capabilities",
        "assemble_team", "list_room_tasks", "update_task", "ask_user_choice",
        "archive_project",
        # 邀请进已有群:低风险(有 _check_room_access 防越权)且是修 bug 的关键工具——不在
        # 旧配置白名单里,不放这会被当"未勾选"禁用,模型又会退回误用 create_room 建同名群。
        "invite_to_room",
        # 全局助理的"眼睛"(双层作用域第二步):只读、频道模式自动拒绝,同理常开防旧配置禁用。
        "list_my_rooms",
        # 人事数据查询（数据智能）:只读、按 hr_data 门控(默认仅管理员),旧配置白名单没有它,
        # 不放这会被当"未勾选=禁用"；门控足够拦权限，工具开关不再叠一层。
        "query_hr",
        # 销售业绩查询（数据智能）:只读、按 sales_data 门控(默认仅管理员),同理常开。
        "query_sales",
    }

    def _is_enabled(self, name: str) -> bool:
        if name in self._ALWAYS_ON:
            return True
        return self._enabled is None or name in self._enabled

    # —— 对外接口 ——

    def specs(self) -> List[ToolSpec]:
        """返回当前启用工具的说明书（交给模型，让它知道有哪些工具可用）。"""
        return [
            entry["spec"]
            for name, entry in self._tools.items()
            if self._is_enabled(name)
        ]

    def execute(self, call: ToolCall, ctx: ToolContext) -> str:
        """执行一次工具调用，返回给模型读的文本结果（绝不抛异常，出错也转成文本）。"""
        entry = self._tools.get(call.name)
        if entry is None:
            return f"错误：不存在名为 {call.name} 的工具。"
        if not self._is_enabled(call.name):
            return f"工具 {call.name} 已被管理员停用。"
        # 会员门控：跑工具前先过 bot 注入的门控钩子（同聊天命令那道闸，防自然语言绕过）。
        # 返回拒绝文案就把它当作工具结果回灌给模型，让模型据此礼貌告知用户需升级。
        if self.gate_check is not None:
            denial = self.gate_check(ctx.sender, call.name)
            if denial:
                return denial
        # 用量配额：门控之后再过配额钩子（如建专班数/工作流次数）。超额返回升级提示。
        if self.quota_check is not None:
            over = self.quota_check(ctx.sender, call.name)
            if over:
                return over
        try:
            logger.info("执行工具 %s 参数=%s", call.name, call.arguments)
            return entry["fn"](call.arguments, ctx)
        except Exception:  # 工具出错也要回文本，别让 Agent 循环崩掉
            # 详情只进服务端日志；回给模型(进而可能回进群)的文案泛化——异常文本可能含内部
            # 路径/SQL 片段/room_id 等，原样回灌是信息泄露。
            logger.exception("工具 %s 执行异常", call.name)
            return f"工具 {call.name} 执行出错了，请稍后重试。"

    # —— 工具注册 ——

    def _register(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        fn: Callable[[Dict[str, Any], ToolContext], str],
    ) -> None:
        self._tools[name] = {
            "spec": ToolSpec(name=name, description=description, parameters=parameters),
            "fn": fn,
        }

    def _register_default_tools(self) -> None:
        # 1) 建群（核心：从"会聊天"到"会动手"的分水岭）
        self._register(
            name="create_room",
            description=(
                "创建一个**新的**群聊/房间，并自动把当前请求人拉进去。"
                "当用户想要『建群/开个专班/新建一个频道』时调用。"
                "⚠️ 只用于**从零新建**：想把人拉进**已有**的群（含当前群）必须用 invite_to_room，"
                "绝不要为了邀请人而再建一个同名新群。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "新群的名字，如『爆款专班』。",
                    },
                    "invitees": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "可选。除请求人外还要邀请的用户 id 列表"
                            "（完整格式如 @bob:host）。没有就留空。"
                        ),
                    },
                },
                "required": ["name"],
            },
            fn=self._tool_create_room,
        )

        # 1b) 邀请进已有群（修「AI 邀人却重复建同名群」：以前没有这个工具，模型想邀请人
        #     只能误用 create_room(带 invitees)，结果生成一个同名新群）。
        self._register(
            name="invite_to_room",
            description=(
                "把某个用户邀请进一个**已有**的群/频道。当用户说『把 @xx 拉进群 / 邀请 xx 加入』时"
                "用这个。在**群聊**里不指定 room_id 就邀进当前群;在**与用户的私聊**里必须显式给"
                " room_id(用之前 create_room 返回的群 id)——私聊房绝不能拉人进来。"
                "被邀请的人下次打开客户端会自动入群。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "要邀请的完整用户 id，如 @bob:cosmac.cc。",
                    },
                    "room_id": {
                        "type": "string",
                        "description": "目标房间 id；不填则邀进当前房间。",
                    },
                    "room_name": {
                        "type": "string",
                        "description": (
                            "目标群的**名字**(如『暑期研学活动』)。不知道 room_id 时用它,"
                            "我会在我加入的群里按名字找;重名时会把候选列出来。"
                        ),
                    },
                },
                "required": ["user_id"],
            },
            fn=self._tool_invite_to_room,
        )

        # 1c) 列出发起人所在的频道(双层作用域·第二步:全局助理跨频道统筹的"眼睛")。
        self._register(
            name="list_my_rooms",
            description=(
                "列出**发起人**所在的所有频道(名字+room_id)。只在与用户的私人会话(全局助理"
                "模式)可用。跨频道统筹的第一步:先用它拿到频道清单,再用 get_recent_messages"
                "(room_id=...) 调取某个频道的最近讨论、或用 invite_to_room/send_message_to_room"
                " 操作目标频道。"
            ),
            parameters={"type": "object", "properties": {}},
            fn=self._tool_list_my_rooms,
        )

        # 2) 往某房间发消息
        self._register(
            name="send_message_to_room",
            description=(
                "往指定的**群/频道**发一条文本消息(公告、通知、任务说明等)。"
                "⚠️ 在与用户的私人会话里用它时**必须**指定目标群(room_id 或 room_name)"
                "——不指定会被拒绝,因为发到私聊里其他成员根本看不到。"
                "刚 create_room 建的群,其 room_id 就在建群结果里,直接用它。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "要发送的消息正文。"},
                    "room_id": {
                        "type": "string",
                        "description": "目标房间 id(优先用它,最精确)。",
                    },
                    "room_name": {
                        "type": "string",
                        "description": "目标群名;不知道 room_id 时用群名,我会解析。",
                    },
                },
                "required": ["text"],
            },
            fn=self._tool_send_message,
        )

        # 3) 看某房间成员
        self._register(
            name="list_room_members",
            description="列出某个房间当前的成员；不指定 room_id 则看当前房间。",
            parameters={
                "type": "object",
                "properties": {
                    "room_id": {
                        "type": "string",
                        "description": "房间 id；不填则看当前房间。",
                    }
                },
            },
            fn=self._tool_list_members,
        )

        # 4) 读某房间最近聊天记录
        self._register(
            name="get_recent_messages",
            description=(
                "读取某房间最近的聊天记录，用于了解上下文/做总结。"
                "不指定 room_id 则读当前房间。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "room_id": {
                        "type": "string",
                        "description": "房间 id；不填则读当前房间。",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "读取最近多少条，默认 20。",
                    },
                },
            },
            fn=self._tool_get_messages,
        )

        # 5) 跑外部工作流连接器（n8n/Make 等）
        self._register(
            name="run_workflow",
            description=(
                "运行一个已配置的外部工作流/自动化（对接 n8n、Make 等平台）。"
                "当用户想『跑某个工作流、用 n8n/自动化做某事、触发某流程』时调用。"
                "不确定 slug 就先不带 slug 调用一次，会返回可用工作流列表。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "slug": {
                        "type": "string",
                        "description": "工作流标识(slug)；不确定就留空以获取可用列表。",
                    },
                    "input": {
                        "type": "string",
                        "description": "传给工作流的输入文本/参数（如『科技感蓝色封面』）。",
                    },
                },
            },
            fn=self._tool_run_workflow,
        )

        # 6) 拆解目标 → 登记任务到任务看板（AI 任务编排；档2 起支持类型化执行者）
        self._register(
            name="create_tasks",
            description=(
                "把一个目标拆解成若干可执行的子任务，登记到『任务看板』，并给每条**指派执行者**。"
                "适用于『不开专班、就在当前对话/频道列一串待办』的轻量场景。\n"
                "⚠️ 若这个目标要**拉团队/建专班**，请**直接用 assemble_team**（它会建频道+派单），"
                "**不要**先 create_tasks 再 assemble_team——否则任务会重复登记两份。\n"
                "当用户『下达目标/让你拆解任务/安排分工/拆成几步』时调用。"
                "**强烈建议先调用 list_capabilities** 看清有哪些人/AI Agent/工作流可用，再据其能力指派：\n"
                "每条子任务填 executor_kind + executor_ref：\n"
                "  • human —— 派给真人，ref 填其完整 user_id（如 @anqi:host）\n"
                "  • agent —— 交给 AI Agent，ref 填其 slug（如 copywriter）\n"
                "  • workflow —— 跑某工作流，ref 填其 slug\n"
                "  • none —— 暂不指派（拿不准就用它，别瞎编一个不存在的人/agent）\n"
                "assignee 另填一个给人看的负责人标签（人名/角色）。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "description": "总目标原文（这批子任务的来源）。",
                    },
                    "tasks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {
                                    "type": "string",
                                    "description": "子任务标题（一句话说清要做什么）。",
                                },
                                "assignee": {
                                    "type": "string",
                                    "description": "给人看的负责人标签：人名/角色（如『编剧』）。",
                                },
                                "executor_kind": {
                                    "type": "string",
                                    "enum": ["human", "agent", "workflow", "none"],
                                    "description": "执行者类型；拿不准用 none，别臆造。",
                                },
                                "executor_ref": {
                                    "type": "string",
                                    "description": (
                                        "执行者标识：human→@user_id / agent→slug / "
                                        "workflow→slug；none 留空。须来自 list_capabilities。"
                                    ),
                                },
                                "due": {
                                    "type": "string",
                                    "description": (
                                        "截止时间（可选）：写成 'YYYY-MM-DD' 或 'YYYY-MM-DD HH:MM'。"
                                        "用户说相对时间（如『3天后』『下周五』）时，按 system 里给的"
                                        "『当前时间』换算成绝对日期再填。没有明确期限就别填。"
                                    ),
                                },
                            },
                            "required": ["title"],
                        },
                        "description": "拆出来的子任务列表。",
                    },
                },
                "required": ["goal", "tasks"],
            },
            fn=self._tool_create_tasks,
        )

        # 7) 主动检索知识库（RAG 工具化）：从"每轮盲塞参考资料"升级为"模型自己决定
        #    何时查、用什么词查、可多次查"——这是"像会查会答的助手"的核心手感。
        self._register(
            name="search_knowledge",
            description=(
                "检索『知识库』里与某个问题相关的资料片段（本群知识库 + 你的个人知识库）。"
                "当用户的问题可能涉及已沉淀的文档/资料/规范/历史结论时调用；"
                "可以换更精准的关键词多次检索。检索不到会明确告诉你，不要编造。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "检索用的查询语句/关键词，尽量具体、围绕要找的知识点。",
                    },
                },
                "required": ["query"],
            },
            fn=self._tool_search_knowledge,
        )

        # 8) 联网搜索（让主 AI"会上网查"）：可插拔搜索后端、无 key 自动降级。
        #    共享付费 key、有成本，受 web_search 门控（默认仅管理员，同 run_workflow 思路）。
        self._register(
            name="web_search",
            description=(
                "联网搜索互联网上的实时/外部信息（新闻、资料、事实核查等）。"
                "当问题涉及你知识截止之后的、或需要最新/外部网页信息时调用。"
                "返回若干条标题+链接+摘要；据此作答并可附上来源链接。未配置或搜不到会明确告知。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索查询语句（用自然语言或关键词，尽量具体）。",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回结果条数，默认 5（最多 10）。",
                    },
                },
                "required": ["query"],
            },
            fn=self._tool_web_search,
        )

        # 8.5) 人事数据查询（数据智能）：让主 AI 能回答企业「人事」问题——花名册、编制人数、
        #      薪酬统计、绩效分布/排名、考勤请假、入离职趋势、按人查档。数据来自 cosmac DB
        #      的员工花名册表（cosmac_employee）。按 hr_data 门控（默认仅管理员），只读。
        self._register(
            name="query_hr",
            description=(
                "查询公司**人事 / 员工（HR）数据**并做统计分析。当用户问到与员工、部门、"
                "人数编制、薪资/薪酬、绩效、考勤请假、入职/离职、汇报关系、司龄、花名册相关的问题时调用。"
                "按 action 选择查询类型；拿到结构化结果后，用自然语言给出结论并适当分析/建议。\n"
                "action 取值：\n"
                "- roster：按条件查花名册（配合 department/status/keyword/city/level/perf_rating）\n"
                "- headcount：人数编制统计（配合 group_by=department/status/city/level/title）\n"
                "- salary：薪酬统计（配合 group_by=department/level/city；均值/总额/最高最低）\n"
                "- performance：绩效评级分布 + 待改进名单（配合 department）\n"
                "- ranking：排行榜（配合 field=salary/overtime/leave/tenure、top_n、department）\n"
                "- attendance：等同 ranking 但看考勤（用 field=overtime 或 leave）\n"
                "- trend：近 N 个月入职/离职趋势（配合 months）\n"
                "- find：按姓名/工号查某个人的完整档案（配合 keyword）\n"
                "- summary：公司人事总览快照（不确定问啥时先看它）"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": (
                            "查询类型：roster/headcount/salary/performance/ranking/"
                            "attendance/trend/find/summary"
                        ),
                    },
                    "department": {"type": "string", "description": "部门名（如「研发部」），可选"},
                    "status": {
                        "type": "string",
                        "description": "在职状态过滤：active 在职 / probation 试用期 / resigned 离职，可选",
                    },
                    "keyword": {
                        "type": "string",
                        "description": "姓名/职位/工号关键词（roster 模糊筛选、find 按人查档用）",
                    },
                    "city": {"type": "string", "description": "工作城市，可选"},
                    "level": {"type": "string", "description": "职级（如 P6、M2），可选"},
                    "perf_rating": {"type": "string", "description": "绩效评级 S/A/B/C，可选"},
                    "group_by": {
                        "type": "string",
                        "description": "分组维度：department/status/city/level/title（headcount/salary 用）",
                    },
                    "field": {
                        "type": "string",
                        "description": "排行/考勤指标：salary 月薪 / overtime 加班 / leave 请假 / tenure 司龄",
                    },
                    "top_n": {"type": "integer", "description": "排行榜取前几名，默认 5（最多 20）"},
                    "months": {"type": "integer", "description": "趋势看近几个月，默认 6（最多 24）"},
                },
                "required": ["action"],
            },
            fn=self._tool_query_hr,
        )

        # 8.6) 销售业绩查询（数据智能）：让主 AI 能回答「销售额 / 签单 / 业绩完成率」类问题。
        #      数据来自 cosmac DB 的 cosmac_sales_record（按 销售员 × 月份）。按 sales_data 门控。
        self._register(
            name="query_sales",
            description=(
                "查询公司**销售业绩数据**并做分析。当用户问到销售额、业绩、签单/成单、目标、"
                "业绩完成率/达成率、销售排名、销售趋势、某销售员的业绩时调用。按 action 选类型；"
                "拿到结构化结果后用自然语言给结论与分析。\n"
                "action 取值：\n"
                "- summary：某月销售概况（团队总销售额/目标/签单/完成率 + 每人明细），默认最近月\n"
                "- ranking：销售排行榜（配合 by=actual 销售额 / completion 完成率 / deals 签单数、top_n）\n"
                "- trend：近 N 个月团队销售趋势（配合 months）\n"
                "- person：某销售员近几个月业绩（配合 keyword=姓名/工号）\n"
                "可选 period 指定月份（YYYY-MM），不填=最近有数据的月。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "查询类型：summary/ranking/trend/person",
                    },
                    "period": {"type": "string", "description": "月份 YYYY-MM（可选，默认最近月）"},
                    "by": {
                        "type": "string",
                        "description": "排行维度：actual 销售额 / completion 完成率 / deals 签单数",
                    },
                    "top_n": {"type": "integer", "description": "排行取前几名，默认 5（最多 20）"},
                    "months": {"type": "integer", "description": "趋势/某人看近几个月，默认 6"},
                    "keyword": {"type": "string", "description": "person 用：销售员姓名或工号"},
                },
                "required": ["action"],
            },
            fn=self._tool_query_sales,
        )

        # 9) 能力名册（模块3.5 档1）：列出可调配的 人/AI Agent/Skill/知识库 + 各自能力备注。
        #    主AI **拆任务/分配前**先调它，才能"知道找谁"，而不是凭空编个名字。
        self._register(
            name="list_capabilities",
            description=(
                "列出当前可调配的资源及其能力：真人成员、AI Agent、Skill、知识库（各带能力备注）。"
                "当你要拆解目标、给子任务分配负责人、或组建项目专班前，**先调用它**了解有谁/有什么可用，"
                "据此把每条子任务派给最合适的人或 AI，不要凭空臆造负责人。"
            ),
            parameters={"type": "object", "properties": {}},
            fn=self._tool_list_capabilities,
        )

        # 10) 一键建专班（模块3.5 档3）：把"建频道+拉人+绑AI+装任务RULE/技能+派单"串成一个动作。
        self._register(
            name="assemble_team",
            description=(
                "为一个项目**一键组建专班频道**：建频道 → 拉真人成员 → 绑定 AI（项目主AI + 协作Agent）"
                "→ 设本专班的任务 RULE → 装技能 → 把子任务派进去。"
                "要拉团队干活的目标就**直接用本工具**（先调 list_capabilities 看有谁可用），"
                "**在 tasks 里一并把子任务带上**——它会把任务直接派进新专班。"
                "⚠️ 对同一目标**不要再单独调 create_tasks**（否则任务重复成两份、一份还留在原对话里）。"
                "成员/Agent/技能**必须来自 list_capabilities 名册,绝不要编造名册里没有的**——"
                "库里没有的资源会被剔除并向用户提示缺口。"
                "项目主AI 会被任务 RULE 约束、只围绕本项目分配与审核。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "project": {"type": "string", "description": "专班/项目名（也是频道名）。"},
                    "members": {
                        "type": "array", "items": {"type": "string"},
                        "description": "邀请的真人完整 user_id 列表（来自 list_capabilities）。",
                    },
                    "lead_agent": {
                        "type": "string",
                        "description": "作为项目主AI 的 Agent slug；留空则用内置编排人设。",
                    },
                    "worker_agents": {
                        "type": "array", "items": {"type": "string"},
                        "description": "绑进专班的协作 Agent slug 列表（可空）。",
                    },
                    "task_rule": {
                        "type": "string",
                        "description": (
                            "本专班的任务 RULE/约束：目标、交付标准、审核要求、节奏——它是频道里"
                            "项目主AI 的行为宪法,请**尽量根据任务内容定制**;留空会自动生成基础版。"
                        ),
                    },
                    "skills": {
                        "type": "array", "items": {"type": "string"},
                        "description": "装进专班的 Skill slug 列表（可空）。",
                    },
                    "knowledge": {
                        "type": "array", "items": {"type": "string"},
                        "description": (
                            "从库里**调进这个专班**的知识库来源(让频道全体成员/AI 检索时都用得上)。"
                            "取值:'owner'=把发起人个人知识库对全班开放;"
                            "'platform'=平台共享知识库;"
                            "某**资料库频道的名字或 room_id**=把那个频道的知识挂给专班。可空。"
                        ),
                    },
                    "tasks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "assignee": {"type": "string"},
                                "executor_kind": {
                                    "type": "string",
                                    "enum": ["human", "agent", "workflow", "none"],
                                },
                                "executor_ref": {"type": "string"},
                                "due": {
                                    "type": "string",
                                    "description": "截止时间(可选)：'YYYY-MM-DD' 或 'YYYY-MM-DD HH:MM'；相对时间先据当前时间换算。",
                                },
                            },
                            "required": ["title"],
                        },
                        "description": "派进专班的子任务卡（同 create_tasks 的结构，可空）。",
                    },
                },
                "required": ["project"],
            },
            fn=self._tool_assemble_team,
        )

        # 11) 列出本频道任务（模块3.5 档4）：项目主AI 跟踪进度/审核前先看清有哪些任务。
        self._register(
            name="list_room_tasks",
            description=(
                "列出某频道的任务（含编号 id、状态、执行者、结果/批注）。"
                "跟踪进度、要审核或更新某条任务前，先调它看清有哪些任务、各自到哪一步。\n"
                "room 不传=当前频道;用户点名了别的频道(如在私聊里问「查XX专班的任务进度」)"
                "就把用户说的**频道名原样**传进 room——名字解析我来做(精确匹配优先),"
                "**不要**自己去频道清单里猜相近的名字(「讲座活动」≠「讲座活动专班」是两个频道)。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "room": {
                        "type": "string",
                        "description": "要查的频道名或 room_id(可选;缺省=当前频道)。照抄用户说的完整名字。",
                    },
                },
            },
            fn=self._tool_list_room_tasks,
        )

        # 12) 更新本频道任务（模块3.5 档4）：推进状态 + 回填结果 + 审核（通过/打回）。
        self._register(
            name="update_task",
            description=(
                "更新**当前频道**里某条任务的状态/结果/**截止日期**，用于推进、审核回填与改期：\n"
                "  • 执行者交付 → status=done 且 result 填交付内容/结论/链接\n"
                "  • 审核通过 → status=done\n"
                "  • 审核打回 → status=doing 且 result 写明打回原因与修改要求\n"
                "  • 开始处理 → status=doing\n"
                "  • **改截止日期** → due 填新日期（如『2025-07-11』或『2025-07-11 10:00』）；"
                "清空截止日期填 due=''。用户说『把截止改到X』就直接用本工具改,别再新建任务。\n"
                "只能改本频道的任务（按 task_id，先用 list_room_tasks 拿编号）。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer", "description": "任务编号（见 list_room_tasks）。"},
                    "status": {
                        "type": "string", "enum": ["todo", "doing", "done"],
                        "description": "新状态（可选）。",
                    },
                    "result": {
                        "type": "string",
                        "description": "交付内容 / 审核批注 / 打回原因（可选）。",
                    },
                    "progress": {
                        "type": "integer",
                        "description": "进度 0-100（可选）。",
                    },
                    "due": {
                        "type": "string",
                        "description": (
                            "新截止日期（可选）。格式『YYYY-MM-DD』或『YYYY-MM-DD HH:MM』"
                            "（只给日期默认当天 23:59）。传空串 '' = 清除截止日期（改为无时限）。"
                        ),
                    },
                },
                "required": ["task_id"],
            },
            fn=self._tool_update_task,
        )

        # 13) 让用户点选（而非打字）：需要用户做选择时发一组可点击选项卡。
        self._register(
            name="ask_user_choice",
            description=(
                "需要用户从若干选项里做选择时，用它发一组**可点击的选项**给用户（而不是用一句话让 TA 打字）。"
                "适合：选邀请谁加入专班、选方案/模板、二选一确认、是否继续等。"
                "发出后**结束本轮**，等用户点选、其选择会作为新消息发回来，你再继续。"
                "选项尽量来自真实可选项（如 list_capabilities 里的人/Agent）。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "问用户的话。"},
                    "options": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string", "description": "按钮显示文字。"},
                                "value": {
                                    "type": "string",
                                    "description": "点选后代表用户发回的内容；不填则用 label。",
                                },
                            },
                            "required": ["label"],
                        },
                        "description": "可点选的选项（2-8 个）。",
                    },
                    "multi": {
                        "type": "boolean",
                        "description": "是否允许多选（如『邀请哪些人』）；默认单选。",
                    },
                },
                "required": ["question", "options"],
            },
            fn=self._tool_ask_user_choice,
        )

        # 14) 归档收尾本专班（模块3.5 收尾环节）：所有任务节点完成、审核通过后调它。
        self._register(
            name="archive_project",
            description=(
                "**收尾归档当前专班频道**：当本频道所有任务节点都已完成并审核通过后，"
                "把整盘项目（总目标 + 各任务快照 + 你写的收尾摘要）存成一条归档记录，"
                "并**清掉本频道的 AI 长期记忆**（项目已结，不再占用记忆），最后在群里贴一条收尾通知、提示可关闭频道。\n"
                "调用前务必：① 用 list_room_tasks 确认确实全部 done；② 先用 ask_user_choice 征得用户同意归档关闭，得到确认再调。\n"
                "summary 用一两句话总结这个项目交付了什么、关键结论。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "项目收尾摘要：交付了什么、关键结论（必填，给归档记录用）。",
                    },
                },
                "required": ["summary"],
            },
            fn=self._tool_archive_project,
        )

    # —— 各工具的具体执行（转发到 MatrixClient）——

    def _tool_create_room(self, args: Dict[str, Any], ctx: ToolContext) -> str:
        name = (args.get("name") or "新群").strip()
        # 默认把发起人拉进新群，再并上模型额外指定的邀请人（去重）
        invitees = list(dict.fromkeys([ctx.sender, *(args.get("invitees") or [])]))
        # 发起人 = 频道主人：建房时就提成 100 级管理员，否则他改不了房名/配置(403)。
        room_id = self.client.create_room(name, invitees=invitees, admins=[ctx.sender])
        if not room_id:
            return f"建群「{name}」失败了（创建房间接口返回错误）。"
        # 关键：bot 建房后用户只是被「邀请」、且新房没挂进任何工作区(Space)——前端频道树按
        # 「当前工作区的子房间」过滤，所以不发信号卡的话，用户那边根本看不到这个群（=显示成功却
        # "没建成"的真相）。复用 team_created 信号卡：前端收到会自动 join 新房 + 挂进当前工作区，
        # 频道树立刻出现。bot 自己没权限写 Space 的 m.space.child，故交给客户端补这一步。
        try:
            self.client.send_card(
                ctx.room_id,
                f"群「{name}」已建好（room_id={room_id}）。",
                {"kind": "team_created", "team_room": room_id, "project": name},
            )
        except Exception:
            logger.debug("发送建群信号卡失败（忽略）", exc_info=True)
        return (
            f"已成功创建群「{name}」（room_id={room_id}），"
            f"并已邀请：{', '.join(invitees)}。"
        )

    def _room_kind(self, room_id: str) -> str:
        """房间类型:'space'(工作区)/'ai'(AI会话房)/'dm'(真人私信)/'channel'(普通频道)。

        按建房时打的 state 标记判定,结果永久缓存(标记不会变)——list_my_rooms 每次要过
        全部房间,不缓存会打出成倍的 state 查询。读失败按 channel 处理且不缓存(下次重试)。

        ⚠️ **工作区(Space)本身也是一个房间、也有名字**。不识别出来的话,按名字找"频道"时会命中
        工作区(如「制作·女相师」),AI 就把人邀进了工作区而不是频道——用户看到"邀请成功"、频道里
        却一个人没多(线上实测)。故这里先认 m.room.create.type == m.space。
        """
        cached = self._room_kind_cache.get(room_id)
        if cached is not None:
            return cached
        try:
            create = self.client.get_state_event(room_id, "m.room.create") or {}
            if create.get("type") == "m.space":
                kind = "space"
            elif self.client.get_state_event(room_id, "cosmac.ai_session") is not None:
                kind = "ai"
            elif self.client.get_state_event(room_id, "cosmac.dm") is not None:
                kind = "dm"
            else:
                kind = "channel"
        except Exception:
            return "channel"  # 读失败:按频道处理,不缓存
        self._room_kind_cache[room_id] = kind
        return kind

    def _tool_list_my_rooms(self, args: Dict[str, Any], ctx: ToolContext) -> str:
        """列出发起人所在的频道。全局模式(私聊)专用;频道模式拒绝(分身只看本频道)。"""
        if not ctx.is_dm:
            return (
                "我现在是这个频道的专属 AI，不提供跨频道清单。"
                "要跨频道统筹，请到右侧「私人会话」里找我。"
            )
        try:
            room_ids = self.client.joined_rooms()
        except Exception:
            room_ids = []
        if not room_ids:
            return "暂时拿不到频道列表(服务波动?),请稍后再试。"
        # 可见范围：普通用户只列自己在的频道(隐私边界);**平台管理员/负责人**列全部 bot 频道——
        # 否则他跨工作区查一个"自己没加入但组织里存在"的频道(如别的工作区的专班)会一直查不到。
        is_admin = bool(self.is_admin and self.is_admin(ctx.sender))
        import time as _time
        now = _time.time()
        out: List[str] = []
        for rid in room_ids[:150]:
            try:
                if self._room_kind(rid) != "channel":
                    continue  # AI 会话房/私信不算频道
                # 非管理员:只暴露发起人自己在的房;管理员:全部频道都可见(跨工作区统筹)。
                if not is_admin and not self.client.is_joined_member(rid, ctx.sender):
                    continue
                cached = self._room_name_cache.get(rid)
                if cached and now - cached[1] < 300:
                    name = cached[0]
                else:
                    ev = self.client.get_state_event(rid, "m.room.name")
                    name = str((ev or {}).get("name") or "")
                    self._room_name_cache[rid] = (name, now)
                if "控制室" in name:
                    continue  # 平台配置房,不是聊天频道
                out.append(f"· {name or '(未命名频道)'} — {rid}")
            except Exception:
                continue  # 单个房读不出不影响整体
        if not out:
            return "没有找到你所在的频道。"
        head = f"全部频道({len(out)} 个,跨工作区)" if is_admin else f"你所在的频道({len(out)} 个)"
        return (
            f"{head}:\n" + "\n".join(out)
            + "\n\n(要看某个频道最近聊了什么,我可以用 get_recent_messages 调取。)"
        )

    def _resolve_room_by_name(self, name: str) -> "Tuple[str, Optional[str]]":
        """把**频道名**解析成 room_id。返回 (room_id, None) 或 ("", 错误/引导文案)。

        在 bot 已加入的房间里按 m.room.name 匹配:精确命中唯一 → 用它;
        多个命中 → 列出候选让用户挑(重名群正是历史 bug 的产物);没精确命中再试包含匹配。
        房名带 5 分钟缓存,避免每次邀人都全量拉一遍 state。

        ⚠️ 只在**真正的频道**里找:排除 工作区(Space)/AI会话房/私信/控制室。否则"制作·女相师"
        这种**工作区名**会被当成频道命中,AI 把人邀进了工作区、频道里却一个人没多(线上实测)。
        """
        import time as _time
        now = _time.time()
        rooms = self.client.joined_rooms()
        if not rooms:
            return "", "我这边拿不到群列表(服务波动?),请稍后再试,或直接到目标群里@我操作。"
        # 刷新缓存(逐房读 m.room.name;5 分钟内复用),同时只保留"频道"类房间
        names: Dict[str, str] = {}
        for rid in rooms:
            if self._room_kind(rid) != "channel":
                continue  # 工作区/AI会话房/私信 都不是可邀人的"频道"
            cached = self._room_name_cache.get(rid)
            if cached and now - cached[1] < 300:
                names[rid] = cached[0]
                continue
            try:
                ev = self.client.get_state_event(rid, "m.room.name")
                nm = str((ev or {}).get("name") or "")
            except Exception:
                nm = ""
            names[rid] = nm
            self._room_name_cache[rid] = (nm, now)
        # 控制室是平台配置房,不是聊天频道,绝不能被解析成邀请目标
        names = {rid: nm for rid, nm in names.items() if "控制室" not in nm}
        exact = [rid for rid, nm in names.items() if nm == name]
        if len(exact) == 1:
            return exact[0], None
        if len(exact) > 1:
            listing = "\n".join(f"  · {names[r]}（{r}）" for r in exact[:6])
            return "", (
                f"有 {len(exact)} 个群都叫「{name}」,请告诉我用哪个(给 room_id):\n{listing}\n"
                "(重名群建议清理掉多余的。)"
            )
        part = [rid for rid, nm in names.items() if nm and name in nm]
        if len(part) == 1:
            return part[0], None
        if len(part) > 1:
            listing = "\n".join(f"  · {names[r]}（{r}）" for r in part[:6])
            return "", f"找到多个名字包含「{name}」的群,请说全名或给 room_id:\n{listing}"
        return "", (
            f"没找到叫「{name}」的**频道**。注意:工作区(左栏那一列)不是频道,不能往里邀人;"
            "请给**频道名**或 room_id,或直接到目标频道里@我操作。(我不在里面的频道我也看不到。)"
        )

    def _existing_channel_names(self) -> "set":
        """bot 可见的所有**频道**名字集合(排除 工作区/AI会话房/私信/控制室)。建专班防重名用。"""
        out: set = set()
        try:
            for rid in (self.client.joined_rooms() or []):
                if self._room_kind(rid) != "channel":
                    continue
                try:
                    ev = self.client.get_state_event(rid, "m.room.name")
                    nm = str((ev or {}).get("name") or "").strip()
                except Exception:
                    nm = ""
                if nm and "控制室" not in nm:
                    out.add(nm)
        except Exception:
            logger.debug("列现有频道名失败", exc_info=True)
        return out

    def _dedup_channel_name(self, name: str) -> str:
        """专班频道名防重名:已有同名频道 → 优先「<name>专班」,再撞加序号。

        场景(线上实测):已有频道「税务自查」,用户又让 AI 建专班,AI 直接又叫「税务自查」,
        左栏出现两个一模一样的频道、谁也分不清。加「专班」后缀区分。
        """
        name = (name or "").strip()
        if not name:
            return name
        existing = self._existing_channel_names()
        if name not in existing:
            return name
        base = name if name.endswith("专班") else name + "专班"
        if base not in existing:
            return base
        for i in range(2, 30):
            cand = f"{base}{i}"
            if cand not in existing:
                return cand
        return base

    def _room_name(self, room_id: str) -> str:
        """取房间显示名(复用 5 分钟名字缓存)。读不到返回空串。

        只用于把工具结果说清楚:让模型转述时报的是**真实落地的房间名**,而不是它自己以为的那个。
        (线上实测:模型把工作区名当频道名,发完消息还照着自己的说法回"已发到 xx 频道"。)
        """
        import time as _time
        now = _time.time()
        cached = self._room_name_cache.get(room_id)
        if cached and now - cached[1] < 300:
            return cached[0]
        try:
            ev = self.client.get_state_event(room_id, "m.room.name")
            nm = str((ev or {}).get("name") or "")
        except Exception:
            return ""
        self._room_name_cache[room_id] = (nm, now)
        return nm

    def _tool_invite_to_room(self, args: Dict[str, Any], ctx: ToolContext) -> str:
        """邀请用户进已有房间。默认当前房间；指定别的房间要过 _check_room_access 防越权。"""
        user_id = str(args.get("user_id") or "").strip()
        if not user_id.startswith("@") or ":" not in user_id:
            return "请给出完整用户 id（如 @bob:cosmac.cc）。"
        # 按群名找 room_id:用户在私人会话里通常只知道群名(如"邀请xx加入暑期研学活动")。
        room_name = str(args.get("room_name") or "").strip()
        if not args.get("room_id") and room_name:
            resolved, err = self._resolve_room_by_name(room_name)
            if err:
                return err
            args = dict(args)
            args["room_id"] = resolved
        # 防语义事故:私聊/AI会话房里说"邀请xx进本群",「本群」= 用户与我的私人会话——
        # 把人邀进来会闯进用户的私人对话(实测踩过:三位成员被邀进了群主的AI私聊)。
        # 私聊里必须显式给 room_id 或群名(群 id 在 create_room 的结果里/上下文里有)。
        if ctx.is_dm and not args.get("room_id"):
            return (
                "当前是你与我的私聊会话，「本群」指的是这个私人对话——不能把别人邀进来。"
                "请告诉我要邀请到哪个群（说出**群名**即可，比如『邀请 @xx 加入暑期研学活动』），"
                "或者直接到目标群里 @我 再说一次邀请。"
            )
        room_id = args.get("room_id") or ctx.room_id
        denial = self._check_room_access(room_id, ctx)
        if denial:
            return denial
        # 带状态邀请:拿到真实失败原因,别让模型对用户瞎猜"可能未注册/可能没权限"
        if hasattr(self.client, "invite_user_status"):
            ok, status, err = self.client.invite_user_status(room_id, user_id)
        else:  # 测试桩等只有 bool 口的客户端
            ok, status, err = self.client.invite_user(room_id, user_id), 0, ""
        # 403=bot 在该频道没邀请权限(用户建的频道里 bot 只是普通成员)。用服务器管理 API
        # 给 bot 自己提成房管理员再重试一次——发起人已过 _check_room_access(必须是房内成员/
        # 本频道内@),提权只补 bot 的执行力,不扩大用户权限。
        if not ok and status == 403 and self._promote_bot_in_room(room_id):
            ok, status, err = self.client.invite_user_status(room_id, user_id)
        if ok:
            nm = self._room_name(room_id)
            where = f"「{nm}」（{room_id}）" if nm else f"房间 {room_id}"
            return (
                f"已邀请 {user_id} 加入{where}。"
                "对方下次打开客户端会自动入群（本服务器账号）。"
                "转告用户时**必须用这里的真实频道名**，不要用你以为的名字。"
            )
        detail = f"（服务器返回 {status}: {err}）" if status else "（网络异常，请稍后重试）"
        return (
            f"邀请 {user_id} 失败{detail}。"
            "请把括号里的真实原因原样转告用户,不要自行猜测别的原因;"
            "若是权限类失败,建议用户请频道管理员在「频道管理→人员」里手动邀请。"
        )

    def _promote_bot_in_room(self, room_id: str) -> bool:
        """bot 在目标房间权限不足时,用服务器管理 API(make_room_admin)把自己提成房管理员。

        依赖服务端已配 COSMAC_ADMIN_TOKEN(与"平台管理员接管频道"同一条通道);未配/失败
        都静默返回 False,调用方按原始错误提示。"""
        try:
            from cosmac import registration

            code, _ = registration.make_room_admin(
                self.client.homeserver_url, room_id, self.client.bot_user_id
            )
            return code == 200
        except Exception:
            logger.debug("bot 房间内自动提权失败（忽略）", exc_info=True)
            return False

    def _tool_send_message(self, args: Dict[str, Any], ctx: ToolContext) -> str:
        text = args.get("text") or ""
        if not text.strip():
            return "没有可发送的内容。"
        # 按群名找 room_id(与 invite_to_room 同款):用户说"往暑期托管班群发个公告",
        # 模型往往只有群名没有 id。
        room_name = str(args.get("room_name") or "").strip()
        if not args.get("room_id") and room_name:
            resolved, err = self._resolve_room_by_name(room_name)
            if err:
                return err
            args = dict(args)
            args["room_id"] = resolved
        # 防语义事故(QA 实测踩过):私聊里让 AI"给群里发公告",模型不带 room_id 调用 →
        # 公告落在用户与 AI 的私聊里,AI 报"已发送",目标群其他成员什么都收不到。
        # 私聊里发消息给用户=直接回复即可,不需要这个工具;所以没有目标群一律拦下。
        if ctx.is_dm and not args.get("room_id"):
            return (
                "当前是你与我的私聊会话——在这里发消息其他成员看不到。"
                "请告诉我要发到哪个群（给**群名**或 room_id，比如『把公告发到暑期托管班群』），"
                "我再发送。"
            )
        room_id = args.get("room_id") or ctx.room_id
        denial = self._check_room_access(room_id, ctx)
        if denial:
            return denial
        event_id = self.client.send_text(room_id, text)
        if not event_id:
            return f"往房间 {room_id} 发消息失败。"
        nm = self._room_name(room_id)
        where = f"「{nm}」（{room_id}）" if nm else f"房间 {room_id}"
        return (
            f"已往{where}发送消息（event_id={event_id}）。"
            "转告用户时**必须用这里的真实频道名**，不要用你以为的名字。"
        )

    def _tool_list_members(self, args: Dict[str, Any], ctx: ToolContext) -> str:
        room_id = args.get("room_id") or ctx.room_id
        denial = self._check_room_access(room_id, ctx)
        if denial:
            return denial
        members = self.client.get_members(room_id)
        if not members:
            return f"房间 {room_id} 没查到成员（或查询失败）。"
        lines = [f"- {m['display_name']}（{m['user_id']}）" for m in members]
        return f"房间 {room_id} 共有 {len(members)} 名成员：\n" + "\n".join(lines)

    def _tool_get_messages(self, args: Dict[str, Any], ctx: ToolContext) -> str:
        room_id = args.get("room_id") or ctx.room_id
        denial = self._check_room_access(room_id, ctx)
        if denial:
            return denial
        limit = max(1, min(50, int(args.get("limit") or 20)))
        msgs = self.client.get_messages(room_id, limit=limit)
        if not msgs:
            return f"房间 {room_id} 没查到聊天记录（或查询失败）。"
        # 用 JSON 回灌，模型读起来结构清晰
        return "最近聊天记录（旧→新）：\n" + json.dumps(msgs, ensure_ascii=False)

    def _check_room_access(self, room_id: str, ctx: ToolContext) -> str:
        """跨房间工具调用的权限检查；返回空串表示放行，否则返回拒绝文案。

        双层作用域(频道分身 vs 全局助理)——用 ctx.is_dm 区分:
          · **频道模式**(在某频道里 @AI，is_dm=False)：AI 是"这个频道的分身"，作用域**锁死本频道**。
            访问任何别的房间一律拒绝——频道分身只看/只动自己这个群，是数据隔离的墙。
          · **全局模式**(右侧私人会话，is_dm=True)：AI 是"全局助理"，可跨房间，但**以发起人本人的
            成员身份为界**——只能碰用户自己在的房间，bot 权限高不代表能替用户越权偷看别的群。
        当前房间在两种模式下都直接放行。
        """
        if room_id == ctx.room_id:
            return ""
        # 频道模式:锁死本频道,不许碰别的房间(即便用户是那房间的成员也不行——分身只服务本频道)
        if not ctx.is_dm:
            return (
                "我现在是这个频道的专属 AI，只处理本频道的事，不能去操作别的频道。"
                "要跨频道操作，请到右侧「私人会话」里对我说。"
            )
        # 全局模式:跨房间以发起人成员身份为界
        checker = getattr(self.client, "is_joined_member", None)
        if not checker:
            return "无法确认你是否有权访问该房间，已拒绝跨房间操作。"
        try:
            if checker(room_id, ctx.sender):
                return ""
        except Exception:
            logger.warning("检查跨房间权限失败 room=%s sender=%s", room_id, ctx.sender)
        return f"你不是房间 {room_id} 的已加入成员，我不能替你读写这个房间。"

    # —— 工作流连接器 ——

    def _workflow_defs(self) -> List[Dict[str, Any]]:
        """读控制室「工作流连接器」定义（启用的）；失败/无配置返回空。"""
        if not self._control_room_alias:
            return []
        try:
            ctrl = self.client.resolve_alias(self._control_room_alias)
            if not ctrl:
                return []
            ev = self.client.get_state_event(ctrl, WORKFLOWS_EVENT_TYPE) or {}
            return [
                w for w in (ev.get("workflows") or [])
                if isinstance(w, dict) and w.get("slug") and w.get("enabled", True)
            ]
        except Exception:
            return []

    def _is_platform_admin(self, sender: str) -> bool:
        """是否平台管理员 = 控制室 power≥50。工作流(共享付费凭据)只许平台管理员触发，
        **不分 DM/群**——否则任何人和 bot 开个两人 DM 就能跑。读不到/非控制室成员→拒。
        """
        if not self._control_room_alias:
            return False
        try:
            ctrl = self.client.resolve_alias(self._control_room_alias)
            if not ctrl:
                return False
            pl = self.client.get_state_event(ctrl, "m.room.power_levels", "") or {}
            users = pl.get("users") or {}
            level = users.get(sender, pl.get("users_default", 0))
            return isinstance(level, int) and level >= 50
        except Exception:
            return False

    def _tool_run_workflow(self, args: Dict[str, Any], ctx: ToolContext) -> str:
        # #1/#2 越权防护：跑工作流触发外部/付费操作、用服务端共享凭据，必须授权。
        # 接了门控钩子时(生产)由 execute() 的 gate_check 统一裁决(走 workflow_run 门槛配置)；
        # 没接门控钩子时(独立/单测)退回硬基线——只许平台管理员，绝不无授权放行。
        if self.gate_check is None and not self._is_platform_admin(ctx.sender):
            return "只有平台管理员能让我跑工作流（它会触发外部/付费操作、用服务端共享凭据）。"
        defs = self._workflow_defs()
        slug = (args.get("slug") or "").strip()
        if not slug:
            if not defs:
                return "当前没有已配置的工作流连接器（去管理后台→工作流添加）。"
            listing = "；".join(
                f"{w.get('slug')}（{w.get('name') or ''}）" for w in defs
            )
            return f"可用工作流：{listing}。请带 slug 再调一次。"
        conn = next((w for w in defs if w.get("slug") == slug), None)
        if conn is None:
            avail = "、".join(w.get("slug", "") for w in defs) or "（空）"
            return f"没找到工作流「{slug}」。可用：{avail}"
        # 延迟导入：HTTP 执行与 DB 记录都不在工具加载期引入
        from cosmac.wf import run_connector, submit_background

        user_input = args.get("input") or ""
        name = conn.get("name") or slug
        platform = conn.get("platform", "webhook")
        # 幂等键拼上 slug：ctx.source_key 在一次 Agent run 内共享（同一条消息），若直接拿它查重，
        # 一句"跑一下工作流 A 和 B"里 B 会命中 A 的登记、被误判"重复提交"（审查 bug#8）。
        # 拼 slug 后：事务重放（同 event 同 slug）仍防得住；同消息不同工作流互不干扰。
        skey = f"{ctx.source_key}:{slug}" if ctx.source_key else ""

        # #1/#3：异步连接器(async=true、bot 注入了 dispatch_async、**且平台支持回调**) → 走回调
        # 协议；dify/coze/comfyui 没有回调通道，即便误存 async=true 也按后台同步跑（不挂 pending）。
        from cosmac.wf import supports_async_callback
        if conn.get("async") and self.dispatch_async and supports_async_callback(platform):
            out = self.dispatch_async(
                conn, user_input, ctx.room_id, ctx.sender, name, skey
            )
            # 真正发起了一次异步提交 → 此刻消费配额（列表/找不到 slug 的分支不该扣）
            self._consume_quota(ctx, "run_workflow")
            return out

        # #1/#4/#5：**其余所有连接器**都放有界后台池跑、立即给 Agent 一个"已开始"让它继续——
        # webhook/dify/coze(≤30s) 也会卡住 Agent + appservice 事务，ComfyUI 更甚(120s)。
        # 跑完把结果发回群（ComfyUI 自己发图，其它平台发文本）。池满则拒。
        def _work() -> None:
            try:
                r = run_connector(
                    conn, user_input, client=self.client, room_id=ctx.room_id
                )
                # 落账必须用与预约**同一个** skey（含 slug），否则查不到上面 _reserve 建的 queued
                # 占位、会另插一行，占位永不结清 → 1 小时后被遗孤回收误报"提交队列中断"（#5）。
                self._record_workflow_run(slug, platform, ctx, user_input, r, source_key=skey)
                if not r.get("ok"):
                    self.client.send_text(
                        ctx.room_id, f"⚠️ 工作流「{name}」执行失败：{r.get('error')}"
                    )
                elif platform != "comfyui":
                    self.client.send_text(
                        ctx.room_id,
                        f"✅ 工作流「{name}」已完成：\n{r.get('output') or '（无内容）'}",
                    )
            except Exception:
                logger.exception("后台工作流执行出错：%s", name)

        pool = "slow" if platform == "comfyui" else "fast"  # ComfyUI 走慢池(#5)
        reserved = bool(skey)
        if reserved and not self._reserve_workflow_source(
            skey, slug, platform, ctx, user_input
        ):
            return f"工作流「{name}」已经由这条消息触发过，我不会重复提交。"
        if submit_background(_work, pool=pool):
            # 真正提交进后台池 → 此刻消费配额（失败/列表/重复分支都不扣，审查 bug#7）
            self._consume_quota(ctx, "run_workflow")
            return f"工作流「{name}」已开始，完成后我会把结果发到群里。"
        # 池满提交失败：必须回滚刚才的来源预约，否则这条事件之后重试会被误判"已触发过"
        # 而永远跑不起来（预约占位残留，直到 1 小时后才被遗孤回收并误报"提交队列中断"）。
        if reserved:
            self._release_workflow_source(skey)
        return "任务太多、系统繁忙，请稍后再让我跑。"

    def _tool_create_tasks(self, args: Dict[str, Any], ctx: ToolContext) -> str:
        """把目标拆成的子任务批量登记到任务看板（写 cosmac DB，AI 任务编排 P1）。"""
        goal = (args.get("goal") or "").strip()
        items = args.get("tasks") or []
        if not isinstance(items, list) or not items:
            return "没有可登记的子任务。"
        # 把每条的截止时间 due(字符串) 解析成 due_ts(epoch 秒)，交给 create_tasks 落库；解析不了忽略。
        for it in items:
            if isinstance(it, dict) and it.get("due"):
                it["due_ts"] = _parse_due_to_ts(it.get("due"))
        by_person: Dict[str, list] = {}  # 真人被指派者 id → 其任务标题(用于群内 @ 通知,bug12)
        try:
            from cosmac.db import session_scope
            from cosmac.db.task_repo import create_tasks

            with session_scope() as s:
                created = create_tasks(
                    s, goal=goal, items=items,
                    room_id=ctx.room_id, sender=ctx.sender,
                    space_id=ctx.space_id,   # 归到发起人当时所在的工作区
                )
                n = len(created)
                # 给模型回灌时把指派情况也带上（类型化执行者 + 人读标签），便于它据此继续编排
                _kind_label = {
                    "human": "派给", "agent": "交AI", "workflow": "跑工作流",
                }
                lines = []
                for t in created:
                    seg = f"• {t.title}"
                    if t.executor_kind != "none" and t.executor_ref:
                        seg += f" —— {_kind_label.get(t.executor_kind, '')}{t.executor_ref}"
                    elif t.assignee:
                        seg += f" —— {t.assignee}"
                    lines.append(seg)
                    # 收集真人被指派者(id 以 @ 开头才能 @提及触发通知;AI/工作流执行者不 @)
                    who = (t.executor_ref if t.executor_kind == "human" else "") or t.assignee or ""
                    if who.startswith("@"):
                        by_person.setdefault(who, []).append(t.title)
        except Exception:
            logger.exception("登记任务到看板失败")
            return "登记任务到看板失败（数据库不可用？）。"
        if not n:
            return "没有有效的子任务可登记。"
        # 通知被指派的真人:群里 @ 他们(Matrix 默认推送规则:正文含对方用户名即触发通知),
        # 别让任务只躺看板、当事人不知道(bug12)。一人一条、best-effort,发失败不影响任务已登记。
        for _who, _titles in by_person.items():
            try:
                self.client.send_text(
                    ctx.room_id,
                    f"{_who} 你被指派了 {len(_titles)} 个任务："
                    f"{'、'.join(_titles)}。详情见「任务看板」。",
                )
            except Exception:
                logger.debug("通知任务被指派者失败 who=%s", _who, exc_info=True)
        return f"已把目标拆成 {n} 个任务、登记到「任务看板」：\n" + "\n".join(lines)

    def _tool_list_capabilities(self, args: Dict[str, Any], ctx: ToolContext) -> str:
        """能力名册（转发到 bot 注入的 list_capabilities）。未注入则优雅降级。"""
        if self.list_capabilities is None:
            return "（能力名册当前不可用。）"
        try:
            return self.list_capabilities(ctx)
        except Exception:
            logger.exception("能力名册工具执行出错")
            return "读取能力名册时出错了。"

    def _tool_search_knowledge(self, args: Dict[str, Any], ctx: ToolContext) -> str:
        """主动检索知识库（转发到 bot 注入的 kb_search）。门控由 execute 的 gate_check
        统一裁决(search_knowledge→knowledge)，这里不重复判。"""
        query = (args.get("query") or "").strip()
        if not query:
            return "请给出要检索的关键词或问题。"
        if self.kb_search is None:
            return "（知识库检索当前不可用。）"
        try:
            return self.kb_search(query, ctx)
        except Exception:
            logger.exception("知识库检索工具执行出错")
            return "检索知识库时出错了。"

    def _tool_web_search(self, args: Dict[str, Any], ctx: ToolContext) -> str:
        """联网搜索（走 cosmac.ai.websearch 的可插拔后端）。门控由 execute 的 gate_check
        统一裁决(web_search→web_search 能力)，这里不重复判。绝不抛异常。"""
        query = (args.get("query") or "").strip()
        if not query:
            return "请给出要搜索的关键词或问题。"
        try:
            limit = max(1, min(10, int(args.get("limit") or 5)))
        except (TypeError, ValueError):
            limit = 5
        try:
            from cosmac.ai.websearch import get_searcher

            searcher = get_searcher()
            if not searcher.available:
                return "（联网搜索未配置：管理员需在服务端设置搜索服务 key 后才能用。）"
            hits = searcher.search(query, k=limit)
        except Exception:
            logger.exception("联网搜索工具执行出错")
            return "联网搜索时出错了。"
        if not hits:
            return f"没搜到与「{query}」相关的结果（可换个说法再试）。"
        lines = ["联网搜索结果（请据此作答，并可附上来源链接）："]
        for i, h in enumerate(hits, 1):
            title = h.get("title") or "(无标题)"
            url = h.get("url") or ""
            snippet = (h.get("snippet") or "")[:300]
            lines.append(f"[{i}] {title}\n    {url}\n    {snippet}")
        return "\n".join(lines)

    def _tool_query_hr(self, args: Dict[str, Any], ctx: ToolContext) -> str:
        """人事数据查询（数据智能）。只读地查 cosmac_employee 花名册并做聚合。

        门控由 execute 的 gate_check 统一裁决（query_hr→hr_data 能力，默认仅管理员），
        这里不重复判权限。把结果整理成**紧凑的 JSON 文本**回给模型——模型据此用自然语言
        回答并做分析。绝不抛异常（DB 不可用/无数据都给出可读提示）。
        """
        import json as _json

        action = (args.get("action") or "summary").strip().lower()
        try:
            from cosmac.db import session_scope
            from cosmac.db import employee_repo as hr

            with session_scope() as s:
                # 先做一个空表兜底：没灌数据时明确告知，别让模型编
                if hr.company_summary(s)["在职人数"] == 0 and \
                        not hr.list_employees(s, limit=1):
                    return "人事数据库里还没有员工数据（需要先播种/导入花名册）。"

                if action == "roster":
                    rows = hr.list_employees(
                        s,
                        department=args.get("department") or "",
                        status=args.get("status") or "",
                        keyword=args.get("keyword") or "",
                        city=args.get("city") or "",
                        level=args.get("level") or "",
                        perf_rating=args.get("perf_rating") or "",
                        # 工具喂模型上下文，top_n 夹到 60 上限（页面全量走 handle_hr_employees，L13）
                        limit=min(int(args.get("top_n") or 60), 60),
                    )
                    data = {
                        "查询": "花名册",
                        "命中人数": len(rows),
                        "员工": [hr.to_dict(e) for e in rows],
                    }
                elif action == "headcount":
                    data = {"查询": "人数编制", **hr.headcount(
                        s, group_by=args.get("group_by") or "department",
                        include_resigned=(args.get("status") == "resigned"),
                    )}
                elif action == "salary":
                    data = {"查询": "薪酬统计", **hr.salary_stats(
                        s, group_by=args.get("group_by") or "department")}
                elif action == "performance":
                    data = {"查询": "绩效分布", **hr.perf_distribution(
                        s, department=args.get("department") or "")}
                elif action in ("ranking", "attendance"):
                    field = args.get("field") or (
                        "overtime" if action == "attendance" else "salary")
                    data = {"查询": "排行榜", **hr.top_by(
                        s, field=field, n=int(args.get("top_n") or 5),
                        department=args.get("department") or "")}
                elif action == "trend":
                    data = {"查询": "入离职趋势", **hr.joins_leaves(
                        s, months=int(args.get("months") or 6))}
                elif action == "find":
                    kw = (args.get("keyword") or "").strip()
                    if not kw:
                        return "请给出要查的人的姓名或工号（keyword）。"
                    rows = hr.list_employees(s, keyword=kw, limit=10)
                    if not rows:
                        return f"没找到与「{kw}」匹配的员工。"
                    data = {
                        "查询": "按人查档",
                        "命中": [hr.to_dict(e) for e in rows],
                    }
                else:  # summary 及未知动作
                    data = {"查询": "公司人事总览", "公司": "星澜科技",
                            **hr.company_summary(s)}
            # ensure_ascii=False 保留中文，模型直接可读
            return _json.dumps(data, ensure_ascii=False)
        except Exception:
            logger.exception("人事数据查询工具执行出错")
            return "查询人事数据时出错了（数据库不可用？）。"

    def _tool_query_sales(self, args: Dict[str, Any], ctx: ToolContext) -> str:
        """销售业绩查询（数据智能）。只读地查 cosmac_sales_record 并聚合。

        门控由 execute 的 gate_check 统一裁决（query_sales→sales_data，默认仅管理员）。
        返回紧凑中文 JSON 供模型分析。绝不抛异常。
        """
        import json as _json

        action = (args.get("action") or "summary").strip().lower()
        period = (args.get("period") or "").strip()
        try:
            from cosmac.db import sales_repo as sr
            from cosmac.db import session_scope

            with session_scope() as s:
                if not sr.has_data(s):
                    return "销售业绩库里还没有数据（需要先播种/导入销售数据）。"

                if action == "ranking":
                    data = {"查询": "销售排行榜", **sr.ranking(
                        s, period=period, by=args.get("by") or "actual",
                        n=int(args.get("top_n") or 5))}
                elif action == "trend":
                    data = {"查询": "销售趋势", **sr.trend(
                        s, months=int(args.get("months") or 6))}
                elif action == "person":
                    kw = (args.get("keyword") or "").strip()
                    if not kw:
                        return "请给出要查的销售员姓名或工号（keyword）。"
                    detail = sr.person(s, keyword=kw, months=int(args.get("months") or 6))
                    if not detail:
                        return f"没找到「{kw}」的销售业绩记录（可能不是销售岗）。"
                    data = {"查询": "个人销售业绩", **detail}
                else:  # summary 及未知动作
                    data = {"查询": "销售概况", "公司": "星澜科技",
                            **sr.monthly_summary(s, period=period)}
            return _json.dumps(data, ensure_ascii=False)
        except Exception:
            logger.exception("销售业绩查询工具执行出错")
            return "查询销售业绩时出错了（数据库不可用？）。"

    def _tool_ask_user_choice(self, args: Dict[str, Any], ctx: ToolContext) -> str:
        """发一张「选择卡」给用户点选（档·交互增强）。结束本轮，等用户点完发回再继续。"""
        question = (args.get("question") or "").strip()
        raw = args.get("options") or []
        if not question or not isinstance(raw, list) or not raw:
            return "需要给出问题和至少一个选项。"
        options = []
        for o in raw[:8]:
            if isinstance(o, dict):
                label = str(o.get("label") or "").strip()
                value = str(o.get("value") or "").strip() or label
            else:
                label = value = str(o).strip()
            if label:
                options.append({"label": label, "value": value})
        if not options:
            return "选项无效。"
        multi = bool(args.get("multi"))
        card = {"kind": "choice", "question": question, "options": options, "multi": multi}
        # 纯文本兜底：Element 等不认 cosmac.card 的客户端显示这段，仍可看到选项
        body = "\n".join([question] + [f"{i}. {o['label']}" for i, o in enumerate(options, 1)])
        try:
            self.client.send_card(ctx.room_id, body, card)
        except Exception:
            logger.exception("发送选择卡失败")
            return "发选项时出错了，请直接用文字告诉我你的选择。"
        return "已把选项发给用户，等 TA 点选后我再继续。"

    def _tool_list_room_tasks(self, args: Dict[str, Any], ctx: ToolContext) -> str:
        """列出频道任务（档4）：给项目主AI/中枢AI 跟踪/审核用。绝不抛异常。

        room 参数(评审后补,负责人线上实测):此前只能查"当前频道",在中枢 AI 私聊里问
        「查XX专班的进度」时模型只能看频道清单猜名字,把「讲座活动专班」猜成了前缀相近的
        「讲座活动」母频道。现在按名字精确解析(撞名列候选);查别的频道要求发起人是
        该频道成员(防越权翻别人频道的任务)。
        """
        target = str(args.get("room") or "").strip()
        room_id = ctx.room_id
        label = "本频道"
        if target and target != ctx.room_id:
            if target.startswith("!"):
                room_id = target
            else:
                rid, err = self._resolve_room_by_name(target)
                if not rid:
                    return err or f"没找到叫「{target}」的频道。"
                room_id = rid
            label = f"频道「{target}」"
            # 越权防护:查非当前频道时,发起人必须在目标频道里(任务标题/结果不该对外泄露)
            try:
                member_ids = {
                    str(m.get("user_id") or "")
                    for m in (self.client.get_members(room_id) or [])
                }
                if ctx.sender not in member_ids:
                    return f"你不在{label}里,看不了它的任务(先加入该频道)。"
            except Exception:
                return "确认频道成员失败(服务波动?),请稍后再试或到该频道里问我。"
        try:
            from cosmac.db import session_scope
            from cosmac.db.task_repo import list_tasks

            with session_scope() as s:
                rows = list_tasks(s, room_ids=[room_id])
                if not rows:
                    return f"{label}还没有任务。"
                lines = []
                done = 0
                for t in rows:
                    if t.status == "done":
                        done += 1
                    seg = f"#{t.id} [{t.status}] {t.title}"
                    if t.executor_kind != "none" and t.executor_ref:
                        seg += f"（{t.executor_kind}:{t.executor_ref}）"
                    elif t.assignee:
                        seg += f"（{t.assignee}）"
                    if t.result:
                        seg += f" — 结果/批注：{t.result[:200]}"
                    lines.append(seg)
                total = len(rows)
            # 完成度抬头：让项目主AI 一眼看清节点进度；全部完成时提示走归档收尾
            head = f"{label}任务（完成度 {done}/{total}）："
            if done == total:
                head += "\n✅ 所有节点已完成——可征得用户同意后用 archive_project 归档收尾、关闭频道。"
            return head + "\n" + "\n".join(lines)
        except Exception:
            logger.exception("列频道任务失败")
            return "读取任务失败（数据库不可用？）。"

    def _tool_update_task(self, args: Dict[str, Any], ctx: ToolContext) -> str:
        """更新本频道某任务（档4：推进/审核回填）。越权防护：只能改 room_id==当前频道 的任务。"""
        try:
            tid = int(args.get("task_id"))
        except (TypeError, ValueError):
            return "请给出要更新的任务编号 task_id（先用 list_room_tasks 拿编号）。"
        # 状态白名单 + 同义词归一化（M6）：非法值直接拒绝，绝不透传给 task_repo 被静默丢弃、
        # 却回一句"已更新→<非法值>"的假成功（模型/用户会以为改成功了）。
        status = _normalize_task_status(args.get("status"))
        if status is not None and status not in _TASK_STATUSES:
            return "任务状态只能是 待办(todo)/进行中(doing)/已完成(done) 之一，请用其中之一。"
        result = args.get("result")
        progress = args.get("progress")
        # 截止日期：没给这个键=不动;给了(含空串)=改期。空串→清除(None);否则解析日期→epoch 秒。
        from cosmac.db.task_repo import _DUE_UNSET
        due_val: Any = _DUE_UNSET
        due_label = ""
        if "due" in args and args.get("due") is not None:
            raw = str(args.get("due")).strip()
            if raw == "":
                due_val = None            # 显式清除截止
                due_label = "清除截止日期"
            else:
                parsed = _parse_due_to_epoch(raw)
                if parsed is None:
                    return "截止日期看不懂，请用『2025-07-11』或『2025-07-11 10:00』这样的格式。"
                due_val = parsed
                due_label = f"截止改为 {raw}"
        try:
            from cosmac.db import session_scope
            from cosmac.db.task_repo import get_task, update_task

            with session_scope() as s:
                t = get_task(s, tid)
                # 越权防护：只能改"本频道"的任务，碰不到别的项目/专班的看板
                if t is None or (t.room_id or "") != ctx.room_id:
                    return f"没找到属于本频道的任务 #{tid}。"
                title = t.title
                ok = update_task(
                    s, tid,
                    status=status,
                    result=result if isinstance(result, str) else None,
                    progress=progress if isinstance(progress, int) else None,
                    due_ts=due_val,
                )
            if not ok:
                return f"任务 #{tid} 没有可更新的内容。"
            tail = f" → {status}" if status else ""
            if due_label:
                tail += f"（{due_label}）"
            return f"已更新任务 #{tid}「{title}」{tail}。"
        except Exception:
            logger.exception("更新任务失败")
            return "更新任务失败（数据库不可用？）。"

    def _can_archive(self, ctx: ToolContext) -> bool:
        """能否归档本频道（L9）：平台管理员 或 本频道管理员(power≥50)。读不到权限→False(拒绝)。"""
        try:
            if self.is_admin and self.is_admin(ctx.sender):
                return True
            pl = self.client.get_state_event(ctx.room_id, "m.room.power_levels") or {}
            users = pl.get("users") if isinstance(pl, dict) else None
            users = users if isinstance(users, dict) else {}
            default = int(pl.get("users_default", 0) or 0) if isinstance(pl, dict) else 0
            return int(users.get(ctx.sender, default) or 0) >= 50
        except Exception:
            logger.debug("归档授权读取失败（拒绝）", exc_info=True)
            return False

    def _tool_archive_project(self, args: Dict[str, Any], ctx: ToolContext) -> str:
        """归档收尾本专班（模块3.5 收尾）：存归档记录 → 清频道长期记忆 → 贴收尾通知。

        把整盘项目落成一条 ProjectArchive（总目标+任务快照+收尾摘要），然后清掉本频道的
        滚动长期记忆（项目已结，不再占记忆），再写一个『已归档』state 标记 + 在群里贴通知。
        越权防护：只归档「本频道」的任务。绝不抛异常。

        L9 授权：清长期记忆是**不可逆**的破坏性收尾，绝不能让频道内任意普通成员一句话触发。
        只有频道管理员（power≥50；assemble_team 已把发起人设为 100）或平台管理员能做。
        """
        # L9：破坏性动作前置授权，读不到权限一律拒绝（fail-closed）
        if not self._can_archive(ctx):
            return (
                "归档会清空本频道的长期记忆（不可逆），属项目收尾动作，只有频道管理员/项目负责人"
                "能操作。如确需归档，请让频道管理员来做。"
            )
        summary = (args.get("summary") or "").strip()
        try:
            from cosmac.db import session_scope
            from cosmac.db.archive_repo import create_archive
            from cosmac.db.memory_repo import clear_summary
            from cosmac.db.models import SCOPE_ROOM
            from cosmac.db.task_repo import list_tasks

            with session_scope() as s:
                rows = list_tasks(s, room_ids=[ctx.room_id])
                if not rows:
                    return "本频道没有任务，无需归档。"
                # 任务快照 + 完成度统计
                snapshot = []
                goal = ""
                done = 0
                for t in rows:
                    if not goal and t.goal:
                        goal = t.goal
                    if t.status == "done":
                        done += 1
                    snapshot.append({
                        "id": t.id,
                        "title": t.title,
                        "status": t.status,
                        "executor_kind": t.executor_kind,
                        "executor_ref": t.executor_ref,
                        "assignee": t.assignee or "",
                        "result": (t.result or "")[:500],
                    })
                total = len(rows)
                create_archive(
                    s,
                    room_id=ctx.room_id,
                    goal=goal,
                    summary=summary,
                    tasks=snapshot,
                    done_count=done,
                    total_count=total,
                    archived_by=ctx.sender,
                )
                # 项目已结：清掉本频道的滚动长期记忆，不浪费 Agent 记忆（成果已进归档）
                cleared = clear_summary(s, SCOPE_ROOM, ctx.room_id)
        except Exception:
            logger.exception("归档专班失败")
            return "归档失败（数据库不可用？），频道先别关，稍后再试。"

        # 写一个『已归档』state 标记（best-effort：失败不影响归档已落库）
        try:
            self.client.set_state_event(
                ctx.room_id, "cosmac.project.archived",
                {"archived": True, "summary": summary[:500], "by": ctx.sender,
                 "done": done, "total": total},
            )
        except Exception:
            logger.warning("写归档 state 标记失败（已忽略）")

        # 群里贴收尾通知
        note = (
            f"🗄 本专班已归档收尾（完成度 {done}/{total}）。\n"
            f"收尾摘要：{summary or '（无）'}\n"
            "项目成果已存档，可随时回查；本频道的长期记忆已清理。"
            "如不再需要，可以关闭/退出本频道了。"
        )
        try:
            self.client.send_text(ctx.room_id, note)
        except Exception:
            logger.warning("贴归档通知失败（已忽略）")

        mem = "，已清理频道长期记忆" if cleared else ""
        return f"已归档专班「{goal or ctx.room_id}」（{done}/{total} 完成）{mem}。已在群里贴出收尾通知并提示可关闭频道。"

    def _tool_assemble_team(self, args: Dict[str, Any], ctx: ToolContext) -> str:
        """一键建专班（模块3.5 档3）：建频道→拉人→绑AI→写任务RULE/技能→派单。

        把前几档的积木串起来。门控走 create_room（建房+拉人+绑配置是重动作）。绝不抛异常。
        """
        project = (args.get("project") or "").strip()
        if not project:
            return "请给专班/项目起个名字。"
        members = [str(m).strip() for m in (args.get("members") or []) if str(m).strip()]
        # 防重名:已有同名频道就给这个专班加「专班」后缀区分,别让左栏出现两个一模一样的频道。
        # project 仍作为项目目标/RULE 里的人读标签;channel_name 只是频道的显示名。
        channel_name = self._dedup_channel_name(project)
        # 健壮性：只用发起人(必然存在)建房，其余成员**逐个尽力邀请**——某个 id 不存在/邀请
        # 失败都不影响专班建成（否则一个坏 id 就把整件事搞崩）。
        # 发起人 = 专班主人：建房时就提成 100 级管理员，否则他改不了频道名/配置(403)。
        room_id = self.client.create_room(
            channel_name, invitees=[ctx.sender], admins=[ctx.sender]
        )
        if not room_id:
            return f"建专班「{channel_name}」失败了（建房间接口出错）。"
        # 专班房**真建成**才消费 teams 配额（终身配额，失败绝不能扣——否则免费用户被一次
        # Synapse 抖动扣光就永久锁死，审查 bug#7）。
        self._consume_quota(ctx, "assemble_team")
        invited, failed = [], []
        for m in members:
            if m == ctx.sender:
                continue  # 发起人建房时已邀
            try:
                ok = self.client.invite_user(room_id, m)
            except Exception:
                ok = False
            (invited if ok else failed).append(m)

        lead = (args.get("lead_agent") or "").strip()
        workers = [str(a).strip() for a in (args.get("worker_agents") or []) if str(a).strip()]
        skills = [str(s).strip() for s in (args.get("skills") or []) if str(s).strip()]
        task_rule = (args.get("task_rule") or "").strip()

        # —— 资源存在性校验(不能静默失效):模型给的 Agent/Skill 必须真在库里 ——
        # 不在库里的:从绑定清单剔除(防写进配置后查无此物、悄悄不生效),并收集进 missing
        # 提醒用户"缺什么、去哪补"。校验回调未注入/失败 → 跳过校验(优雅降级,绝不挡组班)。
        # M2 越权：按**发起人 access** 过滤可见资源——发起人够不到的受限智能体/技能不在集合里，
        # 点名它当 lead/worker/skill 会被下面当"缺口"剔除，绝不注入其付费人设/技能正文。
        missing: List[str] = []
        try:
            known_a = self.known_agents(ctx.sender) if self.known_agents else None
        except Exception:
            known_a = None
        if known_a is not None:
            # 宽容解析(下划线/中划线/大小写/按名称),解析成功即替换成库里的真 slug——
            # 否则模型写 marketing_campaign(库里是 marketing-campaign)就被误报"库里没有"。
            if lead:
                ok_l, bad_l = _resolve_resource_slugs([lead], known_a)
                if bad_l:
                    missing.append(f"项目主AI人设「{lead}」(已回退内置编排人设)")
                    lead = ""
                else:
                    lead = ok_l[0]
            resolved_w, bad_w = _resolve_resource_slugs(workers, known_a)
            if bad_w:
                missing.append("协作AI:" + "、".join(bad_w))
            workers = resolved_w
        try:
            known_s = self.known_skills(ctx.sender) if self.known_skills else None
        except Exception:
            known_s = None
        if known_s is not None:
            resolved_s, bad_s = _resolve_resource_slugs(skills, known_s)
            if bad_s:
                missing.append("技能:" + "、".join(bad_s))
            skills = resolved_s

        # —— 任务 RULE 保底:模型没给约束时自动生成基础版,专班绝不"裸奔" ——
        # (负责人设计:到了频道后,频道主AI要受本专班任务约束——RULE 是频道自治的宪法,不能缺。)
        auto_rule = False
        if not task_rule:
            titles: List[str] = []
            for it in (args.get("tasks") or [])[:8]:
                title = str((it or {}).get("title") if isinstance(it, dict) else it).strip()
                if title:
                    titles.append(title)
            task_rule = (
                f"本专班目标：{project}。"
                + (f"任务节点：{'、'.join(titles)}。" if titles else "任务节点见任务看板。")
                + "约束：只围绕本项目工作；每个节点完成后必须由项目主AI审核（不合格打回并写明原因）；"
                "全部节点完成并审核通过后，征询用户同意再归档关闭本专班。"
            )
            auto_rule = True
        # 组装频道配置：项目主AI 人设 + 任务RULE + 协作Agent + 技能
        persona: Dict[str, Any] = {}
        if lead:
            persona["agentSlug"] = lead  # _group_context 会用该全局 Agent 的人设
        else:
            persona["prompt"] = (
                f"你是本专班「{project}」的项目主AI（编排者）。职责仅限于：围绕本项目把子任务"
                "分配给合适的成员/AI、跟踪进度、按下方任务约束审核交付。具体节奏：\n"
                "① 每当某个成员/AI 完成一个任务节点，你要**逐个审核**：用 list_room_tasks 看清进度，"
                "用 update_task 把审核通过的节点标 done、把不合格的打回（status=doing 并写明原因）。\n"
                "② 始终盯住完成度（X/N）；卡点时汇报。\n"
                "③ 当**所有节点都已完成并审核通过**时，先用 ask_user_choice 征询用户是否归档关闭本专班，"
                "得到同意后调 archive_project 把项目存档、清理频道记忆、提示关闭频道。\n"
                "不要越出本项目范围去做无关的事。"
            )
        if skills:
            persona["skill_slugs"] = skills
        content: Dict[str, Any] = {"persona": persona, "agentSlugs": workers}
        if task_rule:
            content["taskRule"] = task_rule

        # —— 把知识库"调进"这个频道:解析成前缀化来源(user:/room:/platform),写进 kbScopes ——
        # 频道里所有人对话时都会检索这些来源(见 _group_context/_kb_retrieve),知识库真正"放进频道"。
        kb_raw = [str(k).strip() for k in (args.get("knowledge") or []) if str(k).strip()]
        kb_scopes: List[str] = []
        kb_labels: List[str] = []
        for k in kb_raw:
            low = k.lower()
            if low in ("owner", "self", "me", ctx.sender.lower()):
                scope = f"user:{ctx.sender}"
                label = "发起人个人库"
            elif low == "platform":
                scope = "platform"
                label = "平台共享库"
            elif k.startswith("!"):  # 已是 room_id
                scope = f"room:{k}"
                label = k
            else:  # 当作资料库频道名,解析成 room_id
                rid, err = self._resolve_room_by_name(k)
                if not rid:
                    kb_labels.append(f"「{k}」(没找到这个知识库频道,已跳过)")
                    continue
                scope = f"room:{rid}"
                label = k
            if scope not in kb_scopes:
                kb_scopes.append(scope)
                kb_labels.append(label)
        if kb_scopes:
            content["kbScopes"] = kb_scopes

        # M7：频道配置写入结果不能吞——写失败时人设/任务RULE/技能/kbScopes 全没生效，专班"裸奔"，
        # 绝不能在开班消息里照样宣称"已设RULE/已绑技能"。捕获成功与否，下面据实汇报。
        config_ok = True
        try:
            config_ok = bool(
                self.client.set_state_event(room_id, CHANNEL_CONFIG_EVENT_TYPE, content)
            )
        except Exception:
            logger.exception("写专班频道配置失败（M7）")
            config_ok = False

        # 方案B:把每个协作 Agent 的傀儡账号拉进专班——AI 同事真的出现在成员列表里,
        # 消息以它自己的名字发。失败(账号建不了/namespace 不符)退回方案A 人设应答,不阻断。
        joined_workers: List[str] = []
        if workers and self.ensure_worker_in_room:
            for w in workers:
                try:
                    if self.ensure_worker_in_room(room_id, w):
                        joined_workers.append(w)
                except Exception:
                    logger.debug("拉 AI 同事 %s 进专班失败(退回人设应答)", w, exc_info=True)

        # 派任务卡进这个专班（作用域 = 新频道）
        n_tasks = 0
        task_items = args.get("tasks") or []
        if isinstance(task_items, list) and task_items:
            # 解析每条截止时间 due → due_ts（同 create_tasks 路径）。
            for it in task_items:
                if isinstance(it, dict) and it.get("due"):
                    it["due_ts"] = _parse_due_to_ts(it.get("due"))
            try:
                from cosmac.db import session_scope
                from cosmac.db.task_repo import create_tasks

                with session_scope() as s:
                    created = create_tasks(
                        s, goal=project, items=task_items,
                        room_id=room_id, sender=ctx.sender,
                        space_id=ctx.space_id,   # 专班归到发起人当时所在的工作区
                    )
                    n_tasks = len(created)
                    # 收集「派给 AI 同事」的任务 id(在 session 内取,防 detached)——
                    # 下面交给自动执行器后台跑,让"分配给 Agent 的任务真的被执行"。
                    agent_task_ids = [
                        t.id for t in created
                        if t.executor_kind == "agent" and t.executor_ref
                    ]
            except Exception:
                logger.exception("派任务进专班失败")
                agent_task_ids = []
        else:
            agent_task_ids = []
        # AI 任务自动执行(负责人需求:派了就干,不等人 @):后台线程执行、不阻塞本轮回复。
        # 回调未注入/触发失败只影响"自动",看板照常,可在频道 @该 AI 手动要产出。
        auto_started = False
        if agent_task_ids and self.auto_execute_agent_tasks:
            try:
                self.auto_execute_agent_tasks(
                    room_id, ctx.sender, agent_task_ids, task_rule
                )
                auto_started = True
            except Exception:
                logger.exception("启动 AI 任务自动执行失败(看板不受影响)")

        # 开班消息发进频道（用**去重后的真实频道名**，别再说成撞名的那个）
        parts = [f"🗂 专班「{channel_name}」已组建。"]
        if channel_name != project:
            parts.append(f"(已有同名频道「{project}」，本专班改叫「{channel_name}」以区分。)")
        if invited:
            parts.append("已邀请：" + "、".join(invited))
        if failed:
            parts.append("未邀到（账号可能不存在）：" + "、".join(failed))
        if config_ok:
            # 只有频道配置真写进去了，才宣称人设/协作/知识库/RULE 已生效（M7）
            parts.append(f"项目主AI：{lead}" if lead else "项目主AI：内置编排人设")
            if workers:
                joined = set(joined_workers)
                parts.append("AI 协作：" + "、".join(
                    (w + "(已进频道)") if w in joined else w for w in workers
                ))
            if kb_labels:
                parts.append("已把知识库调进本频道（全体成员/AI 可检索）：" + "、".join(kb_labels))
            if task_rule:
                parts.append(
                    "已设本专班任务约束（RULE，自动生成的基础版——要调整随时告诉我）。"
                    if auto_rule else "已按你的要求设定本专班任务约束（RULE）。"
                )
        else:
            parts.append(
                "⚠️ 频道已建、成员已邀，但**频道配置写入失败**——人设/任务约束(RULE)/技能/知识库"
                "这次没能绑上。请对我说「给这个频道重新绑定…」重试，或到频道管理里手动设置。"
            )
        if missing:
            parts.append(
                "⚠️ 以下资源库里没有、未能绑定：" + "；".join(missing)
                + "。可让管理员到「管理后台 → 智能体/技能」先添加，再对我说重新绑定。"
            )
        if n_tasks:
            parts.append(f"已派 {n_tasks} 个任务，详见任务看板。")
        if auto_started:
            parts.append(
                f"🤖 其中 {len(agent_task_ids)} 个任务由 AI 同事执行——已自动开工，"
                "产出会陆续发到本频道并回填任务看板。"
            )
        # M7：开班消息发送包异常——此刻房间已建、配额已扣、任务已派，绝不能因发消息网络错让异常
        # 穿透到 execute()→模型收到"工具出错请重试"→撞名再建一个专班、任务重复派、配额二次扣。
        try:
            self.client.send_text(room_id, "\n".join(parts))
        except Exception:
            logger.debug("发送开班消息失败（忽略，专班已建成）", exc_info=True)

        # 让客户端把这个专班挂进用户**当前工作区**：bot 不在用户的 Space、没权限写 m.space.child；
        # 客户端在 Space 里有权限，收到这张信号卡会自动 join 新专班 + 挂到当前工作区，使其显示在频道树。
        try:
            self.client.send_card(
                ctx.room_id,
                f"专班「{channel_name}」已建好（room_id={room_id}）。",
                {"kind": "team_created", "team_room": room_id, "project": channel_name},
            )
        except Exception:
            logger.debug("发送 team_created 信号卡失败（忽略）", exc_info=True)

        # 回灌给模型（让它知道建好了、可继续编排/汇报；邀请失败也如实告知，别假装都拉进来了）
        # ⚠️ 用去重后的 channel_name——撞名时改了名,模型转述必须用真实频道名,别再说成撞名的那个。
        rename_note = f"（注意:已有同名频道，本专班实际叫「{channel_name}」）" if channel_name != project else ""
        summary = [f"已建好专班「{channel_name}」{rename_note}(room_id={room_id})，邀到 {len(invited)} 人"]
        if failed:
            summary.append(f"{len(failed)} 人没邀到（{('、'.join(failed))}，账号可能不存在）")
        if not config_ok:
            # M7：配置写失败——如实告知模型，避免它转述"已绑好人设/RULE/技能"误导用户；且明确
            # 房间已建、别再调 assemble_team 重建（会重复建房/重复派单/配额二次扣）。
            summary.append(
                "但频道配置(人设/RULE/技能/知识库)写入失败、未生效——请转告用户可说"
                f"「给频道 {room_id} 重新绑定…」重试，**切勿重新建专班**（房间已建好）"
            )
        else:
            summary.append(f"项目主AI={lead}" if lead else "项目主AI=内置编排人设")
            if workers:
                summary.append(f"协作Agent {len(workers)} 个")
            if skills:
                summary.append(f"技能 {len(skills)} 个")
            if kb_scopes:
                summary.append(f"知识库 {len(kb_scopes)} 个已绑进频道")
            summary.append(
                ("已设任务RULE（自动生成的基础版，可按需修改）" if auto_rule else "已按你的要求设任务RULE")
                if task_rule else "无任务RULE"
            )
        summary.append(f"派 {n_tasks} 个任务" if n_tasks else "暂未派任务")
        if auto_started:
            summary.append(
                f"其中 {len(agent_task_ids)} 个派给 AI 同事的任务已自动开始执行"
                "(产出稍后陆续发进专班、回填看板——转述时告诉用户不用手动催)"
            )
        if missing:
            summary.append(
                "⚠️ 以下资源库里没有、未绑定：" + "；".join(missing)
                + "（请如实转告用户：可到管理后台→智能体/技能添加后再让我补绑）"
            )
        return "；".join(summary) + "。"

    def _record_workflow_run(
        self, slug, platform, ctx, user_input, result, source_key: str = ""
    ) -> None:
        """尽力把运行记录落库；DB 不可用就跳过（不影响已拿到的结果）。

        ``source_key``：必须与本次运行 _reserve_workflow_source 用的键**完全一致**（同步后台路径
        传 ``event:<id>:ai:<slug>``），record_run 才能命中并结清那条 queued 占位（#5）。不传则按
        无来源键处理（直接插一行，不做去重）。
        """
        try:
            from cosmac.db import session_scope
            from cosmac.db.wf_repo import record_run

            with session_scope() as s:
                record_run(
                    s, slug=slug, platform=platform, room_id=ctx.room_id,
                    sender=ctx.sender, user_input=user_input, result=result,
                    source_key=source_key,
                )
        except Exception:
            # 运行记录丢失不影响已拿到的结果，但要留痕，否则"为什么没有运行记录"无从排查。
            logger.debug("登记工作流运行记录失败（忽略）", exc_info=True)

    def _consume_quota(self, ctx: ToolContext, tool_name: str) -> None:
        """在工具**成功路径**上消费配额（bot 注入 quota_consume 时才生效）。绝不抛异常。"""
        if self.quota_consume is None:
            return
        try:
            self.quota_consume(ctx.sender, tool_name)
        except Exception:
            logger.debug("配额消费失败（忽略）：%s", tool_name, exc_info=True)

    def _reserve_workflow_source(
        self, source_key: str, slug: str, platform: str, ctx: ToolContext, user_input: str
    ) -> bool:
        """提交外部工作流前先登记来源事件；新登记返回 True，已存在返回 False。"""
        try:
            from cosmac.db import session_scope
            from cosmac.db.wf_repo import create_pending, find_by_source_key

            with session_scope() as s:
                if find_by_source_key(s, source_key) is not None:
                    return False
                create_pending(
                    s, slug=slug, platform=platform, room_id=ctx.room_id,
                    sender=ctx.sender, user_input=user_input, token="",
                    source_key=source_key,
                )
                return True
        except Exception:
            # DB 不可用时宁可继续执行（保持旧可用性），只失去重放幂等。
            return True

    def _release_workflow_source(self, source_key: str) -> None:
        """提交线程池失败时回滚来源预约（删尚未提交的 queued 占位）。DB 不可用则忽略。"""
        try:
            from cosmac.db import session_scope
            from cosmac.db.wf_repo import release_pending_source

            with session_scope() as s:
                release_pending_source(s, source_key)
        except Exception:
            # 回滚失败只会让该来源在遗孤回收前不可重试，不影响当前响应；留痕即可。
            logger.debug("回滚工作流来源预约失败（忽略）", exc_info=True)
