# -*- coding: utf-8 -*-
"""
ArcMind — Project REST API Routes (V2 Phase 1)
================================================
CRUD endpoints for project management.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger("arcmind.project_routes")

router = APIRouter()


# ── Request Models ───────────────────────────────────────────────────────────

class CreateProjectRequest(BaseModel):
    name: str
    description: str = ""
    session_id: str | None = None
    priority: str = "medium"
    tags: list[str] | None = None


class UpdateProjectRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    priority: str | None = None
    tags: list[str] | None = None


class TransitionRequest(BaseModel):
    status: str


class AddPhaseRequest(BaseModel):
    name: str
    description: str = ""
    order_index: int = 0


class AddTaskRequest(BaseModel):
    description: str
    phase_id: int | None = None
    order_index: int = 0


class AddMilestoneRequest(BaseModel):
    name: str
    phase_id: int | None = None
    due_date: str | None = None
    description: str = ""


class AddRiskRequest(BaseModel):
    description: str
    severity: str = "medium"
    mitigation: str = ""


class GenerateReportRequest(BaseModel):
    report_type: str = "status"


# ── Project CRUD ─────────────────────────────────────────────────────────────

@router.get("/api/projects")
async def list_projects(
    session_id: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
):
    """List projects with optional filters."""
    from runtime.project_registry import project_registry
    projects = project_registry.list_projects(
        session_id=session_id, status=status, limit=limit
    )
    return {"projects": projects, "count": len(projects)}


@router.post("/api/projects")
async def create_project(req: CreateProjectRequest):
    """Create a new project."""
    from runtime.project_registry import project_registry
    project = project_registry.create_project(
        name=req.name,
        description=req.description,
        session_id=req.session_id,
        priority=req.priority,
        tags=req.tags,
    )
    return {"project": project}


@router.get("/api/projects/{project_id}")
async def get_project(project_id: int):
    """Get project details."""
    from runtime.project_registry import project_registry
    project = project_registry.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return {"project": project}


@router.put("/api/projects/{project_id}")
async def update_project(project_id: int, req: UpdateProjectRequest):
    """Update project fields."""
    from runtime.project_registry import project_registry
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    project = project_registry.update_project(project_id, **updates)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return {"project": project}


@router.post("/api/projects/{project_id}/transition")
async def transition_project(project_id: int, req: TransitionRequest):
    """Transition project to new status (state machine enforced)."""
    from runtime.project_registry import project_registry
    try:
        project = project_registry.transition_project(project_id, req.status)
        return {"project": project}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/projects/{project_id}/progress")
async def get_project_progress(project_id: int):
    """Get human-readable project progress."""
    from runtime.project_registry import project_registry
    project = project_registry.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    progress = project_registry.format_project_progress(project_id)
    return {"progress": progress}


# ── Phase Endpoints ──────────────────────────────────────────────────────────

@router.post("/api/projects/{project_id}/phases")
async def add_phase(project_id: int, req: AddPhaseRequest):
    """Add a phase to a project."""
    from runtime.project_registry import project_registry
    try:
        phase = project_registry.add_phase(
            project_id=project_id,
            name=req.name,
            description=req.description,
            order_index=req.order_index,
        )
        return {"phase": phase}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/projects/{project_id}/phases")
async def list_phases(project_id: int):
    """List all phases for a project."""
    from runtime.project_registry import project_registry
    phases = project_registry.list_phases(project_id)
    return {"phases": phases}


@router.post("/api/projects/{project_id}/phases/{phase_id}/complete")
async def complete_phase(project_id: int, phase_id: int):
    """Mark a phase as completed."""
    from runtime.project_registry import project_registry
    try:
        phase = project_registry.complete_phase(project_id, phase_id)
        return {"phase": phase}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Task Endpoints ───────────────────────────────────────────────────────────

@router.post("/api/projects/{project_id}/tasks")
async def add_task(project_id: int, req: AddTaskRequest):
    """Add a task to a project."""
    from runtime.project_registry import project_registry
    task = project_registry.add_task(
        project_id=project_id,
        description=req.description,
        phase_id=req.phase_id,
        order_index=req.order_index,
    )
    return {"task": task}


@router.get("/api/projects/{project_id}/tasks")
async def list_tasks(
    project_id: int,
    phase_id: int | None = Query(None),
):
    """List tasks for a project."""
    from runtime.project_registry import project_registry
    tasks = project_registry.list_tasks(project_id, phase_id=phase_id)
    return {"tasks": tasks, "count": len(tasks)}


# ── Milestone Endpoints ─────────────────────────────────────────────────────

@router.post("/api/projects/{project_id}/milestones")
async def add_milestone(project_id: int, req: AddMilestoneRequest):
    """Add a milestone to a project."""
    from runtime.project_registry import project_registry
    milestone = project_registry.add_milestone(
        project_id=project_id,
        name=req.name,
        phase_id=req.phase_id,
        due_date=req.due_date,
        description=req.description,
    )
    return {"milestone": milestone}


@router.post("/api/projects/{project_id}/milestones/{milestone_id}/complete")
async def complete_milestone(project_id: int, milestone_id: int):
    """Mark a milestone as completed."""
    from runtime.project_registry import project_registry
    try:
        milestone = project_registry.complete_milestone(milestone_id)
        return {"milestone": milestone}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Risk Endpoints ───────────────────────────────────────────────────────────

@router.post("/api/projects/{project_id}/risks")
async def add_risk(project_id: int, req: AddRiskRequest):
    """Add a risk to a project."""
    from runtime.project_registry import project_registry
    risk = project_registry.add_risk(
        project_id=project_id,
        description=req.description,
        severity=req.severity,
        mitigation=req.mitigation,
    )
    return {"risk": risk}


@router.get("/api/projects/{project_id}/risks")
async def list_risks(project_id: int):
    """List risks for a project."""
    from runtime.project_registry import project_registry
    risks = project_registry.list_risks(project_id)
    return {"risks": risks}


# ── Report Endpoints ─────────────────────────────────────────────────────────

@router.get("/api/projects/{project_id}/reports")
async def list_reports(project_id: int):
    """List reports for a project."""
    from runtime.project_registry import project_registry
    reports = project_registry.list_reports(project_id)
    return {"reports": reports}


@router.post("/api/projects/{project_id}/reports")
async def generate_report(project_id: int, req: GenerateReportRequest):
    """Generate a project report."""
    from runtime.project_registry import project_registry
    try:
        report = project_registry.generate_report(
            project_id=project_id,
            report_type=req.report_type,
        )
        return {"report": report}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
