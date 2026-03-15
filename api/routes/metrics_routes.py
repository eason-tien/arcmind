# -*- coding: utf-8 -*-
"""
ArcMind — Prometheus Metrics Exporter
=======================================
Zero-dependency /metrics endpoint using plain text exposition format.
Compatible with Prometheus scraping without prometheus_client library.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

from fastapi import APIRouter, Response

logger = logging.getLogger("arcmind.metrics")

router = APIRouter()

_startup_time = time.time()


def _prom_line(name: str, value: Any, help_text: str = "",
               metric_type: str = "gauge", labels: dict | None = None) -> str:
    """Generate Prometheus exposition format lines."""
    lines = []
    if help_text:
        lines.append(f"# HELP {name} {help_text}")
    lines.append(f"# TYPE {name} {metric_type}")
    if labels:
        label_str = ",".join(f'{k}="{v}"' for k, v in labels.items())
        lines.append(f"{name}{{{label_str}}} {value}")
    else:
        lines.append(f"{name} {value}")
    return "\n".join(lines)


@router.get("/metrics")
async def prometheus_metrics():
    """Prometheus-compatible /metrics endpoint."""
    metrics: list[str] = []

    # ── 1. System uptime ──
    uptime = time.time() - _startup_time
    metrics.append(_prom_line(
        "arcmind_uptime_seconds", f"{uptime:.0f}",
        "Seconds since ArcMind server started", "counter"
    ))

    # ── 2. Governor stats ──
    try:
        from governor.governor import governor
        eval_count = governor._eval_count
        history = governor._audit_history
        approved = sum(1 for d in history if d == "APPROVED")
        warned = sum(1 for d in history if d == "WARNED")
        blocked = sum(1 for d in history if d == "BLOCKED")

        metrics.append(_prom_line(
            "arcmind_governor_evaluations_total", eval_count,
            "Total governor evaluations", "counter"
        ))
        metrics.append(_prom_line(
            "arcmind_governor_decisions", approved,
            "Governor decisions by type", "gauge", {"decision": "approved"}
        ))
        metrics.append(_prom_line(
            "arcmind_governor_decisions", warned,
            labels={"decision": "warned"}
        ))
        metrics.append(_prom_line(
            "arcmind_governor_decisions", blocked,
            labels={"decision": "blocked"}
        ))
        metrics.append(_prom_line(
            "arcmind_governor_warn_threshold", governor.warn_threshold,
            "Current adaptive warn threshold"
        ))
    except Exception:
        pass

    # ── 3. Circuit Breaker ──
    try:
        from governor.circuit_breaker import circuit_breaker
        metrics.append(_prom_line(
            "arcmind_circuit_breaker_mode", 1 if circuit_breaker.mode.value == "LIMITED" else 0,
            "Circuit breaker in LIMITED mode (1=yes)"
        ))
        metrics.append(_prom_line(
            "arcmind_circuit_breaker_vetos", circuit_breaker.consecutive_vetos,
            "Consecutive veto count"
        ))
        metrics.append(_prom_line(
            "arcmind_circuit_breaker_frozen_tasks", len(circuit_breaker.frozen_tasks()),
            "Number of currently frozen tasks"
        ))
    except Exception:
        pass

    # ── 4. Task Resilience ──
    try:
        from runtime.task_resilience import resilience_engine
        status = resilience_engine.get_status()
        metrics.append(_prom_line(
            "arcmind_resilience_tracked_skills", status.get("total_skills_tracked", 0),
            "Number of skills being tracked by resilience engine"
        ))
        metrics.append(_prom_line(
            "arcmind_resilience_open_circuits", status.get("open_circuits", 0),
            "Number of open circuit breakers (skill-level)"
        ))
    except Exception:
        pass

    # ── 5. Skill Manager ──
    try:
        from runtime.skill_manager import skill_manager
        metrics.append(_prom_line(
            "arcmind_skills_loaded", len(skill_manager._local),
            "Number of loaded skills"
        ))
    except Exception:
        pass

    # ── 6. Agent Registry ──
    try:
        from runtime.agent_registry import agent_registry
        agents = agent_registry.list_agents() if hasattr(agent_registry, 'list_agents') else []
        active = sum(1 for a in agents if isinstance(a, dict) and a.get("active", True))
        metrics.append(_prom_line(
            "arcmind_agents_active", active,
            "Number of active agents"
        ))
    except Exception:
        pass

    # ── 7. EventBus ──
    try:
        from runtime.event_bus import event_bus
        metrics.append(_prom_line(
            "arcmind_eventbus_processed_total",
            getattr(event_bus, '_processed_count', 0),
            "Total events processed by EventBus", "counter"
        ))
        metrics.append(_prom_line(
            "arcmind_eventbus_dead_letters",
            len(getattr(event_bus, '_dead_letters', [])),
            "Events in dead letter queue"
        ))
    except Exception:
        pass

    # ── 8. Memory ──
    try:
        import psutil
        proc = psutil.Process(os.getpid())
        mem = proc.memory_info()
        metrics.append(_prom_line(
            "arcmind_process_memory_bytes", mem.rss,
            "Process resident memory in bytes"
        ))
        metrics.append(_prom_line(
            "arcmind_process_cpu_percent", proc.cpu_percent(interval=0),
            "Process CPU usage percent"
        ))
    except ImportError:
        pass
    except Exception:
        pass

    body = "\n\n".join(metrics) + "\n"
    return Response(content=body, media_type="text/plain; version=0.0.4; charset=utf-8")
