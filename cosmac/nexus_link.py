"""实例 → GuDuu Nexus 母舰的回连（模块6 P1③：心跳上报）。

每个 GuDuu OS 实例（含主站自己=实例#0）定期向母舰上报心跳：
版本号 + 运营统计（人员构成 / 今日消息量），母舰回传 token 钱包余额。
这是大屏「实时树状图 / 增长数据」的数据来源之一（另一来源是 LLM 网关计量）。

启用条件：环境变量 ``COSMAC_NEXUS_URL`` 与 ``COSMAC_OEM_KEY`` **都**配置。
缺任一个 = 完全静默不启动——本地开发、未接入 OEM 体系的部署零影响。

统计口径（P1，诚实优先，不伪造）：
    users_total        Synapse 本地账号总数
    users_business     正常业务用户（排除管理员、AI、访客、停用和锁定）
    users_admin        正常服务器管理员
    users_ai           主 AI 与已注册的协作 AI 账号
    users_guest        正常访客账号
    users_deactivated  已停用账号
    users_locked       已锁定账号
                       （以上经 Synapse admin API 获取；需真实的
                       COSMAC_ADMIN_TOKEN，拿不到就不报人数）
    messages_today 今日 bot 亲眼所见的消息条数（appservice 推送计数，日切归零；
                   进程重启会从 0 重计——心跳是趋势数据，可接受）
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, Optional
from urllib.parse import quote

import requests

import cosmac
from cosmac.config import CosmacConfig, _env

logger = logging.getLogger(__name__)

# 心跳间隔：10 分钟（母舰在线判定阈值 15 分钟，见 nexus/fleet.py _ONLINE_MS）
_INTERVAL_S = 600
# 首跳延迟：等 bot 完成启动自检再报，避免抢启动期资源
_FIRST_BEAT_DELAY_S = 15

# —— 进程内计数器（线程安全；按天归零）——
_LOCK = threading.Lock()
_COUNTS: Dict[str, Any] = {"day": "", "messages": 0}

# 母舰最近一次回传的钱包余额（实例后台"余额快见底"提醒的数据源，负数=已透支）
_last_balance: Optional[int] = None
# 注册请求和 10 分钟心跳可能同时触发队列投递；一把锁避免同一行被重复并发提交。
_ATTR_SYNC_LOCK = threading.Lock()

# Bot 内部运营统计只允许这些已定义的整数字段进心跳。用白名单而不是
# 盲目合并 callback 返回值，避免以后内部统计意外带上用户标识或其他敏感字段。
_EXTRA_STAT_KEYS = (
    "members_total",
    "members_paid",
    "members_creator",
    "workflow_runs",
    "orders_paid",
    "channels_total",
    "spaces_total",
    "ai_rooms_total",
    "dm_rooms_total",
    "knowledge_bases_total",
    "kb_docs",
    "kb_chunks",
    "skills_available",
    "skills_custom_total",
    "skills_custom_enabled",
    "agents_available",
    "agents_custom_total",
    "agents_custom_enabled",
    "workflows_total",
    "workflows_enabled",
)
StatsProvider = Callable[[], Dict[str, Any]]


class ReferralError(Exception):
    """邀请链接无法由 Nexus 确认时的用户可读错误。"""


class LifetimeActivationError(Exception):
    """终身会员激活无法由 Nexus 确认时的用户可读错误。"""


def _today() -> str:
    return time.strftime("%Y-%m-%d")


def note_message() -> None:
    """记一条"bot 看到的用户消息"。由 appservice_bot 的事件处理入口调用。"""
    with _LOCK:
        day = _today()
        if _COUNTS["day"] != day:  # 跨天归零
            _COUNTS["day"] = day
            _COUNTS["messages"] = 0
        _COUNTS["messages"] += 1


def _messages_today() -> int:
    with _LOCK:
        return _COUNTS["messages"] if _COUNTS["day"] == _today() else 0


def enabled() -> bool:
    """是否接入了 OEM 体系（两项 env 齐备才算）。"""
    return bool(_env("NEXUS_URL")) and bool(_env("OEM_KEY"))


def referral_info(code: str) -> Dict[str, Any]:
    """向 Nexus 校验分享码并返回最小邀请方信息。

    带分享码的注册必须 fail-closed：母舰不可达或分享码无效时不继续建号，否则会生成
    无法确认归属的用户。普通不带分享码的直接注册不受影响。
    """
    normalized = (code or "").strip()
    if not normalized:
        raise ReferralError("邀请链接缺少分享码")
    if not enabled():
        raise ReferralError("当前实例尚未接入 OEM 邀请体系")
    try:
        response = requests.get(
            f"{_env('NEXUS_URL').rstrip('/')}/nexus/referral?code={quote(normalized)}",
            timeout=10,
        )
    except requests.RequestException as exc:
        raise ReferralError("邀请关系暂时无法确认，请稍后重试") from exc
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if not response.ok:
        raise ReferralError(str(payload.get("error") or "邀请链接已失效"))
    return dict(payload)


def activate_lifetime_membership(
    activation_code: str, user_id: str, device_id: str = ""
) -> Dict[str, Any]:
    """用宿主注入的 OEM KEY 代理兑换终身会员。

    前端只会提交终身码和自己的 Matrix 会话；节点 KEY 不进入浏览器。
    """
    code = (activation_code or "").strip().upper()
    if not code:
        raise LifetimeActivationError("请输入终身会员激活码")
    if not enabled():
        raise LifetimeActivationError("当前节点尚未接入 OEM 授权体系")
    try:
        response = requests.post(
            f"{_env('NEXUS_URL').rstrip('/')}/nexus/lifetime/activate",
            json={
                "key": _env("OEM_KEY"),
                "activation_code": code,
                "user_id": user_id,
                "device_kind": "node",
                "device_id": (device_id or "").strip()[:255],
            },
            timeout=15,
        )
    except requests.RequestException as exc:
        raise LifetimeActivationError("激活服务暂时不可用，请稍后重试") from exc
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if not response.ok:
        raise LifetimeActivationError(str(payload.get("error") or "终身会员激活失败"))
    return dict(payload)


def queue_user_attribution(user_id: str, referral_code: str) -> bool:
    """先把注册用户归属写入实例本地可靠队列。"""
    try:
        from cosmac.db import session_scope
        from cosmac.db.oem_attribution_repo import enqueue

        with session_scope() as session:
            return enqueue(
                session, user_id=user_id, referral_code=referral_code
            )
    except Exception:
        logger.exception("保存 OEM 用户归属失败 user_id=%s", user_id)
        return False


def sync_pending_attributions(limit: int = 50) -> int:
    """把本地待同步关系幂等投递到 Nexus，返回本轮成功数。"""
    if not enabled() or not _ATTR_SYNC_LOCK.acquire(blocking=False):
        return 0
    synced = 0
    try:
        from cosmac.db import session_scope
        from cosmac.db.oem_attribution_repo import mark_failed, mark_synced, pending

        with session_scope() as session:
            for row in pending(session, limit=limit):
                try:
                    response = requests.post(
                        f"{_env('NEXUS_URL').rstrip('/')}/nexus/user/attribution",
                        json={
                            "key": _env("OEM_KEY"),
                            "referral_code": row.referral_code,
                            "user_id": row.user_id,
                        },
                        timeout=10,
                    )
                    if response.ok:
                        mark_synced(row)
                        synced += 1
                    else:
                        try:
                            payload = response.json()
                        except ValueError:
                            payload = {}
                        mark_failed(
                            row,
                            str(payload.get("error") or f"HTTP {response.status_code}"),
                            # 429 是临时限频；其他 4xx 表示链接/实例/用户不一致，继续重试无益。
                            permanent=400 <= response.status_code < 500
                            and response.status_code != 429,
                        )
                except requests.RequestException as exc:
                    mark_failed(row, str(exc), permanent=False)
        return synced
    except Exception:
        logger.exception("同步 OEM 用户归属队列失败")
        return synced
    finally:
        _ATTR_SYNC_LOCK.release()


def sync_attributions_soon() -> None:
    """注册成功后后台立即投递一次，不让 HTTP 注册响应额外等待母舰网络。"""
    threading.Thread(
        target=sync_pending_attributions,
        name="nexus-attribution-sync",
        daemon=True,
    ).start()


def get_last_balance() -> Optional[int]:
    """最近一次心跳回传的 token 余额（未上报过返回 None）。"""
    return _last_balance


def _is_ai_account(user_id: str, bot_user_id: str) -> bool:
    """判断 Matrix 账号是否属于 GuDuu AI，只使用项目已有的确定规则。

    ``bot_user_id`` 是该节点主 AI 的完整 MXID；``guduu-ai-*`` 是项目在
    ``CosmacBot._worker_user_id`` 里统一生成的协作 AI 机器人账号。不根据
    显示名或邮箱猜测，避免把真人误统计成 AI。
    """
    normalized = str(user_id or "").strip().lower()
    master = str(bot_user_id or "").strip().lower()
    localpart = normalized.split(":", 1)[0]
    return bool(normalized and (normalized == master or localpart.startswith("@guduu-ai-")))


def _user_breakdown(config: CosmacConfig) -> Optional[Dict[str, int]]:
    """读取全部 Synapse 本地账号，返回互斥的人员构成统计。

    Synapse 列表端点是分页的，只读 ``total`` 无法区分管理员、AI 与
    真实用户，所以这里遍历每页。分类按“停用 → 锁定 → 访客 → AI →
    管理员 → 业务用户”的顺序只计一类，因此各分项之和严格等于
    ``users_total``。任一页失败就返回 ``None``，不向 Nexus 上报半截数据。
    """
    token = _env("ADMIN_TOKEN")
    if not token:
        return None
    counts = {
        "users_total": 0,
        "users_business": 0,
        "users_admin": 0,
        "users_ai": 0,
        "users_guest": 0,
        "users_deactivated": 0,
        "users_locked": 0,
    }
    offset = 0
    page_size = 500
    try:
        while True:
            response = requests.get(
                f"{config.homeserver_url.rstrip('/')}/_synapse/admin/v2/users",
                params={"from": offset, "limit": page_size},
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            if not response.ok:
                return None
            payload = response.json()
            users = payload.get("users")
            total = payload.get("total")
            if not isinstance(users, list) or total is None:
                return None
            expected_total = int(total)
            for user in users:
                if not isinstance(user, dict):
                    return None
                counts["users_total"] += 1
                if bool(user.get("deactivated")):
                    counts["users_deactivated"] += 1
                elif bool(user.get("locked")):
                    counts["users_locked"] += 1
                elif bool(user.get("is_guest")):
                    counts["users_guest"] += 1
                elif _is_ai_account(str(user.get("name") or ""), config.bot_user_id):
                    counts["users_ai"] += 1
                elif bool(user.get("admin")):
                    counts["users_admin"] += 1
                else:
                    counts["users_business"] += 1
            offset += len(users)
            if offset >= expected_total:
                # total 与实际遍历数必须一致，避免并发注册或接口异常
                # 时把一组无法对账的数字传到管理后台。
                return counts if counts["users_total"] == expected_total else None
            if not users:
                return None
    except Exception:
        return None


def _room_count(config: CosmacConfig) -> Optional[int]:
    """返回 Synapse 当前房间总数，拿不到则返回 ``None``。

    这是“聊天房间数”而不是“历史消息总数”。Synapse Admin API 能直接
    返回 ``total_rooms``，无需把房间或消息详情上传 Nexus。
    """
    token = _env("ADMIN_TOKEN")
    if not token:
        return None
    try:
        response = requests.get(
            f"{config.homeserver_url.rstrip('/')}/_synapse/admin/v1/rooms",
            params={"from": 0, "limit": 1},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if not response.ok:
            return None
        total = response.json().get("total_rooms")
        return int(total) if total is not None else None
    except Exception:
        return None


def build_stats(
    config: CosmacConfig,
    extra_stats_provider: Optional[StatsProvider] = None,
) -> Dict[str, Any]:
    """组一次心跳的 stats 载荷（只放拿得到的真实聚合数据）。

    ``extra_stats_provider`` 由正在运行的 ``CosmacBot`` 注入，用于读会员、
    工作流、订单和知识库数量。回调失败只使这些字段缺省，不影响
    节点版本、账号和消息心跳。
    """
    stats: Dict[str, Any] = {"messages_today": _messages_today()}
    users = _user_breakdown(config)
    if users is not None:
        stats.update(users)
    rooms = _room_count(config)
    if rooms is not None:
        stats["rooms_total"] = max(0, rooms)
    if extra_stats_provider is not None:
        try:
            extra = extra_stats_provider()
            for key in _EXTRA_STAT_KEYS:
                if key not in extra or isinstance(extra[key], bool):
                    continue
                value = int(extra[key])
                if value >= 0:
                    stats[key] = value
        except Exception:
            logger.debug("Nexus 心跳读取 Bot 运营统计失败（忽略该组字段）", exc_info=True)
    return stats


def beat(
    config: CosmacConfig,
    extra_stats_provider: Optional[StatsProvider] = None,
) -> bool:
    """打一次心跳。成功返回 True 并更新余额缓存；失败返回 False（调用方节流告警）。"""
    global _last_balance
    try:
        r = requests.post(
            f"{_env('NEXUS_URL').rstrip('/')}/nexus/heartbeat",
            json={
                "key": _env("OEM_KEY"),
                "version": cosmac.__version__,
                "stats": build_stats(config, extra_stats_provider),
            },
            timeout=15,
        )
        if r.ok:
            data = r.json()
            _last_balance = int(data.get("balance_tokens", 0))
            # Nexus 心跳已用 OEM KEY 确认了实例身份。持久化返回的
            # instance_id，同时自动修复旧安装器未写激活文件的节点。
            try:
                from cosmac import node_activation

                node_activation.record_instance_id(data.get("instance_id"))
            except (OSError, ValueError):
                logger.warning("Nexus 心跳成功，但节点身份持久化失败", exc_info=True)
            return True
        logger.warning("Nexus 心跳被拒：HTTP %s %s", r.status_code, r.text[:120])
    except requests.RequestException as e:
        logger.warning("Nexus 心跳失败（网络）：%s", e)
    return False


def start(
    config: CosmacConfig,
    extra_stats_provider: Optional[StatsProvider] = None,
) -> None:
    """启动心跳后台线程（daemon）。未接入 OEM 体系时安静返回。"""
    if not enabled():
        logger.info("未配置 COSMAC_NEXUS_URL/COSMAC_OEM_KEY，跳过 Nexus 心跳（独立模式）")
        return

    def _loop() -> None:
        time.sleep(_FIRST_BEAT_DELAY_S)
        while True:
            ok = beat(config, extra_stats_provider)
            # 无论心跳本身成功与否都尝试队列：二者端点可能受不同的瞬时故障影响。
            sync_pending_attributions()
            if ok and _last_balance is not None and _last_balance <= 0:
                # 余额耗尽：AI 已被网关断供。日志大声说，后台横幅是后续 UI 活。
                logger.warning(
                    "⚠️ token 钱包余额已耗尽（%s）——AI 服务已暂停，请充值恢复",
                    _last_balance,
                )
            time.sleep(_INTERVAL_S)

    threading.Thread(target=_loop, name="nexus-heartbeat", daemon=True).start()
    logger.info("Nexus 心跳已启动（每 %s 秒 → %s）", _INTERVAL_S, _env("NEXUS_URL"))
