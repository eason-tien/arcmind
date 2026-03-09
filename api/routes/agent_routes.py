"""
Agent 控制 API：執行指令、查詢狀態
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Any

router = APIRouter()


class RunRequest(BaseModel):
    command: str
    source: str = "user"
    session_id: Optional[int] = None
    goal_id: Optional[int] = None
    context: dict = {}
    skill_hint: Optional[str] = None
    task_type: str = "general"
    budget: str = "medium"


class RunResponse(BaseModel):
    success: bool
    task_id: Optional[int]
    skill_used: Optional[str]
    model_used: Optional[str]
    output: Any
    tokens_used: int
    elapsed_s: float
    governor_approved: bool
    error: Optional[str] = None


@router.post("/run", response_model=RunResponse)
async def run_command(req: RunRequest):
    """
    主入口：使用者下達指令，走完整 OODA 主循環。
    main_loop.run() 是同步阻塞操作，透過 to_thread 避免阻塞 FastAPI event loop。
    """
    from loop.main_loop import main_loop, LoopInput

    inp = LoopInput(
        command=req.command,
        source=req.source,
        session_id=req.session_id,
        goal_id=req.goal_id,
        context=req.context,
        skill_hint=req.skill_hint,
        task_type=req.task_type,
        budget=req.budget,
    )
    result = await asyncio.to_thread(main_loop.run, inp)
    return RunResponse(
        success=result.success,
        task_id=result.task_id,
        skill_used=result.skill_used,
        model_used=result.model_used,
        output=result.output,
        tokens_used=result.tokens_used,
        elapsed_s=result.elapsed_s,
        governor_approved=result.governor_approved,
        error=result.error,
    )


@router.get("/tasks")
def list_open_tasks():
    from runtime.lifecycle import lifecycle
    return {"tasks": lifecycle.tasks.list_open()}


@router.get("/tasks/{task_id}")
def get_task(task_id: int):
    from runtime.lifecycle import lifecycle
    t = lifecycle.tasks.get(task_id)
    if not t:
        raise HTTPException(404, f"Task {task_id} not found")
    return t


@router.get("/agents")
def list_agents():
    from runtime.lifecycle import lifecycle
    return {"agents": lifecycle.agents.list_active()}


@router.get("/lifecycle/summary")
def lifecycle_summary():
    from runtime.lifecycle import lifecycle
    return lifecycle.summary()
