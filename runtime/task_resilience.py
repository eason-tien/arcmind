# -*- coding: utf-8 -*-
"""
ArcMind — Task Resilience Engine
===================================
任務級韌性引擎：填補進程級 Watchdog 和任務級故障之間的空白。

功能：
  1. Timeout 保護 — 每個 Skill 有最大執行時間
  2. 自動重試 — 指數退避，最多 N 次
  3. 智能診斷 — 分析失敗原因 (timeout/SSL/import/network/OOM)
  4. 自動修復 — 根據診斷結果嘗試修復再重試
  5. 升級通知 — 修復失敗則通知 Telegram + 寫入 incident log
  6. Circuit Breaker — 連續失敗達閾值暫停該 Skill
  7. 狀態追蹤 — 提供全局可觀測性 API

使用方式：
    from runtime.task_resilience import resilience_engine
    result = resilience_engine.execute_with_resilience(
        skill_name="daily_report",
        input_data={"action": "report"},
        timeout_s=180,
        max_retries=2,
    )
"""
from __future__ import annotations

import logging
import os
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger("arcmind.resilience")

_ARCMIND_DIR = Path(__file__).resolve().parent.parent


# ── Failure Types ────────────────────────────────────────────────────────────

class FailureType(Enum):
    TIMEOUT = "timeout"
    SSL_ERROR = "ssl_error"
    IMPORT_ERROR = "import_error"
    NETWORK_ERROR = "network_error"
    DB_ERROR = "db_error"
    PERMISSION_ERROR = "permission_error"
    OOM = "out_of_memory"
    UNKNOWN = "unknown"


@dataclass
class DiagnosisResult:
    failure_type: FailureType
    message: str
    repairable: bool = False
    repair_action: str = ""
    original_error: str = ""


@dataclass
class SkillHealthState:
    """Per-skill health tracking for circuit breaker."""
    name: str
    total_calls: int = 0
    success_count: int = 0
    fail_count: int = 0
    consecutive_failures: int = 0
    last_failure_time: float = 0.0
    last_success_time: float = 0.0
    last_error: str = ""
    circuit_open: bool = False
    circuit_open_until: float = 0.0  # timestamp
    avg_elapsed_s: float = 0.0
    _elapsed_samples: list[float] = field(default_factory=list)

    def record_success(self, elapsed_s: float) -> None:
        self.total_calls += 1
        self.success_count += 1
        self.consecutive_failures = 0
        self.last_success_time = time.time()
        self._elapsed_samples.append(elapsed_s)
        if len(self._elapsed_samples) > 20:
            self._elapsed_samples = self._elapsed_samples[-20:]
        self.avg_elapsed_s = sum(self._elapsed_samples) / len(self._elapsed_samples)
        # Close circuit on success
        if self.circuit_open:
            self.circuit_open = False
            logger.info("[Resilience] ✅ Circuit closed for '%s' (recovered)", self.name)

    def record_failure(self, error: str) -> None:
        self.total_calls += 1
        self.fail_count += 1
        self.consecutive_failures += 1
        self.last_failure_time = time.time()
        self.last_error = error[:200]

    @property
    def success_rate(self) -> float:
        return self.success_count / max(self.total_calls, 1)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "total_calls": self.total_calls,
            "success_count": self.success_count,
            "fail_count": self.fail_count,
            "consecutive_failures": self.consecutive_failures,
            "success_rate": round(self.success_rate, 3),
            "avg_elapsed_s": round(self.avg_elapsed_s, 2),
            "circuit_open": self.circuit_open,
            "last_error": self.last_error,
        }


# ── Task Resilience Engine ───────────────────────────────────────────────────

class TaskResilienceEngine:
    """
    任務級韌性引擎。包裹所有 Skill 執行，提供：
    - Timeout 保護
    - 智能診斷 + 自動修復
    - 指數退避重試
    - Circuit breaker + 自動恢復
    - Telegram 升級通知
    - Incident log 持久化
    """

    # Circuit breaker thresholds
    CB_FAIL_THRESHOLD = 3       # consecutive failures to open circuit
    CB_COOLDOWN_S = 300         # 5 min cooldown before half-open test
    CB_HALF_OPEN_MAX = 1        # max concurrent requests in half-open state

    def __init__(self):
        self._skill_health: dict[str, SkillHealthState] = defaultdict(
            lambda: SkillHealthState(name="")
        )
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="resilience")
        self._lock = threading.Lock()

    def _get_health(self, name: str) -> SkillHealthState:
        with self._lock:
            if name not in self._skill_health:
                self._skill_health[name] = SkillHealthState(name=name)
            return self._skill_health[name]

    # ── Main Entry Point ─────────────────────────────────────────────────

    def execute_with_resilience(
        self,
        skill_name: str,
        input_data: dict,
        timeout_s: int = 120,
        max_retries: int = 2,
        cron_name: str | None = None,
    ) -> dict:
        """
        包裹 Skill 執行，提供完整韌性保護。

        Returns: skill_manager.invoke() 的標準返回格式
                 {success: bool, output: Any, error: str|None, elapsed_s: float}
        """
        health = self._get_health(skill_name)
        label = cron_name or skill_name

        # ── Circuit Breaker 檢查 ──
        if health.circuit_open:
            if time.time() < health.circuit_open_until:
                msg = (f"[Resilience] ⚡ Circuit OPEN for '{label}' "
                       f"(連續 {health.consecutive_failures} 次失敗, "
                       f"冷卻到 {datetime.fromtimestamp(health.circuit_open_until).strftime('%H:%M:%S')})")
                logger.warning(msg)
                return {"success": False, "output": None,
                        "error": f"Circuit breaker open: {health.last_error}",
                        "elapsed_s": 0, "circuit_breaker": True}
            else:
                # Half-open: allow one test request
                logger.info("[Resilience] 🔄 Circuit half-open for '%s', attempting test...", label)

        # ── 重試循環 ──
        last_error = ""
        last_diagnosis: DiagnosisResult | None = None

        for attempt in range(max_retries + 1):
            if attempt > 0:
                backoff = min(2 ** attempt, 30)  # 2, 4, 8... max 30s
                logger.info("[Resilience] ⏳ Retry %d/%d for '%s' (backoff %ds)",
                            attempt, max_retries, label, backoff)
                time.sleep(backoff)

            # Execute with timeout
            start = time.monotonic()
            try:
                result = self._execute_with_timeout(skill_name, input_data, timeout_s)
            except FuturesTimeoutError:
                elapsed = time.monotonic() - start
                last_error = f"Timeout after {timeout_s}s"
                last_diagnosis = self._diagnose(
                    TimeoutError(last_error), skill_name, elapsed
                )
                health.record_failure(last_error)
                logger.warning("[Resilience] ⏰ '%s' timeout (%ds). Diagnosis: %s",
                               label, timeout_s, last_diagnosis.failure_type.value)

                # Attempt repair
                if last_diagnosis.repairable and self._attempt_repair(last_diagnosis, skill_name):
                    logger.info("[Resilience] 🔧 Repair succeeded for '%s', retrying...", label)
                    continue
                continue  # retry without repair

            except Exception as e:
                elapsed = time.monotonic() - start
                last_error = str(e)
                last_diagnosis = self._diagnose(e, skill_name, elapsed)
                health.record_failure(last_error)
                logger.warning("[Resilience] ❌ '%s' error: %s. Diagnosis: %s",
                               label, last_error[:100], last_diagnosis.failure_type.value)

                if last_diagnosis.repairable and self._attempt_repair(last_diagnosis, skill_name):
                    logger.info("[Resilience] 🔧 Repair succeeded for '%s', retrying...", label)
                    continue
                continue

            # ── 檢查 result.success ──
            elapsed = time.monotonic() - start
            if result.get("success"):
                health.record_success(elapsed)
                logger.info("[Resilience] ✅ '%s' succeeded (%.1fs, attempt %d)",
                            label, elapsed, attempt + 1)
                return result
            else:
                # Skill returned success=False (handled error)
                error_msg = result.get("error", "Unknown skill error")
                last_error = error_msg
                last_diagnosis = self._diagnose(
                    Exception(error_msg), skill_name, elapsed
                )
                health.record_failure(error_msg)
                logger.warning("[Resilience] ❌ '%s' returned failure: %s",
                               label, error_msg[:100])

                if last_diagnosis.repairable and self._attempt_repair(last_diagnosis, skill_name):
                    continue
                if attempt < max_retries:
                    continue
                # Fall through to escalation

        # ── 所有重試耗盡 → 升級 ──
        self._open_circuit(health)
        self._escalate(
            skill_name=skill_name,
            cron_name=cron_name,
            error=last_error,
            diagnosis=last_diagnosis,
            attempts=max_retries + 1,
        )

        return {"success": False, "output": None,
                "error": f"All {max_retries + 1} attempts failed: {last_error}",
                "elapsed_s": 0, "escalated": True}

    # ── Timeout Execution ────────────────────────────────────────────────

    def _execute_with_timeout(self, skill_name: str, input_data: dict,
                               timeout_s: int) -> dict:
        """在獨立線程中執行 Skill，超過 timeout_s 則拋出 TimeoutError。"""
        from runtime.skill_manager import skill_manager
        future = self._executor.submit(skill_manager.invoke, skill_name, input_data)
        return future.result(timeout=timeout_s)

    # ── Diagnosis ────────────────────────────────────────────────────────

    def _diagnose(self, error: Exception, skill_name: str,
                  elapsed_s: float) -> DiagnosisResult:
        """分析失敗原因，返回結構化診斷結果。"""
        err_str = str(error).lower()
        err_type = type(error).__name__.lower()

        # Timeout
        if isinstance(error, (TimeoutError, FuturesTimeoutError)) or "timeout" in err_str:
            return DiagnosisResult(
                failure_type=FailureType.TIMEOUT,
                message=f"Skill '{skill_name}' exceeded {elapsed_s:.0f}s",
                repairable=False,
                original_error=str(error)[:200],
            )

        # SSL
        if "ssl" in err_str or "certificate" in err_str:
            return DiagnosisResult(
                failure_type=FailureType.SSL_ERROR,
                message="SSL certificate verification failed",
                repairable=True,
                repair_action="install_certifi",
                original_error=str(error)[:200],
            )

        # Import
        if "modulenotfounderror" in err_type or "no module named" in err_str:
            module = ""
            if "'" in str(error):
                parts = str(error).split("'")
                module = parts[1] if len(parts) > 1 else ""
            return DiagnosisResult(
                failure_type=FailureType.IMPORT_ERROR,
                message=f"Missing module: {module}",
                repairable=True,
                repair_action=f"pip_install:{module}",
                original_error=str(error)[:200],
            )

        # Network
        if any(kw in err_str for kw in ["connection", "network", "urlopen", "socket"]):
            return DiagnosisResult(
                failure_type=FailureType.NETWORK_ERROR,
                message="Network connectivity issue",
                repairable=False,
                original_error=str(error)[:200],
            )

        # Database
        if any(kw in err_str for kw in ["mysql", "database", "sqlalchemy", "operationalerror"]):
            return DiagnosisResult(
                failure_type=FailureType.DB_ERROR,
                message="Database connection error",
                repairable=True,
                repair_action="restart_mysql",
                original_error=str(error)[:200],
            )

        # Memory
        if "memoryerror" in err_type or "oom" in err_str or "killed" in err_str:
            return DiagnosisResult(
                failure_type=FailureType.OOM,
                message="Out of memory",
                repairable=False,
                original_error=str(error)[:200],
            )

        # Unknown
        return DiagnosisResult(
            failure_type=FailureType.UNKNOWN,
            message=f"Unclassified error in '{skill_name}'",
            repairable=False,
            original_error=str(error)[:200],
        )

    # ── Self-Repair ──────────────────────────────────────────────────────

    def _attempt_repair(self, diagnosis: DiagnosisResult,
                         skill_name: str) -> bool:
        """根據診斷結果嘗試自動修復。返回 True 表示修復成功。"""
        logger.info("[Resilience] 🔧 Attempting repair: %s for '%s'",
                    diagnosis.repair_action, skill_name)
        try:
            if diagnosis.repair_action == "install_certifi":
                return self._repair_ssl()
            elif diagnosis.repair_action.startswith("pip_install:"):
                module = diagnosis.repair_action.split(":", 1)[1]
                return self._repair_import(module)
            elif diagnosis.repair_action == "restart_mysql":
                return self._repair_mysql()
        except Exception as e:
            logger.warning("[Resilience] Repair failed: %s", e)
        return False

    def _repair_ssl(self) -> bool:
        """嘗試安裝 certifi 修復 SSL 問題。"""
        import subprocess
        pip = str(_ARCMIND_DIR / ".venv" / "bin" / "pip")
        if not os.path.exists(pip):
            pip = "pip3"
        try:
            subprocess.run(
                [pip, "install", "certifi"],
                capture_output=True, timeout=60,
            )
            logger.info("[Resilience] ✅ certifi installed")
            return True
        except Exception as e:
            logger.warning("[Resilience] certifi install failed: %s", e)
            return False

    def _repair_import(self, module: str) -> bool:
        """嘗試 pip install 缺失模組（安全白名單檢查）。"""
        _SAFE_MODULES = {
            "anthropic", "openai", "httpx", "pydantic", "pydantic_settings",
            "uvicorn", "fastapi", "starlette", "yaml", "pyyaml", "dotenv",
            "python-dotenv", "chromadb", "apscheduler", "requests", "aiohttp",
            "websockets", "psutil", "tiktoken", "numpy", "pillow",
            "edge_tts", "certifi",
        }
        if module.lower() not in _SAFE_MODULES:
            logger.warning("[Resilience] Module '%s' not in safe list, skipping", module)
            return False

        import subprocess
        pip = str(_ARCMIND_DIR / ".venv" / "bin" / "pip")
        if not os.path.exists(pip):
            pip = "pip3"
        try:
            subprocess.run(
                [pip, "install", "--no-deps", module],
                capture_output=True, timeout=120,
            )
            logger.info("[Resilience] ✅ Module '%s' installed", module)
            return True
        except Exception as e:
            logger.warning("[Resilience] pip install '%s' failed: %s", module, e)
            return False

    def _repair_mysql(self) -> bool:
        """嘗試重啟 Docker MySQL。"""
        import subprocess
        try:
            subprocess.run(
                ["docker", "restart", "mysql"],
                capture_output=True, timeout=30,
            )
            time.sleep(5)
            logger.info("[Resilience] ✅ MySQL Docker container restarted")
            return True
        except Exception as e:
            logger.warning("[Resilience] MySQL restart failed: %s", e)
            return False

    # ── Circuit Breaker ──────────────────────────────────────────────────

    def _open_circuit(self, health: SkillHealthState) -> None:
        """連續失敗達閾值 → 打開 Circuit Breaker。"""
        if health.consecutive_failures >= self.CB_FAIL_THRESHOLD:
            health.circuit_open = True
            health.circuit_open_until = time.time() + self.CB_COOLDOWN_S
            logger.warning(
                "[Resilience] ⚡ Circuit OPENED for '%s' "
                "(consecutive_failures=%d, cooldown=%ds)",
                health.name, health.consecutive_failures, self.CB_COOLDOWN_S,
            )

    # ── Escalation ───────────────────────────────────────────────────────

    def _escalate(
        self,
        skill_name: str,
        cron_name: str | None,
        error: str,
        diagnosis: DiagnosisResult | None,
        attempts: int,
    ) -> None:
        """修復失敗 → Telegram 通知 + Incident Log + EventBus。"""
        label = cron_name or skill_name
        failure_type = diagnosis.failure_type.value if diagnosis else "unknown"

        # 1. Incident log
        try:
            from ops.incident_logger import log_incident
            log_incident(
                cause=f"Task '{label}' failed ({failure_type}): {error[:100]}",
                action=f"Attempted {attempts} retries"
                       + (f", repair: {diagnosis.repair_action}" if diagnosis and diagnosis.repair_action else ""),
                result="所有重試失敗，已通知用戶",
                repaired=False,
            )
        except Exception as e:
            logger.warning("[Resilience] Incident log failed: %s", e)

        # 2. EventBus — emit TASK_FAILED event
        try:
            from runtime.event_bus import event_bus, Event, EventType, EventPriority
            event_bus.emit(Event(
                type=EventType.TASK_FAILED,
                source=f"resilience:{skill_name}",
                payload={
                    "skill_name": skill_name,
                    "cron_name": cron_name,
                    "error": error[:200],
                    "failure_type": failure_type,
                    "attempts": attempts,
                    "diagnosis": diagnosis.message if diagnosis else "",
                },
                priority=EventPriority.HIGH,
            ))
        except Exception as e:
            logger.warning("[Resilience] EventBus emit failed: %s", e)

        # 3. Telegram alert
        self._send_telegram_alert(
            f"⚠️ ArcMind 任務失敗\n"
            f"任務: {label}\n"
            f"類型: {failure_type}\n"
            f"錯誤: {error[:100]}\n"
            f"重試: {attempts} 次均失敗\n"
            f"{"修復: " + diagnosis.repair_action if diagnosis and diagnosis.repair_action else "無可用修復"}\n"
            f"狀態: Circuit Breaker 已開啟 ({self.CB_COOLDOWN_S}s 冷卻)"
        )

    def _send_telegram_alert(self, message: str) -> None:
        """發送 Telegram 告警。"""
        try:
            from config.settings import settings
            token = getattr(settings, "telegram_bot_token", "")
            chat_id = getattr(settings, "telegram_chat_id", "")
            if not token or not chat_id:
                logger.warning("[Resilience] No Telegram credentials for alert")
                return

            import urllib.parse
            import urllib.request
            import ssl as _ssl
            ctx = _ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = _ssl.CERT_NONE

            url = f"https://api.telegram.org/bot{token}/sendMessage"
            data = urllib.parse.urlencode({
                "chat_id": chat_id,
                "text": message,
            }).encode()
            req = urllib.request.Request(url, data=data, method="POST")
            urllib.request.urlopen(req, timeout=10, context=ctx)
            logger.info("[Resilience] 📱 Telegram alert sent")
        except Exception as e:
            logger.warning("[Resilience] Telegram alert failed: %s", e)

    # ── Observability API ────────────────────────────────────────────────

    def get_status(self) -> dict:
        """返回所有 Skill 的健康狀態（供 /v1/resilience/status API 使用）。"""
        with self._lock:
            skills = []
            for name, h in self._skill_health.items():
                skills.append(h.to_dict())

            open_circuits = [s for s in skills if s["circuit_open"]]
            total_calls = sum(s["total_calls"] for s in skills)
            total_failures = sum(s["fail_count"] for s in skills)

            return {
                "total_skills_tracked": len(skills),
                "total_calls": total_calls,
                "total_failures": total_failures,
                "overall_success_rate": round(
                    (total_calls - total_failures) / max(total_calls, 1), 3
                ),
                "open_circuits": len(open_circuits),
                "open_circuit_skills": [s["name"] for s in open_circuits],
                "skills": sorted(skills, key=lambda s: s["fail_count"], reverse=True),
            }

    def reset_circuit(self, skill_name: str) -> bool:
        """手動重置某 Skill 的 Circuit Breaker。"""
        health = self._get_health(skill_name)
        if health.circuit_open:
            health.circuit_open = False
            health.consecutive_failures = 0
            logger.info("[Resilience] 🔄 Circuit manually reset for '%s'", skill_name)
            return True
        return False


# ── Global singleton ──────────────────────────────────────────────────────────

resilience_engine = TaskResilienceEngine()
