"""
天气数据客户端 — Open-Meteo API
===============================
独立模块，不依赖项目其他文件，可单独运行测试。

用法:
    python weather_client.py          # 测试：打印今明后3天天气

    from weather_client import fetch_daily_weather, get_et0_rain
    w = fetch_daily_weather()         # 获取天气预报 (dict)
    et0, rain = get_et0_rain()        # 快捷获取 ET0 + 降雨 (mm/天)

地点: 乌兰察布市察右中旗
  坐标: 41.27°N, 112.64°E
  海拔: ~1746m
"""

import json
import os
import time
from datetime import datetime

import requests

# ---- 地点配置 ----
LOCATION = {
    "name": "乌兰察布察右中旗",
    "latitude": 41.27,
    "longitude": 112.64,
    "timezone": "Asia/Shanghai",
    "elevation_m": 1746,
}

# ---- 缓存设置 ----
_CACHE_DIR = os.path.join(os.path.dirname(__file__), ".weather_cache")
_CACHE_TTL_SECONDS = 3600  # 1 小时才重新请求（免费接口，留点体面）


def _cache_path() -> str:
    os.makedirs(_CACHE_DIR, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    return os.path.join(_CACHE_DIR, f"weather_{today}.json")


def _load_cache() -> dict | None:
    path = _cache_path()
    if not os.path.exists(path):
        return None
    age = time.time() - os.path.getmtime(path)
    if age > _CACHE_TTL_SECONDS:
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_cache(data: dict):
    with open(_cache_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def fetch_daily_weather(
    forecast_days: int = 7,
    use_cache: bool = True,
) -> dict:
    """获取逐日天气预报。

    参数
    ----------
    forecast_days : int
        预报天数 (1~16)，默认 7
    use_cache : bool
        是否使用缓存，默认 True

    返回
    ----------
    dict:
        { "time": ["2026-05-18", ...],
          "et0_mm_day": [5.14, 5.40, ...],
          "rain_mm_day": [0.0, 0.0, ...],
          "t_max_c": [19.4, 20.2, ...],
          "t_min_c": [4.6, 7.4, ...],
          "location": "乌兰察布察右中旗" }
    """
    if use_cache:
        cached = _load_cache()
        if cached is not None:
            return cached

    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": LOCATION["latitude"],
        "longitude": LOCATION["longitude"],
        "daily": "et0_fao_evapotranspiration,precipitation_sum,"
                 "temperature_2m_max,temperature_2m_min",
        "timezone": LOCATION["timezone"],
        "forecast_days": forecast_days,
        "wind_speed_unit": "ms",
    }

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        raw = resp.json()
    except (requests.RequestException, ValueError) as e:
        # 网络异常时返回缓存（哪怕过期）或默认值
        print(f"[weather_client] 请求失败: {e}")
        return _fallback_data()

    daily = raw.get("daily", {})
    result = {
        "time": daily.get("time", []),
        "et0_mm_day": daily.get("et0_fao_evapotranspiration", []),
        "rain_mm_day": daily.get("precipitation_sum", []),
        "t_max_c": daily.get("temperature_2m_max", []),
        "t_min_c": daily.get("temperature_2m_min", []),
        "location": LOCATION["name"],
        "elevation_m": raw.get("elevation", LOCATION["elevation_m"]),
        "fetched_at": datetime.now().isoformat(),
    }

    _save_cache(result)
    return result


def get_et0_rain(day_index: int = 0) -> tuple[float, float]:
    """快捷方法：获取第 N 天的 ET0 和降雨。

    参数
    ----------
    day_index : int
        0=今天, 1=明天, ...

    返回
    ----------
    (et0_mm_day, rain_mm_day)
    """
    data = fetch_daily_weather()
    try:
        et0 = float(data["et0_mm_day"][day_index])
        rain = float(data["rain_mm_day"][day_index])
    except (IndexError, KeyError):
        et0, rain = 5.0, 2.0  # 论文默认值兜底
    return et0, rain


def _fallback_data() -> dict:
    """网络不可用时的兜底数据。"""
    today = datetime.now().strftime("%Y-%m-%d")
    return {
        "time": [today],
        "et0_mm_day": [5.0],
        "rain_mm_day": [2.0],
        "t_max_c": [20.0],
        "t_min_c": [10.0],
        "location": LOCATION["name"],
        "elevation_m": LOCATION["elevation_m"],
        "fetched_at": datetime.now().isoformat(),
        "fallback": True,
    }


# ============================================================
#  直接运行 python weather_client.py 查看天气
# ============================================================
if __name__ == "__main__":
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    print(f"地点: {LOCATION['name']}")
    print(f"坐标: {LOCATION['latitude']}N, {LOCATION['longitude']}E")
    print(f"海拔: {LOCATION['elevation_m']}m")
    print("-" * 60)

    data = fetch_daily_weather(use_cache=False)
    print(f"{'日期':<12} {'ET0(mm)':>8} {'降雨(mm)':>8} {'最高(°C)':>8} {'最低(°C)':>8}")
    print("-" * 52)
    for i in range(len(data["time"])):
        print(f"{data['time'][i]:<12} {data['et0_mm_day'][i]:>8.1f} "
              f"{data['rain_mm_day'][i]:>8.1f} {data['t_max_c'][i]:>8.1f} "
              f"{data['t_min_c'][i]:>8.1f}")

    et0, rain = get_et0_rain()
    print(f"\n当前用于仿真: et0={et0} mm/天, rain={rain} mm/天")
