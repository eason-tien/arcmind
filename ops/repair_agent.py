# -*- coding: utf-8 -*-
"""
ArcMind — Repair Agent
========================
輕量故障診斷 + 最小修復。
由 watchdog.py 在偵測到主 Agent 故障時調用。

診斷項目（按優先順序）：
  1. JSON 配置文件損壞 → 從 .bak 還原
  2. MySQL 連線失敗 → 重啟 Docker 容器
  3. Python Import 錯誤 → pip install 缺失模組
  4. Port 被佔用 → kill 佔用進程
  5. Log 文件過大 → rotate
  6. .env 配置損壞 → 從 .bak 還原
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger("arcmind.repair")

_ARCMIND_DIR = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_CONFIG_DIR  = _ARCMIND_DIR / "config"
_LOGS_DIR    = _ARCMIND_DIR / "logs"
_ERR_LOG     = _LOGS_DIR / "arcmind_err.log"
_PORT        = 8100
_MAX_LOG_MB  = 100


class RepairResult:
    def __init__(self):
        self.checks: list[dict] = []
        self.repaired: bool = False
        self.summary: str = ""

    def add(self, name: str, status: str, detail: str = ""):
        self.checks.append({"name": name, "status": status, "detail": detail})
        if status == "REPAIRED":
            self.repaired = True


def run_diagnostics() -> RepairResult:
    """Run all diagnostic checks and attempt repairs."""
    result = RepairResult()

    _check_json_configs(result)
    _check_mysql(result)
    _check_import_errors(result)
    _check_port(result)
    _check_log_size(result)
    _check_env(result)

    repaired_items = [c for c in result.checks if c["status"] == "REPAIRED"]
    failed_items   = [c for c in result.checks if c["status"] == "FAILED"]
    ok_items       = [c for c in result.checks if c["status"] == "OK"]

    if repaired_items:
        result.summary = f"修復 {len(repaired_items)} 項: " + ", ".join(c["name"] for c in repaired_items)
    elif failed_items:
        result.summary = f"無法修復 {len(failed_items)} 項: " + ", ".join(c["name"] for c in failed_items)
    else:
        result.summary = f"全部正常 ({len(ok_items)} 項通過)"

    return result


def _check_json_configs(result: RepairResult) -> None:
    """Check all JSON files in config/ for parse errors."""
    if not _CONFIG_DIR.exists():
        result.add("json_configs", "OK", "No config dir")
        return

    for jf in _CONFIG_DIR.glob("*.json"):
        try:
            with open(jf, "r", encoding="utf-8") as f:
                json.load(f)
        except json.JSONDecodeError as e:
            bak = jf.with_suffix(".json.bak")
            if bak.exists():
                try:
                    # Validate backup first
                    with open(bak, "r", encoding="utf-8") as fb:
                        json.load(fb)
                    shutil.copy2(bak, jf)
                    result.add("json_configs", "REPAIRED",
                               f"{jf.name}: 從 .bak 還原 (原錯: {e})")
                    logger.warning("[Repair] Restored %s from backup", jf.name)
                    continue
                except Exception:
                    pass
            result.add("json_configs", "FAILED",
                       f"{jf.name}: JSON 損壞且無有效備份 ({e})")
            return
        except Exception:
            pass

    result.add("json_configs", "OK")


def _check_mysql(result: RepairResult) -> None:
    """Check MySQL connectivity."""
    try:
        import pymysql
        conn = pymysql.connect(
            host="127.0.0.1", port=3306,
            user="root", password="root123",
            database="arcmind", connect_timeout=5,
        )
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        conn.close()
        result.add("mysql", "OK")
    except Exception as e:
        # Try restarting Docker MySQL
        try:
            subprocess.run(
                ["docker", "restart", "mysql"],
                capture_output=True, timeout=30,
            )
            time.sleep(5)
            # Re-test
            import pymysql
            conn = pymysql.connect(
                host="127.0.0.1", port=3306,
                user="root", password="root123",
                database="arcmind", connect_timeout=5,
            )
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.close()
            conn.close()
            result.add("mysql", "REPAIRED", f"Docker MySQL 重啟成功 (原錯: {e})")
            logger.warning("[Repair] MySQL restarted via Docker")
        except Exception as e2:
            result.add("mysql", "FAILED", f"MySQL 無法連線: {e2}")


def _check_import_errors(result: RepairResult) -> None:
    """Check stderr log for ModuleNotFoundError."""
    if not _ERR_LOG.exists():
        result.add("imports", "OK", "No error log")
        return

    try:
        content = _ERR_LOG.read_text(encoding="utf-8", errors="replace")
        # Only check last 5KB
        content = content[-5000:]
        missing = set(re.findall(r"ModuleNotFoundError: No module named '(\w+)'", content))
        if not missing:
            result.add("imports", "OK")
            return

        pip = str(_ARCMIND_DIR / ".venv" / "bin" / "pip")
        installed = []
        for mod in missing:
            try:
                subprocess.run(
                    [pip, "install", mod],
                    capture_output=True, timeout=60,
                )
                installed.append(mod)
            except Exception:
                pass

        if installed:
            result.add("imports", "REPAIRED", f"安裝: {', '.join(installed)}")
            logger.warning("[Repair] Installed missing modules: %s", installed)
        else:
            result.add("imports", "FAILED", f"缺失模組: {missing}")
    except Exception as e:
        result.add("imports", "OK", f"讀取錯誤日誌失敗: {e}")


def _check_port(result: RepairResult) -> None:
    """Check if port 8100 is occupied by a zombie process."""
    try:
        out = subprocess.run(
            ["lsof", "-ti", f":{_PORT}"],
            capture_output=True, text=True, timeout=5,
        )
        pids = out.stdout.strip().split("\n")
        pids = [p.strip() for p in pids if p.strip()]
        if not pids:
            result.add("port", "OK", f"Port {_PORT} 可用")
            return

        # Check if it's our own process (don't kill it)
        my_pid = str(os.getpid())
        foreign_pids = [p for p in pids if p != my_pid]
        if not foreign_pids:
            result.add("port", "OK", f"Port {_PORT} 由當前進程使用")
            return

        # Kill zombie processes on our port
        for pid in foreign_pids:
            try:
                subprocess.run(["kill", "-9", pid], timeout=5)
            except Exception:
                pass
        time.sleep(1)
        result.add("port", "REPAIRED", f"已清理佔用進程: {foreign_pids}")
        logger.warning("[Repair] Killed zombie PIDs on port %d: %s", _PORT, foreign_pids)
    except Exception as e:
        result.add("port", "OK", f"檢查失敗: {e}")


def _check_log_size(result: RepairResult) -> None:
    """Rotate logs if too large."""
    for log_file in _LOGS_DIR.glob("*.log"):
        try:
            size_mb = log_file.stat().st_size / (1024 * 1024)
            if size_mb > _MAX_LOG_MB:
                rotated = log_file.with_suffix(f".log.{int(time.time())}")
                log_file.rename(rotated)
                log_file.touch()
                result.add("log_rotation", "REPAIRED",
                           f"{log_file.name}: {size_mb:.0f}MB → rotated")
                logger.warning("[Repair] Rotated %s (%.0f MB)", log_file.name, size_mb)
                return
        except Exception:
            pass
    result.add("log_rotation", "OK")


def _check_env(result: RepairResult) -> None:
    """Check .env file existence and basic validity."""
    env_file = _ARCMIND_DIR / ".env"
    env_bak  = _ARCMIND_DIR / ".env.bak"

    if not env_file.exists():
        if env_bak.exists():
            shutil.copy2(env_bak, env_file)
            result.add("env_config", "REPAIRED", ".env 從 .bak 還原")
            logger.warning("[Repair] Restored .env from backup")
        else:
            result.add("env_config", "OK", "No .env (using defaults)")
        return

    try:
        content = env_file.read_text(encoding="utf-8")
        if len(content.strip()) < 5:
            if env_bak.exists():
                shutil.copy2(env_bak, env_file)
                result.add("env_config", "REPAIRED", ".env 為空，從 .bak 還原")
                return
        result.add("env_config", "OK")
    except Exception as e:
        result.add("env_config", "FAILED", str(e))


def backup_configs() -> None:
    """Backup current configs (called when system is healthy)."""
    # JSON configs
    if _CONFIG_DIR.exists():
        for jf in _CONFIG_DIR.glob("*.json"):
            try:
                with open(jf, "r", encoding="utf-8") as f:
                    json.load(f)  # Validate before backing up
                bak = jf.with_suffix(".json.bak")
                shutil.copy2(jf, bak)
            except Exception:
                pass

    # .env
    env_file = _ARCMIND_DIR / ".env"
    if env_file.exists():
        try:
            shutil.copy2(env_file, _ARCMIND_DIR / ".env.bak")
        except Exception:
            pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    r = run_diagnostics()
    print(f"\n{'='*50}")
    print(f"Repair Agent Result: {'REPAIRED' if r.repaired else 'OK'}")
    print(f"Summary: {r.summary}")
    for c in r.checks:
        print(f"  [{c['status']}] {c['name']}: {c.get('detail', '')}")
