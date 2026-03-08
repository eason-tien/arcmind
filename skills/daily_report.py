# -*- coding: utf-8 -*-
"""
ArcMind Skill: Daily Morning Report
每日早報技能 — 每天 06:00 透過 Telegram 發送早報。

包含：
- 天氣（當前位置）
- 國際 / 台灣 / 大陸 / 泰國 Top 5 新聞
- 過去 24h 系統異常與處理狀況
- 迭代進度
"""
from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger("arcmind.skills.daily_report")

_ARCMIND_DIR = Path(__file__).resolve().parent.parent

# ── User location config (will be updated when user travels) ──
_LOCATION_FILE = _ARCMIND_DIR / "config" / "user_location.json"
_DEFAULT_LOCATION = {
    "city": "大溪",
    "region": "桃園",
    "country": "Taiwan",
    "lat": 24.88,
    "lon": 121.28,
}


def _get_location() -> dict:
    """Read current user location from config file."""
    try:
        if _LOCATION_FILE.exists():
            return json.loads(_LOCATION_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return _DEFAULT_LOCATION.copy()


def _set_location(location: dict) -> None:
    """Update user location."""
    _LOCATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    _LOCATION_FILE.write_text(
        json.dumps(location, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ── Weather ──────────────────────────────────────────────────────────────────

def _fetch_wttr_weather(city: str) -> dict | None:
    """Fetch weather from wttr.in with retry and longer timeout."""
    max_retries = 2
    timeout = 20  # Increased from 10 to 20 seconds
    
    for attempt in range(max_retries):
        try:
            url = f"https://wttr.in/{urllib.parse.quote(city)}?format=j1&lang=zh-tw"
            req = urllib.request.Request(url, headers={"User-Agent": "ArcMind/0.3"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data
        except Exception as e:
            logger.warning(f"[DailyReport] wttr.in attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                import time
                time.sleep(2)  # Wait before retry
    return None


def _fetch_open_meteo_weather(lat: float, lon: float) -> dict | None:
    """Fetch weather from Open-Meteo (free, no API key needed)."""
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code"
            f"&daily=temperature_2m_max,temperature_2m_min"
            f"&timezone=auto"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "ArcMind/0.3"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data
    except Exception as e:
        logger.warning(f"[DailyReport] Open-Meteo fetch failed: {e}")
        return None


def _get_weather_description(code: int) -> str:
    """Convert Open-Meteo weather code to description."""
    codes = {
        0: "晴朗",
        1: "晴時多雲", 2: "多雲", 3: "陰天",
        45: "霧", 48: "霧凇",
        51: "小毛毛雨", 53: "中毛毛雨", 55: "大毛毛雨",
        61: "小雨", 63: "中雨", 65: "大雨",
        71: "小雪", 73: "中雪", 75: "大雪",
        80: "局部陣雨", 81: "陣雨", 82: "強陣雨",
        95: "雷暴", 96: "雷暴", 99: "雷暴",
    }
    return codes.get(code, "未知")


def _get_weather(location: dict) -> str:
    """Get weather using wttr.in (primary) with Open-Meteo as fallback."""
    city = location.get("city", "Taoyuan")
    region = location.get("region", "")
    country = location.get("country", "")
    lat = location.get("lat", 24.88)
    lon = location.get("lon", 121.28)
    
    # Try wttr.in first (primary)
    data = _fetch_wttr_weather(city)
    
    if data:
        try:
            current = data.get("current_condition", [{}])[0]
            temp = current.get("temp_C", "?")
            feels = current.get("FeelsLikeC", "?")
            humidity = current.get("humidity", "?")
            desc_zh = current.get("lang_zh", [{}])[0].get("value", "")
            desc = desc_zh or current.get("weatherDesc", [{}])[0].get("value", "")

            # Today's forecast
            forecast = data.get("weather", [{}])[0]
            max_temp = forecast.get("maxtempC", "?")
            min_temp = forecast.get("mintempC", "?")

            return (
                f"📍 {region}{city} ({country})\n"
                f"🌡 現在 {temp}°C (體感 {feels}°C)\n"
                f"🔼 最高 {max_temp}°C / 🔽 最低 {min_temp}°C\n"
                f"💧 濕度 {humidity}% | {desc}"
            )
        except Exception as e:
            logger.warning("[DailyReport] wttr.in parse failed: %s", e)
    
    # Fallback to Open-Meteo
    logger.info("[DailyReport] Trying Open-Meteo as fallback...")
    data = _fetch_open_meteo_weather(lat, lon)
    
    if data:
        try:
            current = data.get("current", {})
            daily = data.get("daily", {})
            
            temp = current.get("temperature_2m", "?")
            feels = current.get("apparent_temperature", "?")
            humidity = current.get("relative_humidity_2m", "?")
            code = current.get("weather_code", 0)
            desc = _get_weather_description(code)
            
            max_temp = daily.get("temperature_2m_max", ["?"])[0]
            min_temp = daily.get("temperature_2m_min", ["?"])[0]
            
            return (
                f"📍 {region}{city} ({country})\n"
                f"🌡 現在 {temp}°C (體感 {feels}°C)\n"
                f"🔼 最高 {max_temp}°C / 🔽 最低 {min_temp}°C\n"
                f"💧 濕度 {humidity}% | {desc} (Open-Meteo)"
            )
        except Exception as e:
            logger.warning("[DailyReport] Open-Meteo parse failed: %s", e)
    
    # All methods failed
    return "🌤 天氣資訊暫時無法取得 (請檢查網路連線)"


# ── News ─────────────────────────────────────────────────────────────────────

def _get_news_via_agent() -> str:
    """Use agentic_complete with web_search to get top news."""
    try:
        from runtime.tool_loop import agentic_complete

        prompt = (
            "請使用 web_search 工具搜尋以下四個區域的今日重要新聞，每個區域列出 Top 5：\n"
            "1. 國際新聞\n"
            "2. 台灣新聞\n"
            "3. 中國大陸新聞\n"
            "4. 泰國新聞\n\n"
            "格式要求：\n"
            "每條新聞一行，用 • 開頭，包含標題和簡短摘要（20字以內）。\n"
            "分四個區塊，用區域名稱作為標題。"
        )

        result = agentic_complete(
            prompt=prompt,
            task_type="research",
            budget="medium",
            max_tokens=3000,
            tools_enabled=True,
        )
        return result.get("content", "新聞取得失敗")
    except Exception as e:
        logger.error("[DailyReport] News fetch failed: %s", e)
        return f"📰 新聞暫時無法取得 ({e})"


# ── System Status ────────────────────────────────────────────────────────────

def _get_system_status() -> str:
    """Collect system anomalies from last 24 hours."""
    parts = []

    # 1. Error logs from past 24h - check BOTH arcmind.log AND arcmind_err.log
    log_file = _ARCMIND_DIR / "logs" / "arcmind.log"
    err_log_file = _ARCMIND_DIR / "logs" / "arcmind_err.log"
    errors_24h = 0
    warnings_24h = 0
    recent_errors = []
    
    # Helper to parse logs with multiple formats
    def parse_log_file(filepath, is_error_log=False):
        """Parse log file supporting both [ERROR] format and Traceback/Exception format."""
        local_errors = 0
        local_warnings = 0
        local_recent = []
        try:
            if filepath.exists():
                lines = filepath.read_text(encoding="utf-8", errors="replace").split("\n")
                cutoff = datetime.now() - timedelta(hours=24)
                cutoff_str = cutoff.strftime("%Y-%m-%d")
                today_str = datetime.now().strftime("%Y-%m-%d")
                
                for line in lines[-5000:]:  # Increased to catch more entries
                    # Skip if not from last 24 hours
                    if cutoff_str not in line and today_str not in line:
                        continue
                    
                    if is_error_log:
                        # For error log: look for Traceback, Error, Exception keywords
                        if any(kw in line for kw in ["Traceback", "Error:", "Exception:", "ValidationError"]):
                            local_errors += 1
                            # Extract meaningful error message
                            msg = line.strip()
                            # Clean up long traceback lines
                            msg = msg[:100] if msg else "Error detected"
                            local_recent.append(msg)
                    else:
                        # Standard log format with [ERROR] and [WARNING]
                        # Also check for raw Error/Exception/ValidationError (no [ERROR] prefix)
                        if "[ERROR]" in line:
                            local_errors += 1
                            msg = re.sub(
                                r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+ \[ERROR\] \S+ — ",
                                "", line.strip()
                            )
                            local_recent.append(msg[:80])
                        elif any(kw in line for kw in ["Error:", "Exception:", "ValidationError"]):
                            # Raw error text without [ERROR] prefix (e.g., ValidationError)
                            local_errors += 1
                            msg = line.strip()[:80]
                            local_recent.append(msg)
                        elif "[WARNING]" in line:
                            local_warnings += 1
        except Exception as e:
            logger.warning("[DailyReport] Failed to parse %s: %s", filepath, e)
        return local_errors, local_warnings, local_recent

    # Parse both log files
    e1, w1, err1 = parse_log_file(log_file, is_error_log=False)
    e2, w2, err2 = parse_log_file(err_log_file, is_error_log=True)
    
    errors_24h = e1 + e2
    warnings_24h = w1 + w2
    recent_errors = err1 + err2

    status_icon = "✅" if errors_24h == 0 else "⚠️" if errors_24h < 5 else "🔴"
    parts.append(f"{status_icon} 過去24h: {errors_24h} 錯誤 / {warnings_24h} 警告")

    if recent_errors:
        unique = list(dict.fromkeys(recent_errors))[:3]  # dedup, top 3
        for err in unique:
            # Clean up error message for display
            clean_err = err.strip()
            if len(clean_err) > 60:
                clean_err = clean_err[:60] + "..."
            parts.append(f"  → {clean_err}")

    # 2. Watchdog incidents
    try:
        incident_file = _ARCMIND_DIR / "evidence" / "ARCMIND_VERIFY.json"
        if incident_file.exists():
            data = json.loads(incident_file.read_text(encoding="utf-8"))
            incidents = data.get("incidents", [])
            if incidents:
                parts.append(f"🔧 Watchdog 事故: {len(incidents)} 筆")
    except Exception:
        pass

    # 3. CRON health
    try:
        from runtime.cron import cron_system
        jobs = cron_system.list_jobs()
        active = sum(1 for j in jobs if j.get("enabled"))
        parts.append(f"⏰ CRON 排程: {active} 個啟用中")
    except Exception:
        pass

    return "\n".join(parts) if parts else "✅ 系統運行正常"


# ── Iteration Progress ───────────────────────────────────────────────────────

def _get_iteration_progress() -> str:
    """Get the latest iteration plan status."""
    try:
        from db.schema import IterationRecord_, get_db
        db = next(get_db())
        rec = db.query(IterationRecord_).order_by(
            IterationRecord_.created_at.desc()
        ).first()
        if rec:
            plan = json.loads(rec.plan or "[]")
            planned = sum(1 for t in plan if t.get("status") == "planned")
            completed = sum(1 for t in plan if t.get("status") == "completed")
            total = len(plan)
            return (
                f"📋 週度迭代 ({rec.week_id}): "
                f"{completed}/{total} 完成, {planned} 待執行, "
                f"階段: {rec.phase}"
            )
        return "📋 尚無迭代記錄"
    except Exception as e:
        return f"📋 迭代進度查詢失敗 ({e})"


# ── Send Report ──────────────────────────────────────────────────────────────

def _send_telegram(message: str) -> bool:
    """Send report via Telegram."""
    try:
        from config.settings import settings
        token = settings.telegram_bot_token
        chat_id = settings.telegram_chat_id
        if not token or not chat_id:
            logger.warning("[DailyReport] No Telegram credentials")
            return False

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        if len(message) > 4000:
            message = message[:4000] + "\n...(truncated)"

        data = urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
        }).encode()
        req = urllib.request.Request(url, data=data, method="POST")
        urllib.request.urlopen(req, timeout=15)
        return True
    except Exception as e:
        logger.error("[DailyReport] Telegram send failed: %s", e)
        return False


def _send_email(subject: str, body: str) -> None:
    """Send report via email (best-effort)."""
    try:
        import subprocess
        # Use macOS mail command
        proc = subprocess.run(
            ["mail", "-s", subject, "eason.t.tian@gmail.com"],
            input=body.encode("utf-8"),
            capture_output=True,
            timeout=10,
        )
        if proc.returncode == 0:
            logger.info("[DailyReport] Email sent")
        else:
            logger.warning("[DailyReport] Email send failed: %s",
                           proc.stderr.decode("utf-8", errors="replace"))
    except Exception as e:
        logger.warning("[DailyReport] Email failed: %s", e)


# ── Main Entry Point ─────────────────────────────────────────────────────────

def run(inputs: dict) -> dict:
    """
    CRON-triggered daily report entry point.

    inputs:
      action: "report" (default) — generate and send daily report
              "update_location" — update user location
    """
    action = inputs.get("action", "report")

    if action == "update_location":
        loc = {
            "city": inputs.get("city", "大溪"),
            "region": inputs.get("region", "桃園"),
            "country": inputs.get("country", "Taiwan"),
            "lat": inputs.get("lat", 24.88),
            "lon": inputs.get("lon", 121.28),
        }
        _set_location(loc)
        return {"status": "location_updated", "location": loc}

    # ── Generate Report ──
    now = datetime.now()
    date_str = now.strftime("%Y/%m/%d (%a)")

    logger.info("[DailyReport] Generating morning report for %s", date_str)

    location = _get_location()

    # Collect all sections
    weather = _get_weather(location)
    system_status = _get_system_status()
    iteration_progress = _get_iteration_progress()

    # Build the report (news will be added separately since it may take time)
    report_lines = [
        f"☀️ <b>ArcMind 早報 — {date_str}</b>",
        "",
        "<b>🌤 天氣</b>",
        weather,
        "",
        "<b>🔧 系統狀態 (前24h)</b>",
        system_status,
        "",
        "<b>📊 迭代進度</b>",
        iteration_progress,
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "新聞稍後以獨立訊息發送...",
    ]

    report = "\n".join(report_lines)
    logger.info("[DailyReport] Report generated (%d chars)", len(report))

    # Send weather/system report first
    tg_ok = _send_telegram(report)

    # Then fetch and send news (this takes longer)
    try:
        news = _get_news_via_agent()
        news_msg = f"📰 <b>今日新聞摘要 — {date_str}</b>\n\n{news}"
        # Clean up markdown for Telegram (remove ** etc.)
        news_msg = news_msg.replace("**", "").replace("###", "").replace("##", "")
        _send_telegram(news_msg)
    except Exception as e:
        logger.error("[DailyReport] News section failed: %s", e)

    # Also send email
    email_body = report.replace("<b>", "").replace("</b>", "")
    _send_email(f"ArcMind 早報 — {date_str}", email_body)

    return {
        "status": "sent" if tg_ok else "partial",
        "date": date_str,
        "location": location,
        "sections": ["weather", "system_status", "iteration_progress", "news"],
    }
