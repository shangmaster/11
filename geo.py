"""坐标系与地理编码。

签到接口吃的是「客户端上报的经纬度」，服务端只拿去算和老师设定点的距离。
所以位置签到能不能成功，取决于三件事：
  1. 坐标系别搞错（高德/腾讯给 GCJ-02，百度给 BD-09，GPS 给 WGS-84）
  2. 落点在 locationRange 半径内
  3. 别每次都精准落在同一个小数点后 7 位（老师看签到明细会发现）

本模块不联网，地理编码单独放在 geocode() 里，需要网络时由 engine 注入 fetcher。
"""

from __future__ import annotations

import math
import random

PI = math.pi
A = 6378245.0                 # 克拉索夫斯基椭球长半轴
EE = 0.00669342162296594323   # 偏心率平方
X_PI = PI * 3000.0 / 180.0
EARTH_R = 6371008.8           # 平均地球半径（米）


# --------------------------------------------------------------------------
# WGS-84 <-> GCJ-02
# --------------------------------------------------------------------------

def out_of_china(lat: float, lon: float) -> bool:
    return not (73.66 < lon < 135.05 and 3.86 < lat < 53.55)


def _transform_lat(x: float, y: float) -> float:
    ret = (-100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y
           + 0.2 * math.sqrt(abs(x)))
    ret += (20.0 * math.sin(6.0 * x * PI) + 20.0 * math.sin(2.0 * x * PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * PI) + 40.0 * math.sin(y / 3.0 * PI)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * PI) + 320 * math.sin(y * PI / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lon(x: float, y: float) -> float:
    ret = (300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y
           + 0.1 * math.sqrt(abs(x)))
    ret += (20.0 * math.sin(6.0 * x * PI) + 20.0 * math.sin(2.0 * x * PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * PI) + 40.0 * math.sin(x / 3.0 * PI)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * PI) + 300.0 * math.sin(x / 30.0 * PI)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lat: float, lon: float) -> tuple[float, float]:
    if out_of_china(lat, lon):
        return lat, lon
    d_lat = _transform_lat(lon - 105.0, lat - 35.0)
    d_lon = _transform_lon(lon - 105.0, lat - 35.0)
    rad_lat = lat / 180.0 * PI
    magic = math.sin(rad_lat)
    magic = 1 - EE * magic * magic
    sqrt_magic = math.sqrt(magic)
    d_lat = (d_lat * 180.0) / ((A * (1 - EE)) / (magic * sqrt_magic) * PI)
    d_lon = (d_lon * 180.0) / (A / sqrt_magic * math.cos(rad_lat) * PI)
    return lat + d_lat, lon + d_lon


def gcj02_to_wgs84(lat: float, lon: float) -> tuple[float, float]:
    """一次迭代反解，误差 < 1 米，足够签到用。"""
    if out_of_china(lat, lon):
        return lat, lon
    g_lat, g_lon = wgs84_to_gcj02(lat, lon)
    return lat * 2 - g_lat, lon * 2 - g_lon


# --------------------------------------------------------------------------
# GCJ-02 <-> BD-09
# --------------------------------------------------------------------------

def gcj02_to_bd09(lat: float, lon: float) -> tuple[float, float]:
    z = math.sqrt(lon * lon + lat * lat) + 0.00002 * math.sin(lat * X_PI)
    theta = math.atan2(lat, lon) + 0.000003 * math.cos(lon * X_PI)
    return z * math.sin(theta) + 0.006, z * math.cos(theta) + 0.0065


def bd09_to_gcj02(lat: float, lon: float) -> tuple[float, float]:
    x, y = lon - 0.0065, lat - 0.006
    z = math.sqrt(x * x + y * y) - 0.00002 * math.sin(y * X_PI)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * X_PI)
    return z * math.sin(theta), z * math.cos(theta)


# --------------------------------------------------------------------------
# 统一入口
# --------------------------------------------------------------------------

DATUMS = ("gcj02", "wgs84", "bd09")


def to_gcj02(lat: float, lon: float, datum: str = "gcj02") -> tuple[float, float]:
    d = (datum or "gcj02").lower()
    if d == "wgs84":
        return wgs84_to_gcj02(lat, lon)
    if d == "bd09":
        return bd09_to_gcj02(lat, lon)
    return lat, lon


def from_gcj02(lat: float, lon: float, datum: str = "gcj02") -> tuple[float, float]:
    d = (datum or "gcj02").lower()
    if d == "wgs84":
        return gcj02_to_wgs84(lat, lon)
    if d == "bd09":
        return gcj02_to_bd09(lat, lon)
    return lat, lon


def distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine，单位米。"""
    d_lat = (lat2 - lat1) * PI / 180
    d_lon = (lon2 - lon1) * PI / 180
    a = (math.sin(d_lat / 2) ** 2
         + math.cos(lat1 * PI / 180) * math.cos(lat2 * PI / 180) * math.sin(d_lon / 2) ** 2)
    return 2 * EARTH_R * math.asin(min(1.0, math.sqrt(a)))


def jitter(lat: float, lon: float, radius_m: float = 40.0,
           rng: random.Random | None = None) -> tuple[float, float]:
    """在 radius_m 米内随机偏移一点。

    为什么需要：地理编码同一个地址每次返回同一个点，连续十几次签到都落在
    小数点后第 7 位一模一样的位置，在老师那边的签到明细里非常显眼。
    偏移量保持在半径的 60% 以内，不会越出 locationRange。
    """
    r = rng or random.Random()
    # 半径要打折：坐标转换本身也有几米误差
    dist = r.uniform(0.0, max(1.0, radius_m * 0.6))
    bearing = r.uniform(0.0, 2 * PI)
    d_lat = (dist * math.cos(bearing)) / 111320.0
    d_lon = (dist * math.sin(bearing)) / (111320.0 * max(0.2, math.cos(lat * PI / 180)))
    return lat + d_lat, lon + d_lon


def parse_point(text: str) -> tuple[float, float] | None:
    """解析用户粘贴的坐标：`30.5,114.3` / `30.5 114.3` / `114.3,30.5`（自动纠正颠倒）。

    中国境内纬度 3.86~53.55、经度 73.66~135.05，用这个区间判断顺序。
    """
    if not text:
        return None
    parts = [p for p in str(text).replace("，", ",").split() if p]
    nums: list[float] = []
    for p in parts:
        for seg in p.replace(";", ",").split(","):
            seg = seg.strip()
            if not seg:
                continue
            try:
                nums.append(float(seg))
            except ValueError:
                return None
    if len(nums) < 2:
        return None
    a, b = nums[0], nums[1]
    if 3.86 < a < 53.55 and 73.66 < b < 135.05:      # lat, lon
        return a, b
    if 3.86 < b < 53.55 and 73.66 < a < 135.05:      # 写反了
        return b, a
    return a, b


# --------------------------------------------------------------------------
# 地理编码（可选，需要网络）
# --------------------------------------------------------------------------

def geocode_amap(address: str, key: str, fetcher) -> tuple[float, float] | None:
    """高德地理编码：地址 -> GCJ-02 坐标。fetcher 由 engine 注入（返回 (status, text)）。"""
    if not (address and key):
        return None
    from urllib.parse import quote as _q
    url = ("https://restapi.amap.com/v3/geocode/geo?output=json"
           f"&key={_q(key)}&address={_q(address)}")
    try:
        status, text = fetcher(url)
        if status != 200:
            return None
        import json
        data = json.loads(text)
        geos = data.get("geocodes") or []
        if not geos:
            return None
        loc = str(geos[0].get("location") or "")
        if "," not in loc:
            return None
        lon, lat = loc.split(",", 1)
        return float(lat), float(lon)
    except Exception:
        return None


def geocode_osm(address: str, fetcher) -> tuple[float, float] | None:
    """OpenStreetMap Nominatim 兜底：返回 WGS-84，调用方要自己转 GCJ-02。"""
    if not address:
        return None
    from urllib.parse import quote as _q
    url = ("https://nominatim.openstreetmap.org/search?format=json&limit=1"
           f"&q={_q(address)}")
    try:
        status, text = fetcher(url, {"User-Agent": "cxsign-sentinel/1.0"})
        if status != 200:
            return None
        import json
        rows = json.loads(text)
        if not rows:
            return None
        return float(rows[0]["lat"]), float(rows[0]["lon"])
    except Exception:
        return None


__all__ = [
    "wgs84_to_gcj02", "gcj02_to_wgs84", "gcj02_to_bd09", "bd09_to_gcj02",
    "to_gcj02", "from_gcj02", "distance", "jitter", "parse_point",
    "geocode_amap", "geocode_osm", "out_of_china", "DATUMS",
]
