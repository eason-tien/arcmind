"""
Session & Goal 管理 API
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter()


# ── Session ───────────────────────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    name: str
    context: dict = {}


@router.get("/sessions")
def list_sessions():
    from runtime.lifecycle import lifecycle
    active = lifecycle.sessions.list_active()
    paused = lifecycle.sessions.list_paused()
    return {"active": active, "paused": paused}


@router.post("/sessions")
def create_session(req: CreateSessionRequest):
    from runtime.lifecycle import lifecycle
    sid = lifecycle.sessions.create(req.name, req.context)
    return {"id": sid, "name": req.name, "status": "active"}


@router.get("/sessions/{session_id}")
def get_session(session_id: int):
    from runtime.lifecycle import lifecycle
    s = lifecycle.sessions.get(session_id)
    if not s:
        raise HTTPException(404, f"Session {session_id} not found")
    return s


@router.post("/sessions/{session_id}/pause")
def pause_session(session_id: int):
    from runtime.lifecycle import lifecycle
    lifecycle.sessions.pause(session_id)
    return {"paused": session_id}


@router.post("/sessions/{session_id}/resume")
def resume_session(session_id: int):
    from runtime.lifecycle import lifecycle
    result = lifecycle.sessions.resume(session_id)
    if not result:
        raise HTTPException(404, f"Session {session_id} not found or not paused")
    return result


@router.post("/sessions/{session_id}/end")
def end_session(session_id: int):
    from runtime.lifecycle import lifecycle
    lifecycle.sessions.end(session_id)
    return {"ended": session_id}


# ── Goal ──────────────────────────────────────────────────────────────────────

class CreateGoalRequest(BaseModel):
    title: str
    description: str = ""
    priority: int = 5
    context: dict = {}


class UpdateProgressRequest(BaseModel):
    progress: float     # 0.0–1.0
    notes: Optional[str] = None


@router.get("/goals")
def list_goals():
    from loop.goal_tracker import goal_tracker
    return {"goals": goal_tracker.list_all()}


@router.post("/goals")
def create_goal(req: CreateGoalRequest):
    from loop.goal_tracker import goal_tracker
    gid = goal_tracker.create(
        req.title, req.description, req.priority, req.context
    )
    return {"id": gid, "title": req.title}


@router.get("/goals/{goal_id}")
def get_goal(goal_id: int):
    from loop.goal_tracker import goal_tracker
    g = goal_tracker.get(goal_id)
    if not g:
        raise HTTPException(404, f"Goal {goal_id} not found")
    return g


@router.patch("/goals/{goal_id}/progress")
def update_progress(goal_id: int, req: UpdateProgressRequest):
    from loop.goal_tracker import goal_tracker
    goal_tracker.update_progress(goal_id, req.progress, req.notes)
    return {"updated": goal_id, "progress": req.progress}


@router.post("/goals/{goal_id}/complete")
def complete_goal(goal_id: int):
    from loop.goal_tracker import goal_tracker
    goal_tracker.complete(goal_id)
    return {"completed": goal_id}


@router.post("/goals/{goal_id}/sync_mgis")
def sync_goal_to_mgis(goal_id: int):
    from loop.goal_tracker import goal_tracker
    goal_tracker.sync_to_mgis(goal_id)
    return {"synced": goal_id}
