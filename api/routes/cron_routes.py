"""
Cron 排程 API
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter()


class AddCronRequest(BaseModel):
    name: str
    cron_expr: Optional[str] = None       # "30 21 * * *"
    interval_s: Optional[int] = None      # 秒數（與 cron_expr 二選一）
    skill_name: str
    input_data: dict = {}
    governor_required: bool = True


@router.get("/")
def list_cron_jobs():
    from runtime.cron import cron_system
    return {"jobs": cron_system.list_jobs()}


@router.post("/")
def add_cron_job(req: AddCronRequest):
    from runtime.cron import cron_system
    if not req.cron_expr and not req.interval_s:
        raise HTTPException(400, "Either cron_expr or interval_s is required")

    if req.cron_expr:
        result = cron_system.add_cron(
            req.name, req.cron_expr, req.skill_name,
            req.input_data, req.governor_required,
        )
    else:
        result = cron_system.add_interval(
            req.name, req.interval_s, req.skill_name,
            req.input_data, req.governor_required,
        )
    return result


@router.delete("/{name}")
def remove_cron_job(name: str):
    from runtime.cron import cron_system
    cron_system.remove(name)
    return {"removed": name}


@router.post("/{name}/trigger")
def trigger_cron_job(name: str):
    """手動立即觸發排程工作"""
    from runtime.cron import cron_system
    try:
        cron_system.trigger_now(name)
        return {"triggered": name}
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/{name}/pause")
def pause_cron_job(name: str):
    from runtime.cron import cron_system
    cron_system.pause_job(name)
    return {"paused": name}


@router.post("/{name}/resume")
def resume_cron_job(name: str):
    from runtime.cron import cron_system
    cron_system.resume_job(name)
    return {"resumed": name}
