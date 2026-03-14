# -*- coding: utf-8 -*-
"""
V2 Phase 2: PM Escalation REST API Routes
==========================================
Endpoints for viewing and resolving PM escalations.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("arcmind.escalation_routes")

router = APIRouter()


class ResolveRequest(BaseModel):
    decision: str        # continue | skip_step | cancel
    instructions: str = ""


@router.get("/v1/pm/escalations")
async def list_escalations():
    """List all pending PM escalations."""
    from runtime.pm_escalation import pm_escalation
    return {"escalations": pm_escalation.get_pending()}


@router.post("/v1/pm/escalations/{task_id}/resolve")
async def resolve_escalation(task_id: str, req: ResolveRequest):
    """Resolve a pending PM escalation."""
    from runtime.pm_escalation import pm_escalation
    ok = pm_escalation.resolve_escalation(
        task_id=task_id,
        decision=req.decision,
        instructions=req.instructions,
    )
    if not ok:
        raise HTTPException(404, f"No pending escalation for task {task_id}")
    return {"resolved": True, "task_id": task_id}
