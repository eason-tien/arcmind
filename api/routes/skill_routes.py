"""
Skill 管理 API
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, Optional

router = APIRouter()


class InvokeRequest(BaseModel):
    skill: str
    inputs: dict = {}
    session_id: Optional[int] = None


@router.get("/")
def list_skills():
    from runtime.skill_manager import skill_manager
    return {"skills": skill_manager.list_skills()}


@router.get("/{name}")
def get_skill(name: str):
    from runtime.skill_manager import skill_manager
    manifest = skill_manager.get_manifest(name)
    if not manifest:
        raise HTTPException(404, f"Skill '{name}' not found")
    return manifest


@router.post("/invoke")
def invoke_skill(req: InvokeRequest):
    """
    直接呼叫一個 Skill（短路 OODA 循環，適合測試或低風險操作）。
    所有呼叫都需通過 MGIS Governor 審計（fail-closed）。
    """
    from runtime.skill_manager import skill_manager, SkillNotFound
    from foundation.mgis_client import mgis

    audit = mgis.audit(
        action=f"invoke_skill:{req.skill}",
        context={"inputs": req.inputs},
    )
    if not audit.get("approved", False):  # fail-closed: default deny
        raise HTTPException(403, f"Governor blocked: {audit.get('reason', 'unknown')}")

    try:
        result = skill_manager.invoke(req.skill, req.inputs)
        return result
    except SkillNotFound:
        # 嘗試 OpenClaw
        from protocol.openclaw_adapter import openclaw
        if openclaw.enabled:
            return openclaw.invoke_skill(req.skill, req.inputs)
        raise HTTPException(404, f"Skill '{req.skill}' not found locally or in OpenClaw")
    except Exception as e:
        raise HTTPException(500, "Skill invocation failed")
