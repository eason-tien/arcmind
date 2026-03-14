#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ArcMind — Unified Launcher
==============================
單一入口點：Pre-flight 檢查 → 自我修復 → 主服務 → 內嵌 Watchdog。

Usage:
  python arcmind_launcher.py              # 標準啟動
  python arcmind_launcher.py --port 8100  # 指定 port
  python arcmind_launcher.py --no-watchdog  # 不啟動 watchdog
  python arcmind_launcher.py --preflight-only  # 只跑 pre-flight 不啟動
"""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

# ── Bootstrap ────────────────────────────────────────────────────────────────
_ARCMIND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_ARCMIND_DIR))
os.chdir(_ARCMIND_DIR)

LOG_DIR = _ARCMIND_DIR / "logs"
PID_FILE = LOG_DIR / "arcmind.pid"


def setup_logging() -> None:
    LOG_DIR.mkdir(exist_ok=True)
    fmt = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
    formatter = logging.Formatter(fmt)

    file_handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / "arcmind.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    handlers: list[logging.Handler] = [file_handler]
    if sys.stdout.isatty():
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(formatter)
        handlers.append(console)

    logging.basicConfig(level=logging.INFO, format=fmt, handlers=handlers)


logger = logging.getLogger("arcmind.launcher")


# ═══════════════════════════════════════════════════════════════════════════════
# PRE-FLIGHT CHECKS
# ═══════════════════════════════════════════════════════════════════════════════

class PreflightResult:
    def __init__(self):
        self.checks: list[dict] = []
        self.blocked = False
        self.repaired = False

    def add(self, name: str, status: str, detail: str = ""):
        self.checks.append({"name": name, "status": status, "detail": detail})
        if status == "BLOCKED":
            self.blocked = True
        if status == "REPAIRED":
            self.repaired = True

    def summary(self) -> str:
        ok = sum(1 for c in self.checks if c["status"] == "OK")
        repaired = sum(1 for c in self.checks if c["status"] == "REPAIRED")
        blocked = sum(1 for c in self.checks if c["status"] == "BLOCKED")
        return f"OK={ok} REPAIRED={repaired} BLOCKED={blocked}"


def run_preflight(port: int) -> PreflightResult:
    """Run all pre-flight checks before starting ArcMind."""
    result = PreflightResult()

    logger.info("=" * 60)
    logger.info("  🛫 ArcMind Pre-flight Check")
    logger.info("=" * 60)

    # 1. PID Lock — 重複實例偵測
    _check_pid_lock(result)

    # 2. Port 可用性 — zombie 進程清理
    _check_port_available(result, port)

    # 3. 自我修復 — 呼叫 repair_agent
    _run_self_repair(result)

    # 4. 關鍵檔案檢查
    _check_critical_files(result)

    # 5. 日誌清理
    _check_log_cleanup(result)

    # Report
    logger.info("-" * 60)
    for c in result.checks:
        icon = {"OK": "✅", "REPAIRED": "🔧", "BLOCKED": "❌"}.get(c["status"], "❓")
        detail = f" — {c['detail']}" if c['detail'] else ""
        logger.info("  %s [%s] %s%s", icon, c["status"], c["name"], detail)
    logger.info("-" * 60)
    logger.info("  Pre-flight: %s", result.summary())
    logger.info("=" * 60)

    return result


def _check_pid_lock(result: PreflightResult) -> None:
    """Check for stale PID lock file."""
    if not PID_FILE.exists():
        result.add("pid_lock", "OK", "No existing PID")
        return

    try:
        old_pid = int(PID_FILE.read_text().strip())
        # Check if process is still running
        try:
            os.kill(old_pid, 0)  # signal 0 = check existence
            # Process exists — is it ArcMind?
            try:
                ps_out = subprocess.run(
                    ["ps", "-p", str(old_pid), "-o", "comm="],
                    capture_output=True, text=True, timeout=5,
                )
                proc_name = ps_out.stdout.strip()
                if "python" in proc_name.lower():
                    result.add("pid_lock", "BLOCKED",
                               f"ArcMind already running (PID {old_pid})")
                    return
            except Exception:
                pass
            # Not our process, stale PID
            PID_FILE.unlink(missing_ok=True)
            result.add("pid_lock", "REPAIRED", f"Stale PID {old_pid} cleared")
        except ProcessLookupError:
            # Process doesn't exist — stale PID file
            PID_FILE.unlink(missing_ok=True)
            result.add("pid_lock", "REPAIRED", f"Stale PID {old_pid} cleared")
        except PermissionError:
            result.add("pid_lock", "OK", f"PID {old_pid} exists but no permission to check")
    except Exception as e:
        PID_FILE.unlink(missing_ok=True)
        result.add("pid_lock", "REPAIRED", f"Corrupt PID file cleared: {e}")


def _check_port_available(result: PreflightResult, port: int) -> None:
    """Check if port is available, kill zombie processes if needed."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(1)
        err = sock.connect_ex(("127.0.0.1", port))
        if err != 0:
            result.add("port", "OK", f"Port {port} available")
            return

        # Port is occupied — try to find and kill zombie
        try:
            out = subprocess.run(
                ["/usr/sbin/lsof", "-ti", f":{port}"],
                capture_output=True, text=True, timeout=5,
            )
            pids = [p.strip() for p in out.stdout.strip().split("\n") if p.strip()]
            if pids:
                for pid in pids:
                    try:
                        subprocess.run(["kill", "-15", pid], timeout=5)
                    except Exception:
                        pass
                time.sleep(2)
                # Force kill if still alive
                for pid in pids:
                    try:
                        subprocess.run(["kill", "-9", pid], timeout=5)
                    except Exception:
                        pass
                result.add("port", "REPAIRED", f"Killed zombie on port {port}: PIDs {pids}")
                logger.warning("[Preflight] Killed zombie processes on port %d: %s", port, pids)
            else:
                result.add("port", "BLOCKED", f"Port {port} occupied but can't find PID")
        except Exception as e:
            result.add("port", "BLOCKED", f"Port {port} occupied: {e}")
    finally:
        sock.close()


def _run_self_repair(result: PreflightResult) -> None:
    """Run repair agent diagnostics."""
    try:
        from ops.repair_agent import run_diagnostics, backup_configs
        repair_result = run_diagnostics()
        if repair_result.repaired:
            result.add("self_repair", "REPAIRED", repair_result.summary)
        else:
            result.add("self_repair", "OK", repair_result.summary)
    except Exception as e:
        result.add("self_repair", "OK", f"Repair agent unavailable: {e}")


def _check_critical_files(result: PreflightResult) -> None:
    """Check critical files exist."""
    critical = [".env", "config/settings.py", "api/server.py", "loop/main_loop.py"]
    missing = [f for f in critical if not (_ARCMIND_DIR / f).exists()]
    if missing:
        result.add("critical_files", "BLOCKED", f"Missing: {', '.join(missing)}")
    else:
        result.add("critical_files", "OK", f"{len(critical)} files present")


def _check_log_cleanup(result: PreflightResult) -> None:
    """Clean up oversized log files on startup."""
    max_mb = 50
    rotated = []
    for log_file in LOG_DIR.glob("*.log"):
        try:
            size_mb = log_file.stat().st_size / (1024 * 1024)
            if size_mb > max_mb:
                rotated_name = log_file.with_suffix(f".log.{int(time.time())}")
                log_file.rename(rotated_name)
                log_file.touch()
                rotated.append(f"{log_file.name} ({size_mb:.0f}MB)")
        except Exception:
            pass
    if rotated:
        result.add("log_cleanup", "REPAIRED", f"Rotated: {', '.join(rotated)}")
    else:
        result.add("log_cleanup", "OK")


# ═══════════════════════════════════════════════════════════════════════════════
# EMBEDDED WATCHDOG
# ═══════════════════════════════════════════════════════════════════════════════

class EmbeddedWatchdog(threading.Thread):
    """
    Background health monitor thread.
    Checks /health endpoint periodically and triggers repair if needed.
    """

    def __init__(self, port: int, check_interval: int = 30, fail_threshold: int = 3):
        super().__init__(daemon=True, name="arcmind-watchdog")
        self.port = port
        self.check_interval = check_interval
        self.fail_threshold = fail_threshold
        self._consecutive_fails = 0
        self._running = True
        self._startup_delay = 15  # wait for server to initialize

    def run(self):
        logger.info("[Watchdog] Started (interval=%ds, threshold=%d)",
                    self.check_interval, self.fail_threshold)
        time.sleep(self._startup_delay)

        while self._running:
            try:
                healthy = self._health_check()
                if healthy:
                    self._consecutive_fails = 0
                    # Backup configs when healthy (every 5 min)
                    try:
                        from ops.repair_agent import backup_configs
                        backup_configs()
                    except Exception:
                        pass
                else:
                    self._consecutive_fails += 1
                    logger.warning("[Watchdog] Health check failed (%d/%d)",
                                   self._consecutive_fails, self.fail_threshold)
                    if self._consecutive_fails >= self.fail_threshold:
                        self._trigger_repair()
                        self._consecutive_fails = 0
            except Exception as e:
                logger.error("[Watchdog] Error: %s", e)

            time.sleep(self.check_interval)

    def stop(self):
        self._running = False

    def _health_check(self) -> bool:
        """Check /health endpoint."""
        import urllib.request
        try:
            url = f"http://127.0.0.1:{self.port}/health"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except Exception:
            return False

    def _trigger_repair(self):
        """Run repair agent when health checks fail."""
        logger.warning("[Watchdog] Triggering self-repair...")
        try:
            from ops.repair_agent import run_diagnostics
            repair = run_diagnostics()
            logger.warning("[Watchdog] Repair result: %s", repair.summary)

            # Log incident
            try:
                from ops.incident_logger import log_incident
                log_incident(
                    cause="Watchdog detected consecutive health check failures",
                    action=repair.summary,
                    resolved=repair.repaired,
                )
            except Exception:
                pass
        except Exception as e:
            logger.error("[Watchdog] Repair failed: %s", e)


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN LAUNCHER
# ═══════════════════════════════════════════════════════════════════════════════

def write_pid():
    """Write current PID to lock file."""
    PID_FILE.write_text(str(os.getpid()))


def cleanup_pid(*_args):
    """Remove PID file on exit."""
    PID_FILE.unlink(missing_ok=True)


def main() -> None:
    setup_logging()

    parser = argparse.ArgumentParser(description="ArcMind Unified Launcher")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--reload", action="store_true",
                        help="Enable auto-reload (development)")
    parser.add_argument("--no-watchdog", action="store_true",
                        help="Disable embedded watchdog")
    parser.add_argument("--preflight-only", action="store_true",
                        help="Run pre-flight checks only, don't start server")
    args = parser.parse_args()

    # Load settings
    from config.settings import settings
    host = args.host or settings.arcmind_host
    port = args.port or settings.arcmind_port

    # ── Pre-flight ──
    preflight = run_preflight(port)

    if args.preflight_only:
        sys.exit(0 if not preflight.blocked else 1)

    if preflight.blocked:
        logger.error("❌ Pre-flight BLOCKED — cannot start ArcMind")
        for c in preflight.checks:
            if c["status"] == "BLOCKED":
                logger.error("   → %s: %s", c["name"], c["detail"])
        sys.exit(1)

    # ── PID Lock ──
    write_pid()
    signal.signal(signal.SIGTERM, lambda *a: (cleanup_pid(), sys.exit(0)))
    signal.signal(signal.SIGINT, lambda *a: (cleanup_pid(), sys.exit(0)))
    import atexit
    atexit.register(cleanup_pid)

    # ── Start Server ──
    from version import __version__
    logger.info("=" * 60)
    logger.info("  🧠 ArcMind v%s (Unified Launcher)", __version__)
    logger.info("  Listen: http://%s:%d", host, port)
    logger.info("  Watchdog: %s", "disabled" if args.no_watchdog else "enabled")
    logger.info("  Pre-flight: %s", preflight.summary())
    if preflight.repaired:
        logger.info("  🔧 Self-repair performed during pre-flight")
    logger.info("=" * 60)

    # ── Embedded Watchdog ──
    watchdog = None
    if not args.no_watchdog:
        watchdog = EmbeddedWatchdog(port=port)
        watchdog.start()

    # ── Launch uvicorn ──
    try:
        import uvicorn
        from api.server import create_app
        app = create_app()

        # Check for recent incidents
        try:
            from ops.incident_logger import get_recent_incidents
            incidents = get_recent_incidents(limit=3)
            if incidents:
                logger.warning("  ⚠️  Recent incidents: %d", len(incidents))
        except Exception:
            pass

        uvicorn.run(
            app,
            host=host,
            port=port,
            reload=args.reload,
            log_level="info",
            log_config=None,
        )
    except Exception as e:
        logger.exception("❌ ArcMind crashed: %s", e)
        # Trigger repair on crash
        try:
            from ops.repair_agent import run_diagnostics
            repair = run_diagnostics()
            logger.info("🔧 Post-crash repair: %s", repair.summary)
        except Exception:
            pass
        raise
    finally:
        if watchdog:
            watchdog.stop()
        cleanup_pid()


if __name__ == "__main__":
    main()
