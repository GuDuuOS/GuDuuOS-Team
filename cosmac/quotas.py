"""用量配额（模块4 变现第二步）—— 给每个计量维度按会员等级配上限。

与「功能门控」(gating, members.py) 互补：门控管"**能不能用**某功能"，配额管"**能用多少**"。
免费版撞墙(用完额度)就提示升级——这才是订阅的主要付费驱动。

- **配额上限**：admin 在后台配，存控制室 `cosmac.quotas` state event（同 gating），-1=不限。
- **用量计数**：进 cosmac DB（`cosmac_usage`，按 user+metric+周期键累计；见 db/quota_repo）。
- **两类指标**：rate（按天/月累计，如每天 AI 对话条数）/ total（当前存量，如知识库文档数）。

平台管理员永远不受配额限制（同门控）。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from cosmac.config import QUOTAS_EVENT_TYPE
from cosmac.members import MEMBER_TIERS

logger = logging.getLogger("cosmac.quotas")

# 计量维度目录。limit -1 = 不限。新增计量项往这里加一条（前后端各一份，见 client.ts）。
#   track=usage  → 走 cosmac_usage 计数表，period: day/month/total(单调累计)。
#   track=existing → 直接数现有实体行（如知识库文档数），period 仅用于"是否分周期"（这里 total）。
QUOTA_CATALOG: List[Dict[str, Any]] = [
    {
        "key": "ai_msg_daily", "label": "AI 对话（每天）", "unit": "条/天",
        "track": "usage", "period": "day", "group": "AI",
        "defaults": {"free": 30, "paid": -1, "creator": -1},
    },
    {
        # 存储空间(负责人定):每个账号的附件/媒体 + 个人知识库字节数,按会员等级给上限。
        # 归属口径:Synapse 媒体(上传者=本人) + 个人库(SCOPE_USER)。聊天文字/共享频道库不计
        # (共享资源无法归属个人;文字体积可忽略)。track=existing:实时算存量,不走计数表。
        "key": "storage_mb", "label": "存储空间", "unit": "MB",
        "track": "existing", "period": "total", "group": "存储",
        "defaults": {"free": 100, "paid": 1024, "creator": 5120},
    },
    {
        "key": "kb_docs", "label": "知识库文档数", "unit": "篇",
        "track": "existing", "period": "total", "group": "知识库",
        "defaults": {"free": 5, "paid": 200, "creator": -1},
    },
    {
        "key": "teams", "label": "专班数（一键建专班）", "unit": "个",
        "track": "usage", "period": "total", "group": "任务编排",
        "defaults": {"free": 1, "paid": 20, "creator": -1},
    },
    {
        "key": "workflow_runs", "label": "工作流运行（每月）", "unit": "次/月",
        "track": "usage", "period": "month", "group": "自动化",
        "defaults": {"free": 0, "paid": 200, "creator": -1},
    },
    {
        # 商城「已获取」资源数(负责人定:获取数量应按会员等级限制)。track=existing:
        # 直接数 cosmac_market_acquired 现有行,移除后额度立即释放,不走计数表。
        # 获取=给平台资源打「优先派单★」标记,免费用户给少量额度体验,付费/创作者放宽。
        "key": "acquired_items", "label": "商城已获取资源数", "unit": "个",
        "track": "existing", "period": "total", "group": "商城",
        "defaults": {"free": 5, "paid": 50, "creator": -1},
    },
]

_CATALOG_BY_KEY: Dict[str, Dict[str, Any]] = {q["key"]: q for q in QUOTA_CATALOG}
_TIER_SLUGS = [t["slug"] for t in MEMBER_TIERS]  # free / paid / creator


def metric_meta(key: str) -> Optional[Dict[str, Any]]:
    """取某计量项的元信息（label/period/unit/defaults）；未知返回 None。"""
    return _CATALOG_BY_KEY.get(key)


def _as_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def parse_quota_limits(ev: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    """把控制室 cosmac.quotas 事件解析成 {metric: {tier: limit}}，缺的用目录默认补齐。"""
    out: Dict[str, Dict[str, int]] = {}
    raw = (ev or {}).get("limits") if isinstance(ev, dict) else {}
    raw = raw if isinstance(raw, dict) else {}
    for q in QUOTA_CATALOG:
        key = q["key"]
        defaults = q["defaults"]
        cfg = raw.get(key) if isinstance(raw.get(key), dict) else {}
        out[key] = {
            tier: _as_int(cfg.get(tier), defaults.get(tier, -1)) for tier in _TIER_SLUGS
        }
    return out


class QuotaStore:
    """读控制室「用量配额」配置（带 TTL 缓存）。admin 写、bot 读。

    构造参数同 GatingStore：client（resolve_alias/get_state_event）+ control_room_alias。
    """

    def __init__(self, client: Any, control_room_alias: str, ttl: float = 20.0):
        self._client = client
        self._alias = control_room_alias
        self._ttl = ttl
        self._cache: Optional[Dict[str, Dict[str, int]]] = None
        self._cache_ts: float = float("-inf")

    def _limits(self) -> Dict[str, Dict[str, int]]:
        now = time.monotonic()
        if self._cache is not None and (now - self._cache_ts) < self._ttl:
            return self._cache
        try:
            room = self._client.resolve_alias(self._alias)
            ev = self._client.get_state_event(room, QUOTAS_EVENT_TYPE) if room else None
            limits = parse_quota_limits(ev)
        except Exception as e:
            logger.debug("读取配额配置失败，用默认：%s", e)
            limits = parse_quota_limits(None)
        self._cache = limits
        self._cache_ts = now
        return limits

    def limit(self, metric: str, tier: str) -> int:
        """某等级在某计量项上的上限；-1=不限。未知项/等级回退默认或不限。"""
        per_tier = self._limits().get(metric)
        if not per_tier:
            return -1
        return per_tier.get(tier, -1)
