"""
Skill 協議資料結構 — 相容 OpenClaw Skill 格式。
ArcMind 本地 Skill 使用相同 YAML manifest 格式，可雙向互操作。
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class PermissionType(str, Enum):
    NETWORK = "network"
    FILESYSTEM = "filesystem"
    EXEC = "exec"
    BROWSER = "browser"
    MEMORY = "memory"
    GOVERNANCE = "governance"


class InputField(BaseModel):
    name: str
    type: str = "string"
    required: bool = True
    description: str = ""
    default: Any = None


class OutputField(BaseModel):
    name: str
    type: str = "string"
    description: str = ""


class SkillManifest(BaseModel):
    """
    Skill 描述清單，格式相容 OpenClaw。
    可直接從 YAML 解析。
    """
    name: str
    version: str = "1.0"
    description: str = ""
    author: str = "arcmind"
    source: Literal["local", "openclaw"] = "local"
    handler: str = "run"
    module: Optional[str] = None
    inputs: list[InputField] = Field(default_factory=list)
    outputs: list[OutputField] = Field(default_factory=list)
    permissions: list[PermissionType] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    governor_required: bool = True
    timeout_s: int = 60

    def requires_network(self) -> bool:
        return PermissionType.NETWORK in self.permissions

    def requires_browser(self) -> bool:
        return PermissionType.BROWSER in self.permissions

    def requires_exec(self) -> bool:
        return PermissionType.EXEC in self.permissions


class SkillInvokeRequest(BaseModel):
    """呼叫 Skill 的請求格式（本地 or OpenClaw 相同格式）"""
    skill: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    session_id: Optional[int] = None
    task_id: Optional[int] = None
    timeout_s: int = 60
    governor_bypass: bool = False  # 只有 MGIS 審計已通過才能設 True


class SkillResult(BaseModel):
    """Skill 執行結果"""
    success: bool
    skill: str
    output: Any = None
    error: Optional[str] = None
    elapsed_s: float = 0.0
    model_used: Optional[str] = None
    tokens_used: int = 0


class DispatchContract(BaseModel):
    """
    任務派單契約 — 相容 MGIS PDE DispatchContract 格式。
    9 種 role 類型。
    """
    task_id: str
    project_id: str
    title: str
    description: str
    role: Literal[
        "PLANNER", "ACQUIRER", "BUILDER", "EXECUTOR", "VERIFIER",
        "AUDITOR_UI", "AUDITOR_CODE", "AUDITOR_SEC", "AUDITOR_PERF"
    ]
    skill_hint: Optional[str] = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    priority: int = 5
    deadline: Optional[str] = None
