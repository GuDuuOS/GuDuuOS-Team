"""GuDuu Nexus 服务启动入口。

用法（项目根目录）：
    NEXUS_ADMIN_TOKEN=xxx .venv/bin/python -m nexus

环境变量：
    NEXUS_DATABASE_URL  数据库（缺省本地 SQLite run/nexus.db）
    NEXUS_ADMIN_TOKEN   管理端点令牌（必配，否则管理端点 503）
    NEXUS_LISTEN_HOST / NEXUS_LISTEN_PORT   监听（默认 127.0.0.1:9100）
"""

from __future__ import annotations

import logging

from nexus.service import run


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    run()


if __name__ == "__main__":
    main()
