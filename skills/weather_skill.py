"""
Skill: weather_skill
獨立天氣查詢技能 — 從 daily_report 拆出並增強

後端: wttr.in (primary) + Open-Meteo (fallback)
功能: current / forecast / alerts
"""
from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger("arcmind.skill.weather")

_ARCMIND_DIR = Path(__file__).resolve().parent.parent
_LOCATION_FILE = _ARCMIND_DIR / "config" / "user_location.json"

_WMO_CODES = {
    0: "晴朗 ☀️", 1: "晴時多雲 🌤", 2: "多雲 ⛅", 3: "陰天 ☁️",
    45: "霧 🌫", 48: "霧凇 🌫",
    51: "小毛毛雨 🌦", 53: "中毛毛雨 🌧", 55: "大毛毛雨 🌧",
    61: "小雨 🌧", 63: "中雨 🌧", 65: "大雨 🌧",
    71: "小雪 🌨", 73: "中雪 ❄️", 75: "大雪 ❄️",
    80: "局部陣雨 🌦", 81: "陣雨 🌧", 82: "強陣雨 ⛈",
    85: "小雪陣雨 🌨", 86: "大雪陣雨 ❄️",
    95: "雷暴 ⛈", 96: "雷暴伴冰雹 ⛈", 99: "強雷暴 ⛈",
}


def _get_default_location() -> dict:
    """Read user location from config."""
    try:
        if _LOCATION_FILE.exists():
            return json.loads(_LOCATION_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"city": "大溪", "region": "桃園", "country": "Taiwan", "lat": 24.88, "lon": 121.28}


def _fetch_wttr(city: str, timeout: int = 15) -> dict | None:
    """Fetch weather data from wttr.in."""
    try:
        url = f"https://wttr.in/{urllib.parse.quote(city)}?format=j1&lang=zh-tw"
        req = urllib.request.Request(url, headers={"User-Agent": "ArcMind/0.3"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.warning("[weather] wttr.in failed: %s", e)
        return None


def _fetch_open_meteo(lat: float, lon: float, timeout: int = 15) -> dict | None:
    """Fetch weather data from Open-Meteo (free, no API key)."""
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,relative_humidity_2m,apparent_temperature,"
            f"weather_code,wind_speed_10m,wind_direction_10m,surface_pressure"
            f"&hourly=temperature_2m,precipitation_probability,weather_code"
            f"&daily=temperature_2m_max,temperature_2m_min,sunrise,sunset,"
            f"precipitation_sum,precipitation_probability_max,weather_code"
            f"&timezone=auto&forecast_days=7"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "ArcMind/0.3"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.warning("[weather] Open-Meteo failed: %s", e)
        return None


def _current(inputs: dict) -> dict:
    """Get current weather."""
    city = inputs.get("city", "")
    lat = inputs.get("lat", 0)
    lon = inputs.get("lon", 0)

    if not city and not (lat and lon):
        loc = _get_default_location()
        city = loc.get("city", "Taoyuan")
        lat = loc.get("lat", 24.88)
        lon = loc.get("lon", 121.28)

    # Try wttr.in first
    if city:
        data = _fetch_wttr(city)
        if data:
            try:
                current = data.get("current_condition", [{}])[0]
                forecast = data.get("weather", [{}])[0]
                desc_zh = current.get("lang_zh", [{}])[0].get("value", "")
                desc = desc_zh or current.get("weatherDesc", [{}])[0].get("value", "")

                return {
                    "success": True,
                    "source": "wttr.in",
                    "city": city,
                    "temperature": float(current.get("temp_C", 0)),
                    "feels_like": float(current.get("FeelsLikeC", 0)),
                    "humidity": int(current.get("humidity", 0)),
                    "description": desc,
                    "wind_speed_kmh": float(current.get("windspeedKmph", 0)),
                    "wind_direction": current.get("winddir16Point", ""),
                    "pressure_mb": float(current.get("pressure", 0)),
                    "visibility_km": float(current.get("visibility", 0)),
                    "uv_index": int(current.get("uvIndex", 0)),
                    "today_high": float(forecast.get("maxtempC", 0)),
                    "today_low": float(forecast.get("mintempC", 0)),
                }
            except Exception as e:
                logger.warning("[weather] wttr.in parse failed: %s", e)

    # Fallback: Open-Meteo
    if not lat:
        lat = 24.88
    if not lon:
        lon = 121.28

    data = _fetch_open_meteo(lat, lon)
    if data:
        current = data.get("current", {})
        daily = data.get("daily", {})
        code = current.get("weather_code", 0)

        return {
            "success": True,
            "source": "open-meteo",
            "city": city or f"({lat}, {lon})",
            "temperature": current.get("temperature_2m", 0),
            "feels_like": current.get("apparent_temperature", 0),
            "humidity": current.get("relative_humidity_2m", 0),
            "description": _WMO_CODES.get(code, f"WMO code {code}"),
            "wind_speed_kmh": current.get("wind_speed_10m", 0),
            "pressure_mb": current.get("surface_pressure", 0),
            "today_high": daily.get("temperature_2m_max", [0])[0],
            "today_low": daily.get("temperature_2m_min", [0])[0],
        }

    return {"success": False, "error": "天氣資訊暫時無法取得"}


def _forecast(inputs: dict) -> dict:
    """Get multi-day forecast."""
    lat = inputs.get("lat", 0)
    lon = inputs.get("lon", 0)
    days = int(inputs.get("days", 7))

    if not lat or not lon:
        loc = _get_default_location()
        lat = loc.get("lat", 24.88)
        lon = loc.get("lon", 121.28)

    data = _fetch_open_meteo(lat, lon)
    if not data:
        return {"success": False, "error": "預報資訊無法取得"}

    daily = data.get("daily", {})
    dates = daily.get("time", [])[:days]
    forecast_list = []

    for i, date in enumerate(dates):
        code = daily.get("weather_code", [0] * len(dates))[i]
        forecast_list.append({
            "date": date,
            "high": daily.get("temperature_2m_max", [0] * len(dates))[i],
            "low": daily.get("temperature_2m_min", [0] * len(dates))[i],
            "description": _WMO_CODES.get(code, f"WMO {code}"),
            "precipitation_sum_mm": daily.get("precipitation_sum", [0] * len(dates))[i],
            "precipitation_probability": daily.get("precipitation_probability_max", [0] * len(dates))[i],
            "sunrise": daily.get("sunrise", [""] * len(dates))[i],
            "sunset": daily.get("sunset", [""] * len(dates))[i],
        })

    return {
        "success": True,
        "source": "open-meteo",
        "forecast": forecast_list,
        "days": len(forecast_list),
    }


def _set_location(inputs: dict) -> dict:
    """Set default weather location."""
    location = {
        "city": inputs.get("city", ""),
        "region": inputs.get("region", ""),
        "country": inputs.get("country", ""),
        "lat": float(inputs.get("lat", 0)),
        "lon": float(inputs.get("lon", 0)),
    }

    if not location["city"] and not (location["lat"] and location["lon"]):
        return {"success": False, "error": "需要 city 或 lat/lon"}

    _LOCATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    _LOCATION_FILE.write_text(
        json.dumps(location, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {"success": True, "location": location}


# ── Main Entry ────────────────────────────────────────────────

def run(inputs: dict) -> dict:
    """
    Weather skill entry point.

    inputs:
      action: current | forecast | set_location
      city: str (城市名)
      lat/lon: float (經緯度)
      days: int (forecast 天數, 預設 7)
    """
    action = inputs.get("action", "current")

    handlers = {
        "current": _current,
        "forecast": _forecast,
        "set_location": _set_location,
    }

    handler = handlers.get(action)
    if not handler:
        return {
            "success": False,
            "error": f"未知 action: {action}",
            "available_actions": list(handlers.keys()),
        }

    try:
        return handler(inputs)
    except Exception as e:
        logger.error("[weather] %s failed: %s", action, e)
        return {"success": False, "error": str(e), "action": action}
