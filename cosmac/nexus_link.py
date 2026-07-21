"""实例 → GuDuu Nexus 母舰的回连（模块6 P1③：心跳上报）。

每个 GuDuu OS 实例（含主站自己=实例#0）定期向母舰上报心跳：
版本号 + 运营统计（注册用户数 / 今日消息量），母舰回传 token 钱包余额。
这是大屏「实时树状图 / 增长数据」的数据来源之一（另一来源是 LLM 网关计量）。

启用条件：环境变量 ``COSMAC_NEXUS_URL`` 与 ``COSMAC_OEM_KEY`` **都**配置。
缺任一个 = 完全静默不启动——本地开发、未接入 OEM 体系的部署零影响。

统计口径（P1，诚实优先，不伪造）：
    users          注册用户总数（经 Synapse admin API；需 COSMAC_ADMIN_TOKEN
                   是真实的服务器管理员 access token，拿不到就不报这项）
    messages_today 今日 bot 亲眼所见的消息条数（appservice 推送计数，日切归零；
                   进程重启会从 0 重计——心跳是趋势数据，可接受）
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

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


def get_last_balance() -> Optional[int]:
    """最近一次心跳回传的 token 余额（未上报过返回 None）。"""
    return _last_balance


def _users_count(hs_url: str) -> Optional[int]:
    """注册用户总数：/_synapse/admin/v2/users 的 total 字段。

    需要 COSMAC_ADMIN_TOKEN 是真实的服务器管理员 access token（发行版由
    bootstrap 登录 admin 换取并写入 .env）。任何失败返回 None——统计缺项
    好过伪造数字。
    """
    token = _env("ADMIN_TOKEN")
    if not token:
        return None
    try:
        r = requests.get(
            f"{hs_url.rstrip('/')}/_synapse/admin/v2/users",
            params={"from": 0, "limit": 1},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if r.ok:
            total = r.json().get("total")
            return int(total) if total is not None else None
    except Exception:
        pass
    return None


def build_stats(config: CosmacConfig) -> Dict[str, Any]:
    """组一次心跳的 stats 载荷（只放拿得到的真实数据）。"""
    stats: Dict[str, Any] = {"messages_today": _messages_today()}
    users = _users_count(config.homeserver_url)
    if users is not None:
        stats["users"] = users
    return stats


def beat(config: CosmacConfig) -> bool:
    """打一次心跳。成功返回 True 并更新余额缓存；失败返回 False（调用方节流告警）。"""
    global _last_balance
    try:
        r = requests.post(
            f"{_env('NEXUS_URL').rstrip('/')}/nexus/heartbeat",
            json={
                "key": _env("OEM_KEY"),
                "version": cosmac.__version__,
                "stats": build_stats(config),
            },
            timeout=15,
        )
        if r.ok:
            data = r.json()
            _last_balance = int(data.get("balance_tokens", 0))
            return True
        logger.warning("Nexus 心跳被拒：HTTP %s %s", r.status_code, r.text[:120])
    except requests.RequestException as e:
        logger.warning("Nexus 心跳失败（网络）：%s", e)
    return False


def start(config: CosmacConfig) -> None:
    """启动心跳后台线程（daemon）。未接入 OEM 体系时安静返回。"""
    if not enabled():
        logger.info("未配置 COSMAC_NEXUS_URL/COSMAC_OEM_KEY，跳过 Nexus 心跳（独立模式）")
        return

    def _loop() -> None:
        time.sleep(_FIRST_BEAT_DELAY_S)
        while True:
            ok = beat(config)
            if ok and _last_balance is not None and _last_balance <= 0:
                # 余额耗尽：AI 已被网关断供。日志大声说，后台横幅是后续 UI 活。
                logger.warning(
                    "⚠️ token 钱包余额已耗尽（%s）——AI 服务已暂停，请充值恢复",
                    _last_balance,
                )
            time.sleep(_INTERVAL_S)

    threading.Thread(target=_loop, name="nexus-heartbeat", daemon=True).start()
    logger.info("Nexus 心跳已启动（每 %s 秒 → %s）", _INTERVAL_S, _env("NEXUS_URL"))
