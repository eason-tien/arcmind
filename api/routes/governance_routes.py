# -*- coding: utf-8 -*-
"""
ArcMind — Governance API Routes
=================================
暴露 Governor 狀態、Circuit Breaker、Policy Engine、
Approval Gate、Audit Log 等治理層資訊。
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from fastapi import APIRouter

logger = logging.getLogger("arcmind.api.governance")

router = APIRouter()


# ── Governor Status ──────────────────────────────────────────────────────────

@router.get("/status")
async def governance_status():
    """治理層總覽：Governor + Circuit Breaker + Resilience + Policy 統合狀態。"""
    result: dict = {
        "governor": {},
        "circuit_breaker": {},
        "resilience": {},
        "policy": {},
    }

    # Governor
    try:
        from governor.governor import governor
        result["governor"] = {
            "mode": governor.mode,
            "warn_threshold": governor.warn_threshold,
            "block_threshold": governor.block_threshold,
            "eval_count": governor._eval_count,
            "recent_decisions": governor._audit_history[-20:],
        }
    except Exception as e:
        result["governor"] = {"error": str(e)}

    # Circuit Breaker (Governor-level)
    try:
        from governor.circuit_breaker import circuit_breaker
        result["circuit_breaker"] = {
            "global_mode": circuit_breaker.mode.value,
            "consecutive_vetos": circuit_breaker.consecutive_vetos,
            "frozen_tasks": circuit_breaker.frozen_tasks(),
        }
    except Exception as e:
        result["circuit_breaker"] = {"error": str(e)}

    # Task Resilience CB (Skill-level)
    try:
        from runtime.task_resilience import resilience_engine
        result["resilience"] = resilience_engine.get_status()
    except Exception as e:
        result["resilience"] = {"error": str(e)}

    # Policy Engine
    try:
        from runtime.policy_engine import policy_engine
        result["policy"] = {
            "rules_count": len(getattr(policy_engine, '_rules', [])),
            "enabled": True,
        }
    except Exception as e:
        result["policy"] = {"error": str(e), "enabled": False}

    return result


# ── Governor Audit Log ───────────────────────────────────────────────────────

@router.get("/audit")
async def governance_audit(limit: int = 50):
    """Governor 審計日誌（從 JSONL 讀取）。"""
    audit_path = Path(__file__).parent.parent.parent / "logs" / "governor_audit.jsonl"
    entries = []
    try:
        if audit_path.exists():
            with open(audit_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            for line in lines[-limit:]:
                try:
                    entries.append(json.loads(line.strip()))
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        logger.warning("[GovernanceAPI] Failed to read audit log: %s", e)
    return {"entries": entries, "total": len(entries)}


# ── Approval Gate ────────────────────────────────────────────────────────────

@router.get("/approvals")
async def list_approvals():
    """列出所有待審批的 Approval Gate。"""
    try:
        from runtime.approval_gate import approval_gate
        gates = approval_gate.list_pending()
        return {"gates": gates, "total": len(gates)}
    except Exception as e:
        return {"gates": [], "total": 0, "error": str(e)}


@router.post("/approvals/{gate_id}/approve")
async def approve_gate(gate_id: str):
    """核准指定 Approval Gate。"""
    try:
        from runtime.approval_gate import approval_gate
        ok = approval_gate.approve(gate_id)
        return {"gate_id": gate_id, "approved": ok}
    except Exception as e:
        return {"error": str(e)}


@router.post("/approvals/{gate_id}/reject")
async def reject_gate(gate_id: str, reason: str = ""):
    """拒絕指定 Approval Gate。"""
    try:
        from runtime.approval_gate import approval_gate
        ok = approval_gate.reject(gate_id, reason=reason)
        return {"gate_id": gate_id, "rejected": ok}
    except Exception as e:
        return {"error": str(e)}


# ── Circuit Breaker Controls ─────────────────────────────────────────────────

@router.post("/circuit-breaker/reset")
async def reset_governor_cb():
    """重置 Governor Circuit Breaker（清除 veto 計數）。"""
    try:
        from governor.circuit_breaker import circuit_breaker
        circuit_breaker.reset_veto_streak()
        return {"reset": True, "mode": circuit_breaker.mode.value}
    except Exception as e:
        return {"error": str(e)}


@router.post("/circuit-breaker/unfreeze/{task_id}")
async def unfreeze_task(task_id: str):
    """解凍被 Governor CB 凍結的任務。"""
    try:
        from governor.circuit_breaker import circuit_breaker
        with circuit_breaker._lock:
            if task_id in circuit_breaker._frozen_until:
                del circuit_breaker._frozen_until[task_id]
                circuit_breaker._reject_counts.pop(task_id, None)
                return {"task_id": task_id, "unfrozen": True}
            return {"task_id": task_id, "unfrozen": False, "reason": "not_frozen"}
    except Exception as e:
        return {"error": str(e)}
