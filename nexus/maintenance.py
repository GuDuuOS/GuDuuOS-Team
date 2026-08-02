"""Nexus 周期维护：AI 结算补偿与过期数据清理。

本模块是一次性命令，由 systemd timer 定时调用，不在 Nexus HTTP
进程内再开常驻线程。这样即使 Web 服务重启，维护任务仍有独立的
运行记录与失败重试，也不会在多进程部署时重复启动调度器。
"""

from __future__ import annotations

import argparse
import json
import time
from typing import Dict, Optional, Sequence

from sqlalchemy import delete, select

from nexus import db, gateway
from nexus.db import (
    NexusAdminRecoveryCode,
    NexusAdminSession,
    NexusAdminWebAuthnChallenge,
    NexusGatewayDebitOutbox,
    NexusHeartbeat,
    NexusKeyRequestDelivery,
    NexusOemEmailChallenge,
    NexusRequestStat,
    NexusSession,
)

_DAY_MS = 24 * 60 * 60 * 1000


def _deleted(s, model, condition) -> int:
    """执行一条批量删除并返回实际影响行数。"""
    result = s.execute(delete(model).where(condition))
    return int(result.rowcount or 0)


def cleanup(
    s,
    *,
    now_ms: Optional[int] = None,
    heartbeat_days: int = 90,
    request_stat_days: int = 180,
) -> Dict[str, int]:
    """清理已失效的鉴权状态与超过保留期的高频运行数据。

    不删除审计、订单、收益、KEY、发布记录或钱包流水；这些是长期商业
    证据。心跳和分钟请求桶只是运行观测数据，所以使用明确保留期。
    """
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    hb_days = max(30, min(int(heartbeat_days), 3650))
    stat_days = max(30, min(int(request_stat_days), 3650))
    counts = {
        "oem_sessions": _deleted(s, NexusSession, NexusSession.expires_ts <= now),
        "admin_sessions": _deleted(
            s, NexusAdminSession, NexusAdminSession.expires_ts <= now
        ),
        "email_challenges": _deleted(
            s, NexusOemEmailChallenge, NexusOemEmailChallenge.expires_ts <= now
        ),
        "webauthn_challenges": _deleted(
            s,
            NexusAdminWebAuthnChallenge,
            NexusAdminWebAuthnChallenge.expires_ts <= now,
        ),
        # 恢复码的已用/过期状态保留 7 天便于查故障，之后删除哈希。
        "recovery_codes": _deleted(
            s,
            NexusAdminRecoveryCode,
            NexusAdminRecoveryCode.expires_ts <= now - 7 * _DAY_MS,
        ),
        "heartbeats": _deleted(
            s,
            NexusHeartbeat,
            NexusHeartbeat.ts < now - hb_days * _DAY_MS,
        ),
        "request_stats": _deleted(
            s,
            NexusRequestStat,
            NexusRequestStat.minute_ts < now - stat_days * _DAY_MS,
        ),
        # 已完成的补偿任务保留 30 天供对账；pending 永不自动删除。
        "applied_debits": _deleted(
            s,
            NexusGatewayDebitOutbox,
            (NexusGatewayDebitOutbox.status == "applied")
            & (NexusGatewayDebitOutbox.applied_ts < now - 30 * _DAY_MS),
        ),
    }
    delivery_rows = list(
        s.execute(
            select(NexusKeyRequestDelivery).where(
                NexusKeyRequestDelivery.expires_ts <= now,
                NexusKeyRequestDelivery.cleared_ts.is_(None),
            )
        ).scalars()
    )
    for row in delivery_rows:
        # 领取期结束后立即清除可解密的 KEY 密文，只留交付审计边。
        row.encrypted_key = b""
        row.cleared_ts = now
    counts["expired_key_deliveries"] = len(delivery_rows)
    return counts


def _parser() -> argparse.ArgumentParser:
    """构造维护命令参数解析器。"""
    parser = argparse.ArgumentParser(description="执行 Nexus 周期维护")
    parser.add_argument("--heartbeat-days", type=int, default=90)
    parser.add_argument("--request-stat-days", type=int, default=180)
    parser.add_argument("--debit-limit", type=int, default=500)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """先补偿 AI 扣账，再清理过期数据，最后输出一行 JSON 摘要。"""
    args = _parser().parse_args(argv)
    db.init_engine()
    debit_result = gateway.settle_pending_debits(limit=args.debit_limit)
    s = db.session()
    try:
        cleanup_result = cleanup(
            s,
            heartbeat_days=args.heartbeat_days,
            request_stat_days=args.request_stat_days,
        )
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
    print(
        json.dumps(
            {"debits": debit_result, "cleanup": cleanup_result},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
