"""实例地域字典（大屏地图用）：地域代码 → 中文名 + 经纬度。

**为什么不做 IP 自动定位**（2026-07-26 评估后改的方案，别再走回头路）：
  1. OEM 实例**全都跑在云服务器上**，而云厂商 IP 的地理归属常常是「服务商注册地」
     而不是机房实际所在地——IP 定位恰恰在我们这个场景下最不准；
  2. ip2region 的数据文件已换成 v3 格式（``ip2region_v4.xdb``），手写二进制解析一旦解错
     是**静默出错**（地图上点全飘、还没人发现）；引 MaxMind 又要负责人去注册领 license。
  3. OEM 自己最清楚机房在哪——兑码时选一下即可，一次性、零依赖、100% 准。
心跳来源 IP 仍会记下来（见 fleet.record_heartbeat_ip），但**只作人工核对的参考**，
不参与自动定位。地域填错了在 console 改，改完即准。

坐标取各省会/首府（或国家主要城市）中心点——大屏是宏观分布图，省级精度足够。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# 代码 → (中文名, 纬度, 经度)。代码沿用 ISO 风格：中国用 CN-<省级简码>，境外用国家码。
REGIONS: Dict[str, Tuple[str, float, float]] = {
    # —— 中国大陆 31 省级 ——
    "CN-BJ": ("北京", 39.9042, 116.4074),
    "CN-TJ": ("天津", 39.3434, 117.3616),
    "CN-HE": ("河北", 38.0428, 114.5149),
    "CN-SX": ("山西", 37.8706, 112.5489),
    "CN-NM": ("内蒙古", 40.8414, 111.7519),
    "CN-LN": ("辽宁", 41.8057, 123.4315),
    "CN-JL": ("吉林", 43.8171, 125.3235),
    "CN-HL": ("黑龙江", 45.8038, 126.5349),
    "CN-SH": ("上海", 31.2304, 121.4737),
    "CN-JS": ("江苏", 32.0603, 118.7969),
    "CN-ZJ": ("浙江", 30.2741, 120.1551),
    "CN-AH": ("安徽", 31.8206, 117.2272),
    "CN-FJ": ("福建", 26.0745, 119.2965),
    "CN-JX": ("江西", 28.6820, 115.8579),
    "CN-SD": ("山东", 36.6512, 117.1201),
    "CN-HA": ("河南", 34.7466, 113.6254),
    "CN-HB": ("湖北", 30.5928, 114.3055),
    "CN-HN": ("湖南", 28.2282, 112.9388),
    "CN-GD": ("广东", 23.1291, 113.2644),
    "CN-GX": ("广西", 22.8170, 108.3665),
    "CN-HI": ("海南", 20.0444, 110.1999),
    "CN-CQ": ("重庆", 29.5630, 106.5516),
    "CN-SC": ("四川", 30.5728, 104.0668),
    "CN-GZ": ("贵州", 26.6470, 106.6302),
    "CN-YN": ("云南", 25.0389, 102.7183),
    "CN-XZ": ("西藏", 29.6520, 91.1721),
    "CN-SN": ("陕西", 34.3416, 108.9398),
    "CN-GS": ("甘肃", 36.0611, 103.8343),
    "CN-QH": ("青海", 36.6171, 101.7782),
    "CN-NX": ("宁夏", 38.4872, 106.2309),
    "CN-XJ": ("新疆", 43.8256, 87.6168),
    # —— 港澳台 ——
    "CN-HK": ("香港", 22.3193, 114.1694),
    "CN-MO": ("澳门", 22.1987, 113.5439),
    "CN-TW": ("台湾", 25.0330, 121.5654),
    # —— 境外常见部署地（按需再加）——
    "SG": ("新加坡", 1.3521, 103.8198),
    "JP": ("日本", 35.6762, 139.6503),
    "KR": ("韩国", 37.5665, 126.9780),
    "MY": ("马来西亚", 3.1390, 101.6869),
    "TH": ("泰国", 13.7563, 100.5018),
    "ID": ("印尼", -6.2088, 106.8456),
    "AE": ("阿联酋", 25.2048, 55.2708),
    "US": ("美国", 37.3875, -122.0575),
    "CA": ("加拿大", 43.6532, -79.3832),
    "GB": ("英国", 51.5074, -0.1278),
    "DE": ("德国", 50.1109, 8.6821),
    "AU": ("澳大利亚", -33.8688, 151.2093),
}


def is_valid(code: str) -> bool:
    """地域代码是否在字典里（服务端校验用，防前端传脏值）。"""
    return (code or "").strip().upper() in REGIONS


def normalize(code: str) -> str:
    """规范化地域代码；非法返回空串。"""
    c = (code or "").strip().upper()
    return c if c in REGIONS else ""


def lookup(code: str) -> Optional[Dict[str, Any]]:
    """代码 → {code,label,lat,lon}；未知返回 None。"""
    c = normalize(code)
    if not c:
        return None
    label, lat, lon = REGIONS[c]
    return {"code": c, "label": label, "lat": lat, "lon": lon}


def options() -> List[Dict[str, Any]]:
    """给前端下拉用的全量选项（中国在前、境外在后，各自按代码排序）。"""
    cn = sorted((k for k in REGIONS if k.startswith("CN-")))
    other = sorted((k for k in REGIONS if not k.startswith("CN-")))
    out: List[Dict[str, Any]] = []
    for k in cn + other:
        label, lat, lon = REGIONS[k]
        out.append({"code": k, "label": label, "lat": lat, "lon": lon})
    return out


def mask_ip(ip: str) -> str:
    """把心跳来源 IP 脱敏后再存（只留网段，够人工核对、不留完整地址）。

    IPv4 → ``/24``、IPv6 → ``/64``。存客户完整 IP 属敏感信息，我们只需要"大概哪个网段"
    来核对 OEM 填的地域是否离谱，没必要留全。
    ⚠️ 必须用标准库 ``ipaddress`` 算网段，别手工切字符串——IPv6 的 ``::`` 压缩会让
    "取前 4 组"取到末尾组，算出**完全不同的网段**（本地实测踩到）。非法输入返回空串。
    """
    import ipaddress

    ip = (ip or "").strip()
    if not ip or ip == "?":
        return ""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ""
    prefix = 24 if addr.version == 4 else 64
    return str(ipaddress.ip_network(f"{ip}/{prefix}", strict=False))
