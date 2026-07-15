"""会员等级（账号权限分层）—— 定义 + 校验 + 控制室读写。

这是什么
--------
在「服务器管理员」（Synapse 原生 admin 标志，管后台用）之外，给**普通用户**再叠一层
**会员身份**：免费 / 付费 / 创作者。两套是**正交**的——一个人既可以是服务器管理员，
又可以是任意会员等级（管理员身份 ≠ 会员身份，见 CLAUDE.md 路线图「账号权限」决策）。

为什么放这里
------------
- **枚举/标签/校验**是纯逻辑，前后端都要用同一套口径，集中在这一处避免飘移。
- **存储**走控制室的单用户 ``cosmac.member`` state event，旧 ``cosmac.members`` 只读兼容
  （权威数据、用户不可自改、只有管理员/bot 能写）。这里提供 :class:`MembersStore`，
  把「读当前 map / 查某人等级 / 授予 / 撤销」收口成几个方法，供 bot 调用。

谁来写
------
1. **管理后台**（管理员浏览器）：手动调整——直接走 Matrix 写 state event（前端 client.ts）。
2. **未来模块4（交易系统）支付成功**：服务端调 :meth:`MembersStore.grant` —— 这就是本期
   预留给「购买获得会员」的服务端接口。本期不接真实支付，只把接口和数据模型立起来。

注意：本模块只依赖 MatrixClient 的 state 读写方法，不引入额外依赖，方便单测注入假 client。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from cosmac.config import GATING_EVENT_TYPE, MEMBER_EVENT_TYPE, MEMBERS_EVENT_TYPE

logger = logging.getLogger("cosmac.members")

# —— 会员等级枚举（slug 是机器用的稳定标识，绝不改；label 是给人看的中文，可随品牌改）——
TIER_FREE = "free"        # 免费会员（默认；未在 cosmac.members 里列出的用户都算这个）
TIER_PAID = "paid"        # 付费会员（购买/管理员授予）
TIER_CREATOR = "creator"  # 创作者会员（购买/管理员授予；面向内容创作者的身份）

# 默认等级：任何没有显式记录的用户都视为免费会员。
DEFAULT_TIER = TIER_FREE

# 等级目录：slug → 中文标签 + level（数值仅用于「至少 X 级」这类比较；不代表创作者一定
# 比付费"高级"，只是给门控一个可排序的口径）。顺序即前端下拉展示顺序。
MEMBER_TIERS: List[Dict[str, Any]] = [
    {"slug": TIER_FREE, "label": "免费会员", "level": 0},
    {"slug": TIER_PAID, "label": "付费会员", "level": 10},
    {"slug": TIER_CREATOR, "label": "创作者会员", "level": 20},
]

# 便捷映射（由上面的目录派生，避免两处手写不一致）
_TIER_BY_SLUG: Dict[str, Dict[str, Any]] = {t["slug"]: t for t in MEMBER_TIERS}


def is_valid_tier(tier: str) -> bool:
    """tier 是否是已知等级 slug。"""
    return tier in _TIER_BY_SLUG


def normalize_tier(tier: Optional[str]) -> str:
    """把任意输入规整成合法等级 slug；空/未知一律回落到默认（免费）。

    脏数据兜底：控制室 state event 是外部可写的，读出来的 tier 不可信，统一过这一关。
    """
    t = (tier or "").strip()
    return t if t in _TIER_BY_SLUG else DEFAULT_TIER


def tier_label(tier: Optional[str]) -> str:
    """等级 slug → 中文标签（未知回落到「免费会员」）。"""
    return _TIER_BY_SLUG[normalize_tier(tier)]["label"]


def tier_level(tier: Optional[str]) -> int:
    """等级 slug → 数值档位（供门控做「至少付费」这类比较）。"""
    return int(_TIER_BY_SLUG[normalize_tier(tier)]["level"])


def _as_int(v: Any, default: int = 0) -> int:
    """把可能脏的值安全转 int；非法回退 default。

    会员数据存在控制室 state event（外部可写、不可信），``expires_ts`` 完全可能是非数字字符串。
    凡是读它做 int 转换的地方都走这里，避免单条脏数据让整批读取抛异常（被外层吞成"全员免费"）。
    """
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def active_tier(rec: Optional[Dict[str, Any]], now_ts: Optional[int] = None) -> str:
    """一条会员记录**当前生效**的等级 slug：到期(expires_ts>0 且已过)→回落免费（订阅制）。

    rec 形如 {"tier","expires_ts",...}；None/无 tier → 免费。``expires_ts`` 为 0/缺省 = 永久。
    """
    if not isinstance(rec, dict):
        return DEFAULT_TIER
    tier = normalize_tier(rec.get("tier"))
    if tier == DEFAULT_TIER:
        return DEFAULT_TIER
    exp = _as_int(rec.get("expires_ts"))
    now = int(now_ts if now_ts is not None else time.time())
    if exp and now >= exp:
        return DEFAULT_TIER  # 已到期 → 失效回落免费
    return tier


def member_state_key(user_id: str) -> str:
    """单用户会员事件 ``cosmac.member`` 的 state_key。

    **不能直接拿 user_id 当 state_key**：Matrix 规定 state_key 以 ``@`` 开头的事件**只有该
    用户本人能写**（否则 403 "You are not allowed to set others state"）——这会拦死 bot/管理员
    给**别人**开会员。故去掉开头的 ``@``（``@alice:host`` → ``alice:host``）：既不触发该规则、
    又与 user_id 一一对应。真实 user_id 另存进 content.uid，读取以 content.uid 为准。
    """
    return user_id[1:] if user_id.startswith("@") else user_id


def parse_members(content: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """把 ``cosmac.members`` state event 的内容解析成 {user_id: {tier, source, updated_ts}}。

    强校验 + 兜脏数据（state event 外部可写，绝不信任）：
      - 只收 ``members`` 是 dict 的；
      - key 必须是 ``@..:..`` 形状的 user_id（粗判，挡明显垃圾）；
      - tier 经 normalize_tier 规整；**等于默认(免费)的直接丢弃**——免费是隐含默认，
        不必显式存，也保证 map 里只有"非免费"的覆盖。
    """
    out: Dict[str, Dict[str, Any]] = {}
    if not isinstance(content, dict):
        return out
    members = content.get("members")
    if not isinstance(members, dict):
        return out
    for uid, rec in members.items():
        if not isinstance(uid, str) or not uid.startswith("@") or ":" not in uid:
            continue
        rec = rec if isinstance(rec, dict) else {}
        tier = normalize_tier(rec.get("tier"))
        if tier == DEFAULT_TIER:
            continue  # 免费是默认，不显式保留
        out[uid] = {
            "tier": tier,
            "source": str(rec.get("source") or "admin"),
            "updated_ts": rec.get("updated_ts"),
        }
    return out


class MembersStore:
    """控制室会员等级的薄封装：读当前 map / 查等级 / 授予 / 撤销。

    新数据按用户拆成 ``cosmac.member`` state event，state_key 是 user_id；旧版
    ``cosmac.members`` 聚合事件只读兼容。单用户写入既不会覆盖其他用户，也不受整表容量限制。

    构造参数：
        client: 提供 resolve_alias/get_state_event/get_room_state/set_state_event 的 MatrixClient。
        control_room_alias:   控制室别名（#cosmac-ctrl:<server>）。
    """

    def __init__(self, client: Any, control_room_alias: str):
        self._client = client
        self._alias = control_room_alias
        # 会员记录 60 秒缓存(user_id → (记录或 None, 时间戳)):get_tier 被资源可见性/
        # 门控/商城目录逐条调用,每次一趟控制室 state HTTP 读太贵(评审 #9)。
        # grant 写入时主动失效;后台直改 state 的场景由 bot 收到 state 事件时清整表。
        self._rec_cache: Dict[str, Tuple[Optional[Dict[str, Any]], float]] = {}

    def invalidate_cache(self, user_id: str = "") -> None:
        """会员记录缓存失效:传 user_id 清单人,不传清整表(state 直改场景)。"""
        if user_id:
            self._rec_cache.pop(user_id, None)
        else:
            self._rec_cache.clear()

    def _ctrl_room(self) -> Optional[str]:
        """解析控制室 room_id；解析不到返回 None（控制室还没建）。"""
        try:
            return self._client.resolve_alias(self._alias)
        except Exception as e:
            logger.debug("解析控制室别名失败（会员）：%s", e)
            return None

    def get_all(self) -> Dict[str, Dict[str, Any]]:
        """合并读取新旧会员数据；失败/无数据返回空，供列表展示与命令查询。"""
        room = self._ctrl_room()
        if not room:
            return {}
        try:
            # 先读旧聚合数据，再让新单用户事件覆盖；free 是 tombstone，用来撤销旧记录。
            legacy = parse_members(
                self._client.get_state_event(room, MEMBERS_EVENT_TYPE)
            )
            for ev in self._client.get_room_state(room):
                if not isinstance(ev, dict) or ev.get("type") != MEMBER_EVENT_TYPE:
                    continue
                content = ev.get("content")
                content = content if isinstance(content, dict) else {}
                # 真实 user_id 以 content.uid 为准；兼容旧数据（state_key 直接是去 @ 的 id）
                uid = content.get("uid")
                if not isinstance(uid, str) or not uid:
                    sk = ev.get("state_key") or ""
                    uid = sk if sk.startswith("@") else ("@" + sk if sk else "")
                if not uid.startswith("@") or ":" not in uid:
                    continue
                # 到期的按免费处理(回落)→ 与 free tombstone 一样从 map 里移除
                tier = active_tier(content)
                if tier == DEFAULT_TIER:
                    legacy.pop(uid, None)
                else:
                    legacy[uid] = {
                        "tier": tier,
                        "source": str(content.get("source") or "admin"),
                        "updated_ts": content.get("updated_ts"),
                        "expires_ts": _as_int(content.get("expires_ts")),
                    }
            return legacy
        except Exception as e:
            logger.debug("读取会员等级失败（忽略）：%s", e)
            return {}

    def get_tier(self, user_id: str) -> str:
        """查某用户**当前生效**的等级；优先单用户事件，缺失时回退旧聚合数据。到期自动回落免费。"""
        rec = self.get_record(user_id)
        return active_tier(rec)

    def get_record(self, user_id: str) -> Optional[Dict[str, Any]]:
        """读某用户的原始会员记录 {tier, source, updated_ts, expires_ts}；无记录返回 None。

        供续费逻辑用（要拿到当前 expires_ts 才能"在原到期日上顺延"）。读失败返回 None
        → 上层按免费/无记录处理（fail-closed，不误授予）。
        带 60 秒缓存(评审 #9,含"无记录"也缓存);grant/收到会员 state 事件时失效。
        """
        cached = self._rec_cache.get(user_id)
        if cached and time.monotonic() - cached[1] < 60:
            return cached[0]
        rec = self._get_record_uncached(user_id)
        self._rec_cache[user_id] = (rec, time.monotonic())
        if len(self._rec_cache) > 10000:
            self._rec_cache.clear()
        return rec

    def _get_record_uncached(self, user_id: str) -> Optional[Dict[str, Any]]:
        """get_record 的真实读取体(缓存壳见上)。"""
        room = self._ctrl_room()
        if not room:
            return None
        try:
            current = self._client.get_state_event(
                room, MEMBER_EVENT_TYPE, member_state_key(user_id)
            )
            if current is not None:
                t = normalize_tier(current.get("tier"))
                return None if t == DEFAULT_TIER else {  # free 是 tombstone=无有效记录
                    "tier": t,
                    "source": str(current.get("source") or "admin"),
                    "updated_ts": current.get("updated_ts"),
                    "expires_ts": _as_int(current.get("expires_ts")),
                }
            legacy = parse_members(
                self._client.get_state_event(room, MEMBERS_EVENT_TYPE)
            )
            return legacy.get(user_id)
        except Exception as e:
            # 会员读失败按无记录处理，使付费能力自然 fail-closed；不会误授予权限。
            logger.warning("读取用户会员记录失败，按免费处理 user=%s: %s", user_id, e)
            return None

    def grant(
        self,
        user_id: str,
        tier: str,
        source: str = "admin",
        now_ts: Optional[int] = None,
        expires_ts: Optional[int] = None,
    ) -> bool:
        """授予/调整某用户的会员等级（**模块4支付成功的服务端入口**，也用于 bot 命令）。

        - tier 经校验：非法直接拒（返回 False），不写脏数据进控制室。
        - tier == 免费 写入 tombstone；既表示撤销，也能覆盖旧聚合事件里的历史等级。
        - source 记录来源（"admin"/"purchase"/…），便于以后审计「这级是怎么来的」。
        - expires_ts：会员到期 unix 秒（订阅制）。``None``/``0`` = 永久（管理员授予默认永久）；
          到期后查等级自动回落免费（见 :func:`active_tier`）。
        成功写入返回 True；控制室不存在/写失败返回 False（调用方据此提示）。
        """
        if not is_valid_tier(tier):
            logger.warning("授予会员失败：未知等级 %r", tier)
            return False
        room = self._ctrl_room()
        if not room:
            logger.warning("授予会员失败：控制室不存在（还没建）")
            return False
        if not user_id.startswith("@") or ":" not in user_id:
            logger.warning("授予会员失败：非法 user_id %r", user_id)
            return False
        content: Dict[str, Any] = {
            "uid": user_id,  # 真实 user_id 存这里（state_key 去了 @、不能反推冒号歧义）
            "tier": tier,
            "source": source,
            "updated_ts": int(now_ts if now_ts is not None else time.time()),
            "expires_ts": int(expires_ts) if expires_ts else 0,  # 0 = 永久
        }
        try:
            # state_key 用去 @ 的形式，绕开 Matrix"@开头只能本人写"的限制（见 member_state_key）
            ok = bool(
                self._client.set_state_event(
                    room, MEMBER_EVENT_TYPE, content, member_state_key(user_id)
                )
            )
            if ok:
                self.invalidate_cache(user_id)  # 等级变了,60 秒缓存立即失效(开通即生效)
            return ok
        except Exception:
            logger.exception("授予会员等级失败 user=%s tier=%s", user_id, tier)
            return False

    def revoke(self, user_id: str) -> bool:
        """撤销某用户的会员（回落到免费）。等价 grant(user_id, free)。"""
        return self.grant(user_id, TIER_FREE)


# =====================================================================
#  功能门控（按会员等级限制能力）
# =====================================================================
#
# 设计：管理员在后台把「每个能力」配一个**最低门槛**，bot 在执行点**服务端强制**。
# 门槛是一条 4 级阶梯：免费 < 付费 < 创作者 < 仅管理员。
#   - tier 门槛（free/paid/creator）：用户会员等级 ≥ 门槛即放行；**平台管理员永远放行**
#     （staff 能用一切，免得给自己开会员）。
#   - 特殊门槛 admin（「仅管理员」）：只有平台管理员放行（用于共享付费凭据这类高危能力）。
# 默认未配置的能力取 GATE_CATALOG 里各自的 default：多数 free（不限制），保证零回归。

GATE_ADMIN = "admin"  # 特殊门槛：仅平台管理员

# 门槛阶梯的排序值（越大越严）。tier 部分与 tier_level 对齐；admin 居顶。
_GATE_RANK: Dict[str, int] = {
    TIER_FREE: 0,
    TIER_PAID: 10,
    TIER_CREATOR: 20,
    GATE_ADMIN: 1000,
}

# 后台门控下拉可选的「门槛」目录（slug + 标签）。即上面阶梯的人类可读版。
GATE_LEVELS: List[Dict[str, str]] = [
    {"slug": TIER_FREE, "label": "免费（不限制）"},
    {"slug": TIER_PAID, "label": "付费会员及以上"},
    {"slug": TIER_CREATOR, "label": "创作者会员"},
    {"slug": GATE_ADMIN, "label": "仅平台管理员"},
]

# 可门控的能力目录：key=能力标识（与 bot 执行点一致，**稳定别改**），label=后台显示，
# default=未配置时的默认门槛。**新增功能就往这里加一条**（前后端各加，见 client.ts GATE_CATALOG）。
GATE_CATALOG: List[Dict[str, str]] = [
    # group：分类（后台「会员权限」按它分组展示）。新增功能往对应分类加一条（前后端各一份）。
    {"key": "ai_chat", "label": "基础 AI 对话（@中枢AI / 私聊回复）", "default": TIER_FREE, "group": "AI 对话与检索"},
    {"key": "knowledge", "label": "知识库（RAG 检索 + 知识命令）", "default": TIER_FREE, "group": "AI 对话与检索"},
    {"key": "memory", "label": "长期记忆（AI 跨多轮/跨天记得你）", "default": TIER_PAID, "group": "AI 对话与检索"},
    {"key": "web_search", "label": "联网搜索（外部 API、共享凭据有成本）", "default": TIER_PAID, "group": "AI 对话与检索"},
    {"key": "custom_skill", "label": "自定义技能（用聊天命令建/管理自己的技能）", "default": TIER_PAID, "group": "AI 对话与检索"},
    {"key": "create_room", "label": "建群 / 频道", "default": TIER_FREE, "group": "任务编排与协作"},
    {"key": "task_board", "label": "AI 拆解任务到看板", "default": TIER_PAID, "group": "任务编排与协作"},
    {"key": "assemble_team", "label": "一键建专班（AI 组队 + 派单）", "default": TIER_PAID, "group": "任务编排与协作"},
    {"key": "people_manage", "label": "个人协作人名册（给常合作的人加能力，供 AI 派单）", "default": TIER_PAID, "group": "任务编排与协作"},
    {"key": "workflow_run", "label": "跑工作流（外部/付费、共享凭据）", "default": GATE_ADMIN, "group": "自动化"},
    {"key": "doc_read", "label": "图文教程（查看平台图文内容）", "default": TIER_PAID, "group": "内容"},
    # 人事/员工（HR）数据查询：涉及薪资、绩效等敏感信息，默认仅平台管理员可查（可在后台调低）。
    {"key": "hr_data", "label": "人事数据查询（花名册/薪酬/绩效/考勤·敏感）", "default": GATE_ADMIN, "group": "数据智能"},
    # 销售业绩数据查询：销售额/签单/完成率等经营敏感信息，默认仅平台管理员可查。
    {"key": "sales_data", "label": "销售业绩查询（销售额/签单/完成率·敏感）", "default": GATE_ADMIN, "group": "数据智能"},
]

# 由目录派生的便捷映射
_GATE_DEFAULTS: Dict[str, str] = {g["key"]: g["default"] for g in GATE_CATALOG}
_GATE_LABELS: Dict[str, str] = {g["key"]: g["label"] for g in GATE_CATALOG}
_GATE_LEVEL_SLUGS = {lv["slug"] for lv in GATE_LEVELS}


def gate_rank(value: Optional[str]) -> int:
    """门槛 slug → 排序值（未知按免费=0）。"""
    return _GATE_RANK.get((value or "").strip(), 0)


def normalize_gate(value: Optional[str], default: str = TIER_FREE) -> str:
    """把门槛输入规整成合法 slug（free/paid/creator/admin）；非法回落到 default。"""
    v = (value or "").strip()
    return v if v in _GATE_LEVEL_SLUGS else default


def gate_capability_label(key: str) -> str:
    """能力 key → 中文标签（未知回落到 key 本身）。"""
    return _GATE_LABELS.get(key, key)


def parse_gates(content: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """解析 ``cosmac.gating`` 内容 → {能力key: 门槛slug}。只收已知能力 + 合法门槛，兜脏数据。"""
    out: Dict[str, str] = {}
    if not isinstance(content, dict):
        return out
    gates = content.get("gates")
    if not isinstance(gates, dict):
        return out
    for key, val in gates.items():
        if key in _GATE_DEFAULTS and isinstance(val, str) and val in _GATE_LEVEL_SLUGS:
            out[key] = val
    return out


class GatingStore:
    """控制室 ``cosmac.gating`` 的薄封装：读门控策略。

    读多写少：bot 频繁读（每条消息可能查几次），故带一个**短 TTL 缓存**避免每次打服务器；
    写由管理后台浏览器直接走 Matrix（bot 不写门控）。读失败保留上次成功值（不失效开放）。
    """

    def __init__(
        self,
        client: Any,
        control_room_alias: str,
        ttl: float = 15.0,
        retry_backoff: float = 5.0,
    ):
        """创建门控读取器。

        ``retry_backoff`` 是读取失败后的最短重试间隔。故障期间沿用上次成功配置；若从未
        成功读取，则返回全能力 ``admin`` 的保守策略，避免默认 free 造成越权。
        """
        self._client = client
        self._alias = control_room_alias
        self._ttl = ttl
        self._retry_backoff = retry_backoff
        self._cache: Dict[str, str] = {}
        self._cache_ts: float = float("-inf")
        self._next_retry_ts: float = float("-inf")

    def get_all(self) -> Dict[str, str]:
        """返回**合并默认后**的完整门控映射 {能力key: 门槛slug}（带 TTL 缓存）。"""
        now = time.monotonic()
        if now - self._cache_ts < self._ttl and self._cache:
            return self._cache
        if now < self._next_retry_ts:
            return self._cache or {key: GATE_ADMIN for key in _GATE_DEFAULTS}
        merged = dict(_GATE_DEFAULTS)  # 先铺默认
        try:
            room = self._client.resolve_alias(self._alias)
            if room:
                ev = self._client.get_state_event(room, GATING_EVENT_TYPE)
                merged.update(parse_gates(ev))
            self._cache = merged
            self._cache_ts = now
            self._next_retry_ts = float("-inf")
            return merged
        except Exception as e:
            # 失败本身不冒充成功缓存，但需要短退避，避免每条消息同时冲击故障中的 Synapse。
            self._next_retry_ts = now + self._retry_backoff
            if self._cache:
                logger.warning("读取门控策略失败，沿用上次成功值，稍后重试：%s", e)
            else:
                logger.warning(
                    "门控策略首次读取失败，临时收紧为仅管理员，稍后重试：%s", e
                )
            return self._cache or {key: GATE_ADMIN for key in _GATE_DEFAULTS}

    def warm(self) -> bool:
        """启动时预热一次；失败不阻断启动，但运行期会使用 fail-closed 策略。"""
        try:
            self.get_all()
            return bool(self._cache)
        except Exception:
            return False

    def required(self, capability: str) -> str:
        """某能力的最低门槛 slug（未在目录里的能力按免费=不限制）。"""
        return self.get_all().get(capability, _GATE_DEFAULTS.get(capability, TIER_FREE))
