"""Nexus 超管单次恢复码的 SSH 命令行工具。

这是网页忘记密码时的最后恢复路径：运维人员必须先登录 Nexus
服务器，再创建一枚最多存活 60 分钟、仅可使用一次的恢复码。
明文只输出到当前终端，不写日志、不写文件、不写数据库。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from typing import Optional, Sequence

from nexus import admin_auth, db


def _parser() -> argparse.ArgumentParser:
    """构造命令行参数解析器，便于测试与主入口复用。"""
    parser = argparse.ArgumentParser(
        description="为 Nexus 超管登录创建短期单次恢复码"
    )
    parser.add_argument(
        "--minutes",
        type=int,
        default=15,
        help="有效分钟数（5-60，默认 15）",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """创建恢复码并将明文仅显示在当前 SSH 终端。"""
    args = _parser().parse_args(argv)
    db.init_engine()
    s = db.session()
    try:
        result = admin_auth.create_recovery_code(s, ttl_minutes=args.minutes)
        s.commit()
    finally:
        s.close()
    expires = datetime.fromtimestamp(
        int(result["expires_ts"]) / 1000, tz=timezone.utc
    ).isoformat()
    print(result["code"])
    print(f"expires_utc={expires}")
    print("该恢复码仅可使用一次；使用或过期后立即作废。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
