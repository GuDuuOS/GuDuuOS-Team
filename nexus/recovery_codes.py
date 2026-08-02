"""Nexus 超管单次恢复码的 SSH 命令行工具。

这是网页忘记密码时的最后恢复路径：运维人员必须先登录 Nexus
服务器，再创建一枚最多存活 60 分钟、仅可使用一次的恢复码。
明文只输出到当前终端，不写日志、不写文件、不写数据库。
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from nexus import admin_auth, db


def _load_database_url(env_file: str) -> None:
    """从 systemd EnvironmentFile 只读取 Nexus 数据库地址。

    SSH shell 不会自动继承 systemd 服务的环境变量。这里不能用
    ``source /etc/nexus.env``，因为 EnvironmentFile 不是 shell 脚本，且
    执行其中内容会扩大密钥泄露与命令注入风险。

    当当前 shell 已显式提供 ``NEXUS_DATABASE_URL`` 时保留它，
    方便本地测试和非 systemd 部署。
    """
    if os.environ.get("NEXUS_DATABASE_URL", "").strip():
        return
    path = Path(env_file)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        # 本地开发没有 /etc/nexus.env 时继续使用 db.py 的 SQLite 回退。
        return
    except OSError as exc:
        raise RuntimeError("无法读取 Nexus 环境文件") from exc
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() != "NEXUS_DATABASE_URL":
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if not value:
            raise RuntimeError("NEXUS_DATABASE_URL 不能为空")
        os.environ["NEXUS_DATABASE_URL"] = value
        return
    # 生产环境文件存在却没有 DB URL 时必须停下，绝不能悄悄
    # 在工作目录创建 SQLite，否则恢复码会写进错误数据库。
    raise RuntimeError("Nexus 环境文件缺少 NEXUS_DATABASE_URL")


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
    parser.add_argument(
        "--env-file",
        default=os.environ.get("NEXUS_ENV_FILE", "/etc/nexus.env"),
        help="systemd EnvironmentFile 路径（默认 /etc/nexus.env）",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """创建恢复码并将明文仅显示在当前 SSH 终端。"""
    args = _parser().parse_args(argv)
    _load_database_url(str(args.env_file))
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
