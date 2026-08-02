# -*- coding: utf-8 -*-
"""产品时区工具——所有「给人看/给模型看的时间」统一从这里出。

背景(负责人线上实测):GCP 服务器时区是 UTC,bot 注入给主 AI 的【当前时间】、任务
截止时间的解析与显示全用了服务器本地时区 → 用户 11:05 时 AI 说"现在是 03:04",
相对截止时间("今天11:30")也会被存偏 8 小时。

约定:产品面向中文用户,**默认按北京时间(Asia/Shanghai)**;跨区部署可用环境变量
COSMAC_TZ(如 "Asia/Tokyo")覆盖。epoch 秒仍是绝对时间,只有"解析/展示"经过时区。
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Optional

logger = logging.getLogger("cosmac.tzutil")

# 中文星期(strftime %A 依赖系统 locale,服务器上常是英文,干脆自己映射)
_WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def product_tz() -> tzinfo:
    """产品时区:COSMAC_TZ(IANA 名)> 默认 Asia/Shanghai;都拿不到退回 UTC+8 固定偏移。"""
    name = (os.environ.get("COSMAC_TZ") or "Asia/Shanghai").strip()
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:
        # 系统缺 tzdata / 名字写错:退回 UTC+8(产品主用户群),别让时间功能整个瘫掉
        logger.warning("加载时区 %s 失败,退回固定 UTC+8", name)
        return timezone(timedelta(hours=8))


def now_text() -> str:
    """给模型/用户看的「当前时间」文本,如 2026-07-14 11:05（周二）。"""
    dt = datetime.now(product_tz())
    return f"{dt.strftime('%Y-%m-%d %H:%M')}（{_WEEKDAYS[dt.weekday()]}）"


def fmt_ts(ts: int, fmt: str = "%m-%d %H:%M") -> str:
    """epoch 秒 → 产品时区的展示文本(任务截止时间等)。"""
    return datetime.fromtimestamp(int(ts), product_tz()).strftime(fmt)


def utc_iso(value: Optional[datetime]) -> str:
    """把数据库时间序列化为带 ``Z`` 的 UTC ISO 8601 字符串。

    cosmac 的 ``DateTime`` 列统一保存 naive UTC；若直接 ``isoformat()``，浏览器会把
    它误认成用户本地时间，东八区界面便会少显示 8 小时。这里显式补上 UTC 语义；如果
    调用方传入的本来就是带时区时间，则先换算成 UTC。空值返回空串，便于 API 直接下发。

    参数：
        value: 数据库读出的 naive UTC 或任意带时区 ``datetime``，也可以是 ``None``。
    返回：
        形如 ``2026-07-27T02:34:37Z`` 的字符串；前端可据此转换到操作系统时区。
    """
    if value is None:
        return ""
    if value.tzinfo is None:
        # SQLAlchemy 的 DateTime 在 SQLite/PG 均按项目约定保存 naive UTC；补 tzinfo
        # 只声明它原本的语义，不改变钟面数值。
        utc_value = value.replace(tzinfo=timezone.utc)
    else:
        utc_value = value.astimezone(timezone.utc)
    # 浏览器原生 Date 对 Z 兼容最稳定；同时比 +00:00 更直观地表达 UTC。
    return utc_value.isoformat().replace("+00:00", "Z")


def weekday_table(days: int = 14) -> str:
    """未来 N 天的「日期↔星期」紧凑对照表(从明天起),注入给模型防星期算错。

    背景(负责人线上实测):模型写公告"7月18日(周五)",实际是周六——LLM 心算未来
    日期的星期不可靠,直接把对照表喂给它,涉及日期的文案照抄即可。
    形如:07-15周三 07-16周四 …(约 7 字符/天,14 天 ≈ 100 字符,注入成本可忽略)。
    """
    tz = product_tz()
    today = datetime.now(tz)
    parts = []
    for i in range(1, days + 1):
        d = today + timedelta(days=i)
        parts.append(f"{d.strftime('%m-%d')}{_WEEKDAYS[d.weekday()]}")
    return " ".join(parts)


def parse_local_to_epoch(s: str, fmt: str) -> Optional[int]:
    """按产品时区把 naive 时间字符串解析成 epoch 秒(解析失败返回 None)。

    模型给的 'YYYY-MM-DD HH:MM' 语义上是**用户所在时区**的时刻——必须按产品时区
    落 epoch,不能按服务器时区(UTC 服务器上会偏 8 小时)。
    """
    try:
        dt = datetime.strptime(s, fmt)
    except ValueError:
        return None
    return int(dt.replace(tzinfo=product_tz()).timestamp())
