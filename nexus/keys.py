"""OEM 授权码（KEY）的生成与校验。

KEY 是整个 OEM 商业模式的锚点（买断凭证 + LLM 网关的运行时凭证，一码两用）。
安全约定：
    - 库里**只存 sha256 哈希**——Nexus 数据库被拖走也拿不到可用的 KEY；
    - 明文只在签发那一刻返回一次，之后无法找回（丢了就作废重发）；
    - 字母表剔除易混淆字符（0/O、1/I/L），方便商务口头/邮件传达不出错。
"""

from __future__ import annotations

import hashlib
import secrets

# 32 个不易混淆的字符：16 位随机 = 32^16 ≈ 2^80 种组合，暴力不可行
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

# KEY 展示格式：CMK-XXXX-XXXX-XXXX-XXXX（CMK = CosMac Key，便于一眼识别）
_PREFIX = "CMK"
_GROUPS = 4
_GROUP_LEN = 4


def generate_key() -> str:
    """生成一把新 KEY 的**明文**（形如 ``CMK-A2B3-C4D5-E6F7-G8H9``）。"""
    groups = [
        "".join(secrets.choice(_ALPHABET) for _ in range(_GROUP_LEN))
        for _ in range(_GROUPS)
    ]
    return "-".join([_PREFIX, *groups])


def normalize_key(raw: str) -> str:
    """归一化用户输入的 KEY：去空白、转大写。

    OEM 从邮件里复制经常带首尾空格/小写，这里统一清洗，降低无谓的支持工单。
    """
    return (raw or "").strip().upper()


def hash_key(raw: str) -> str:
    """KEY → 库内存储形态（sha256 十六进制）。查询/比对一律用哈希。"""
    return hashlib.sha256(normalize_key(raw).encode("utf-8")).hexdigest()


def looks_like_key(raw: str) -> bool:
    """粗校验格式（前缀+分组长度），把明显不是 KEY 的输入挡在查库之前。"""
    parts = normalize_key(raw).split("-")
    return (
        len(parts) == _GROUPS + 1
        and parts[0] == _PREFIX
        and all(len(p) == _GROUP_LEN for p in parts[1:])
    )
