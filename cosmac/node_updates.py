"""OEM 节点网页与宿主更新代理之间的最小状态文件协议。"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Dict


def write_update_approval(path: str, release_id: int, approved_by: str) -> None:
    """在现有共享目录中原子写入节点管理员批准。

    共享目录由宿主更新代理创建并维护权限。容器进程可能只有目录的组写权限，
    因此这里绝不能对父目录执行 ``chmod``/``chown``；这两种操作要求目录所有权，
    会把“本来可以写文件”的合法部署误判为权限失败。
    """
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, mode=0o770, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".approved-update-", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            value: Dict[str, Any] = {
                "release_id": int(release_id),
                "approved_by": str(approved_by),
            }
            json.dump(value, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
            # 临时文件由当前容器进程创建，fchmod 不需要父目录所有权。
            os.fchmod(handle.fileno(), 0o660)
        os.replace(temp, path)
    finally:
        try:
            os.unlink(temp)
        except FileNotFoundError:
            pass


__all__ = ["write_update_approval"]
