# -*- coding: utf-8 -*-
"""
ArcMind — Circuit Breaker
===========================
移植自 ARCHILLX v1.0 multi_agent/circuit_breaker.py。

Rules:
  per-task : >= 3 REJECTs → auto VETO + 10-minute freeze
  global   : >= 5 consecutive VETOs → LIMITED mode (auto-resets after 30 min)
"""
from __future__ import annotations

import logging
import time
from collections import OrderedDict
from enum import Enum
from threading import Lock
from typing import Dict, List

logger = logging.getLogger("arcmind.circuit_breaker")


class SystemMode(str, Enum):
    NORMAL  = "NORMAL"
    LIMITED = "LIMITED"


class CircuitBreaker:
    """Pure in-memory circuit breaker with auto-recovery and bounded memory."""

    _REJECT_THRESHOLD  = 3
    _FREEZE_SECONDS    = 600    # 10 minutes
    _GLOBAL_VETO_LIMIT = 5
    _LIMITED_AUTO_RESET_SECONDS = 1800   # 30 minutes auto-recovery
    _MAX_TRACKED_TASKS = 10_000          # prevent memory leak

    def __init__(self) -> None:
        self._lock = Lock()
        self._reject_counts:     OrderedDict[str, int]   = OrderedDict()
        self._frozen_until:      Dict[str, float] = {}
        self._consecutive_vetos: int              = 0
        self._global_mode:       SystemMode       = SystemMode.NORMAL
        self._limited_since:     float            = 0.0

    def record_reject(self, task_id: str) -> bool:
        """Record REJECT. Returns True when threshold exceeded → freeze."""
        with self._lock:
            self._reject_counts[task_id] = self._reject_counts.get(task_id, 0) + 1
            while len(self._reject_counts) > self._MAX_TRACKED_TASKS:
                self._reject_counts.popitem(last=False)

            if self._reject_counts[task_id] >= self._REJECT_THRESHOLD:
                self._frozen_until[task_id] = time.monotonic() + self._FREEZE_SECONDS
                logger.warning("[CircuitBreaker] Task %s FROZEN for %ds (rejects=%d)",
                               task_id[:16], self._FREEZE_SECONDS, self._reject_counts[task_id])
                return True
            return False

    def is_frozen(self, task_id: str) -> bool:
        with self._lock:
            deadline = self._frozen_until.get(task_id, 0.0)
            if deadline and time.monotonic() < deadline:
                return True
            if task_id in self._frozen_until:
                del self._frozen_until[task_id]
                self._reject_counts.pop(task_id, None)
            return False

    def reject_count(self, task_id: str) -> int:
        with self._lock:
            return self._reject_counts.get(task_id, 0)

    def record_veto(self) -> None:
        with self._lock:
            self._consecutive_vetos += 1
            if self._consecutive_vetos >= self._GLOBAL_VETO_LIMIT:
                self._global_mode = SystemMode.LIMITED
                self._limited_since = time.monotonic()
                logger.warning("[CircuitBreaker] GLOBAL LIMITED MODE (vetos=%d)",
                               self._consecutive_vetos)

    def reset_veto_streak(self) -> None:
        with self._lock:
            self._consecutive_vetos = 0
            self._global_mode = SystemMode.NORMAL
            self._limited_since = 0.0

    @property
    def mode(self) -> SystemMode:
        with self._lock:
            if (self._global_mode == SystemMode.LIMITED
                    and self._limited_since > 0
                    and time.monotonic() - self._limited_since > self._LIMITED_AUTO_RESET_SECONDS):
                logger.info("[CircuitBreaker] AUTO RESET: LIMITED → NORMAL (after %ds)",
                            self._LIMITED_AUTO_RESET_SECONDS)
                self._consecutive_vetos = 0
                self._global_mode = SystemMode.NORMAL
                self._limited_since = 0.0
            return self._global_mode

    @property
    def consecutive_vetos(self) -> int:
        with self._lock:
            return self._consecutive_vetos

    def frozen_tasks(self) -> List[str]:
        with self._lock:
            now = time.monotonic()
            return [t for t, deadline in self._frozen_until.items() if deadline > now]


# Singleton
circuit_breaker = CircuitBreaker()
