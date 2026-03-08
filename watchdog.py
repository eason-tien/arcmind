#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ArcMind — Watchdog Supervisor
================================
獨立監控進程，監控主 Agent 健康狀態。
故障時調用 Repair Agent 診斷修復，然後重啟主 Agent。

Usage:
  python watchdog.py              # 前台運行
  launchctl load com.arcmind.watchdog.plist  # 後台服務
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Setup
_ARCMIND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_ARCMIND_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            str(_ARCMIND_DIR / "logs" / "watchdog.log"),
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger("arcmind.watchdog")

# ── Config ───────────────────────────────────────────────────────────────────
HEALTH_URL      = "http://127.0.0.1:8100/health"
CHECK_INTERVAL  = 15      # seconds between health checks
FAIL_THRESHOLD  = 3       # consecutive failures before triggering repair
BACKUP_INTERVAL = 300     # seconds between config backups (5 min)
STARTUP_DELAY   = 30      # seconds to wait after starting before first check
COOLDOWN_AFTER_REPAIR = 60  # seconds to wait after repair before checking again


class Watchdog:
    def __init__(self):
        self._consecutive_fails = 0
        self._last_backup = 0.0
        self._repair_count = 0
        self._max_repairs_per_hour = 5
        self._repair_timestamps: list[float] = []

    def run_forever(self) -> None:
        """Main watchdog loop."""
        logger.info("=" * 50)
        logger.info("  ArcMind Watchdog v1.0")
        logger.info("  Health URL: %s", HEALTH_URL)
        logger.info("  Check interval: %ds", CHECK_INTERVAL)
        logger.info("  Fail threshold: %d", FAIL_THRESHOLD)
        logger.info("=" * 50)

        # Wait for main agent to start
        logger.info("[Watchdog] Waiting %ds for main agent startup...", STARTUP_DELAY)
        time.sleep(STARTUP_DELAY)

        while True:
            try:
                self._tick()
            except KeyboardInterrupt:
                logger.info("[Watchdog] Shutting down.")
                break
            except Exception as e:
                logger.error("[Watchdog] Unexpected error: %s", e)
                time.sleep(CHECK_INTERVAL)

    def _tick(self) -> None:
        """One check cycle."""
        healthy = self._check_health()

        if healthy:
            if self._consecutive_fails > 0:
                logger.info("[Watchdog] ✅ Main agent recovered (was %d fails)",
                            self._consecutive_fails)
            self._consecutive_fails = 0
            self._maybe_backup()
            time.sleep(CHECK_INTERVAL)
        else:
            self._consecutive_fails += 1
            logger.warning("[Watchdog] ❌ Health check failed (%d/%d)",
                           self._consecutive_fails, FAIL_THRESHOLD)

            if self._consecutive_fails >= FAIL_THRESHOLD:
                self._handle_failure()
                self._consecutive_fails = 0
                time.sleep(COOLDOWN_AFTER_REPAIR)
            else:
                time.sleep(CHECK_INTERVAL)

    def _check_health(self) -> bool:
        """HTTP health check on the main agent."""
        try:
            import urllib.request
            req = urllib.request.Request(HEALTH_URL, method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except Exception:
            return False

    def _handle_failure(self) -> None:
        """Main agent is down. Run repair + restart."""
        # Rate limit repairs
        now = time.time()
        self._repair_timestamps = [t for t in self._repair_timestamps if now - t < 3600]
        if len(self._repair_timestamps) >= self._max_repairs_per_hour:
            logger.error("[Watchdog] ⛔ Max repairs/hour reached (%d). Manual intervention needed.",
                         self._max_repairs_per_hour)
            self._send_telegram_alert(
                "⛔ ArcMind 修復次數上限！1小時內已修復 "
                f"{self._max_repairs_per_hour} 次，需要人工介入。"
            )
            time.sleep(600)  # Wait 10 min before trying again
            return

        # 0. 先確認是否為真正的故障（排除啟動中的假陽性）
        cause = self._read_crash_cause()
        if cause == "":
            # 沒有真正的錯誤，可能是啟動中或暫時超時
            logger.info("[Watchdog] ℹ️ No real error found in stderr, likely startup transient. Skipping repair.")
            return

        logger.warning("[Watchdog] 🔧 Triggering Repair Agent...")

        # 1. Run diagnostics
        try:
            from ops.repair_agent import run_diagnostics
            result = run_diagnostics()
            logger.info("[Watchdog] Repair result: %s", result.summary)
            for c in result.checks:
                logger.info("  [%s] %s: %s", c["status"], c["name"], c.get("detail", ""))
        except Exception as e:
            logger.error("[Watchdog] Repair Agent failed: %s", e)
            result = None

        # 2. 如果基本診斷無法修復，啟動 Smart Repair（Web 搜尋 + 自學習）
        if result and not result.repaired:
            # 先給主 Agent 一次恢復機會
            time.sleep(5)
            if self._check_health():
                logger.info("[Watchdog] ✅ Agent recovered on its own. No restart needed.")
                try:
                    from ops.incident_logger import log_incident
                    log_incident(cause=cause, action=result.summary,
                                 result="Agent 自行恢復，無需重啟", repaired=True)
                except Exception:
                    pass
                return

            # 基本修復不夠 → Smart Repair（Web 搜尋學習）
            logger.info("[Watchdog] 🧠 Basic repair insufficient, invoking Smart Repair...")
            try:
                from ops.smart_repair import smart_repair as do_smart_repair
                sr_result = do_smart_repair()
                logger.info("[Watchdog] Smart Repair status: %s", sr_result.get("status"))

                if sr_result.get("status") == "repaired":
                    action = f"Smart Repair 修復: {sr_result.get('fix', {}).get('fix_action', '?')}"
                    result.repaired = True
                    logger.info("[Watchdog] ✅ Smart Repair succeeded: %s", action)
                elif sr_result.get("status") == "suggestion":
                    fix_info = sr_result.get("fix", {})
                    suggestions = fix_info.get("web_suggestions", [])
                    action = f"Smart Repair 建議: {fix_info.get('fix_action', '?')}"
                    if suggestions:
                        logger.info("[Watchdog] 💡 Web suggestions found:")
                        for s in suggestions[:3]:
                            if isinstance(s, dict):
                                logger.info("  → %s", s.get("title", s.get("body", "")[:80]))
                            else:
                                logger.info("  → %s", str(s)[:80])
                else:
                    action = f"Smart Repair: {sr_result.get('message', 'no fix found')}"
            except Exception as e:
                logger.warning("[Watchdog] Smart Repair failed: %s", e)
                action = result.summary if result else "Repair Agent 執行失敗"
        else:
            action = result.summary if result else "Repair Agent 執行失敗"

        repaired = result.repaired if result else False

        # 3. Log incident
        try:
            from ops.incident_logger import log_incident
            log_incident(
                cause=cause,
                action=action,
                result="已修復並重啟" if repaired else "等待人工介入",
                repaired=repaired,
            )
        except Exception as e:
            logger.error("[Watchdog] Incident logging failed: %s", e)

        # 4. Restart main agent via launchctl
        logger.info("[Watchdog] 🔄 Restarting main agent...")
        try:
            plist = os.path.expanduser("~/Library/LaunchAgents/com.arcmind.server.plist")
            subprocess.run(["launchctl", "unload", plist],
                           capture_output=True, timeout=10)
            time.sleep(3)
            subprocess.run(["launchctl", "load", plist],
                           capture_output=True, timeout=10)
            logger.info("[Watchdog] ✅ Main agent restart command sent")
        except Exception as e:
            logger.error("[Watchdog] Restart failed: %s", e)

        # 5. Send Telegram notification
        smart_note = " (🧠 Smart Repair 已搜尋)" if "Smart Repair" in action else ""
        self._send_telegram_alert(
            f"🔧 ArcMind 故障自愈{smart_note}\n"
            f"原因: {cause[:100]}\n"
            f"修復: {action[:100]}\n"
            f"狀態: {'已修復並重啟' if repaired else '已重啟（可能需要關注）'}"
        )

        self._repair_timestamps.append(now)
        self._repair_count += 1

    # Uvicorn / httpx 正常運行時也會寫入 stderr 的行（這些不算錯誤）
    _BENIGN_PATTERNS = [
        "INFO:",
        "Uvicorn running on",
        "Started server process",
        "Waiting for application startup",
        "Application startup complete",
        "Press CTRL+C to quit",
        "HTTP Request: POST",
        "HTTP Request: GET",
        "lifespan",
    ]

    def _read_crash_cause(self) -> str:
        """Read the last REAL error from stderr log (ignoring INFO/startup lines)."""
        err_log = _ARCMIND_DIR / "logs" / "arcmind_err.log"
        try:
            if err_log.exists():
                content = err_log.read_text(encoding="utf-8", errors="replace")
                lines = content.strip().split("\n")[-30:]

                # 過濾掉正常的 INFO / startup 行
                error_lines = [
                    l for l in lines
                    if not any(bp in l for bp in self._BENIGN_PATTERNS)
                    and l.strip()
                ]

                if not error_lines:
                    # 全部都是正常行，沒有真正的錯誤
                    return ""

                # 找 Traceback
                for i, line in enumerate(error_lines):
                    if "Traceback" in line or "Error" in line or "Exception" in line:
                        return "\n".join(error_lines[i:])[:300]

                return error_lines[-1][:200]
        except Exception:
            pass
        return "主 Agent 無回應（健康檢查連續失敗）"

    def _maybe_backup(self) -> None:
        """Backup configs periodically when healthy."""
        now = time.time()
        if now - self._last_backup < BACKUP_INTERVAL:
            return
        try:
            from ops.repair_agent import backup_configs
            backup_configs()
            self._last_backup = now
            logger.debug("[Watchdog] Config backup completed")
        except Exception as e:
            logger.debug("[Watchdog] Backup failed: %s", e)

    def _send_telegram_alert(self, message: str) -> None:
        """Send alert to Telegram."""
        try:
            token = os.getenv("TELEGRAM_BOT_TOKEN", "")
            chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
            if not token or not chat_id:
                # Try reading from .env
                env_file = _ARCMIND_DIR / ".env"
                if env_file.exists():
                    for line in env_file.read_text().split("\n"):
                        if line.startswith("TELEGRAM_BOT_TOKEN="):
                            token = line.split("=", 1)[1].strip().strip('"')
                        elif line.startswith("TELEGRAM_CHAT_ID="):
                            chat_id = line.split("=", 1)[1].strip().strip('"')

            if token and chat_id:
                import urllib.request
                import urllib.parse
                url = f"https://api.telegram.org/bot{token}/sendMessage"
                data = urllib.parse.urlencode({
                    "chat_id": chat_id,
                    "text": message,
                    "parse_mode": "HTML",
                }).encode()
                req = urllib.request.Request(url, data=data, method="POST")
                urllib.request.urlopen(req, timeout=10)
                logger.info("[Watchdog] Telegram alert sent")
            else:
                logger.warning("[Watchdog] No Telegram credentials for alert")
        except Exception as e:
            logger.warning("[Watchdog] Telegram alert failed: %s", e)


if __name__ == "__main__":
    os.makedirs(str(_ARCMIND_DIR / "logs"), exist_ok=True)
    watchdog = Watchdog()
    watchdog.run_forever()
