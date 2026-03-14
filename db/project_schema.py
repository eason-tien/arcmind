# -*- coding: utf-8 -*-
"""
ArcMind — Project Schema (V2 Phase 1)
=======================================
Project-level management tables for Factory JARVIS V2 architecture.
Import this module so Base.metadata.create_all() auto-creates tables.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Column, DateTime, ForeignKey, Integer, String, Text, Float,
)

from db.schema import Base


# ── Status Constants ─────────────────────────────────────────────────────────

class ProjectStatus:
    """10-state project lifecycle."""
    PROPOSED = "proposed"
    PLANNING = "planning"
    IN_PROGRESS = "in_progress"
    ON_HOLD = "on_hold"
    REVIEW = "review"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    ARCHIVED = "archived"
    CLOSED = "closed"

    ALL = [
        PROPOSED, PLANNING, IN_PROGRESS, ON_HOLD, REVIEW,
        COMPLETED, CANCELLED, FAILED, ARCHIVED, CLOSED,
    ]


class PhaseStatus:
    """Phase lifecycle."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"

    ALL = [PENDING, IN_PROGRESS, COMPLETED, SKIPPED]


class ProjectTaskStatus:
    """Task within project lifecycle."""
    PENDING = "pending"
    ASSIGNED = "assigned"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    ALL = [PENDING, ASSIGNED, EXECUTING, COMPLETED, FAILED, CANCELLED]


class MilestoneStatus:
    """Milestone lifecycle."""
    PENDING = "pending"
    COMPLETED = "completed"
    MISSED = "missed"

    ALL = [PENDING, COMPLETED, MISSED]


class RiskSeverity:
    """Risk severity levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    ALL = [LOW, MEDIUM, HIGH, CRITICAL]


class RiskStatus:
    """Risk lifecycle."""
    IDENTIFIED = "identified"
    MITIGATED = "mitigated"
    ACCEPTED = "accepted"
    CLOSED = "closed"

    ALL = [IDENTIFIED, MITIGATED, ACCEPTED, CLOSED]


class PMAgentStatus:
    """10-state PM Agent lifecycle."""
    IDLE = "idle"
    ASSIGNED = "assigned"
    PLANNING = "planning"
    EXECUTING = "executing"
    REPORTING = "reporting"
    WAITING = "waiting"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    TERMINATED = "terminated"

    ALL = [
        IDLE, ASSIGNED, PLANNING, EXECUTING, REPORTING,
        WAITING, BLOCKED, COMPLETED, FAILED, TERMINATED,
    ]


# ── ORM Models ──────────────────────────────────────────────────────────────

class Project_(Base):
    """Project registry — top-level project entity."""
    __tablename__ = "am_projects"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    name             = Column(String(256), nullable=False)
    description      = Column(Text, default="")
    status           = Column(String(32), default=ProjectStatus.PROPOSED)
    priority         = Column(String(16), default="medium")   # low|medium|high|critical
    owner_session_id = Column(String(128), nullable=True)     # session that created it
    tags             = Column(Text, default="[]")             # JSON list
    metadata_        = Column(Text, default="{}")             # JSON
    progress         = Column(Float, default=0.0)             # 0.0–1.0
    created_at       = Column(DateTime, default=datetime.utcnow)
    updated_at       = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at     = Column(DateTime, nullable=True)


class ProjectPhase_(Base):
    """Project phases — ordered execution stages."""
    __tablename__ = "am_project_phases"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    project_id  = Column(Integer, ForeignKey("am_projects.id"), nullable=False)
    name        = Column(String(256), nullable=False)
    description = Column(Text, default="")
    order_index = Column(Integer, default=0)
    status      = Column(String(32), default=PhaseStatus.PENDING)
    started_at  = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)


class ProjectTask_(Base):
    """Tasks within project phases — linked to PM Agent tasks."""
    __tablename__ = "am_project_tasks"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    project_id     = Column(Integer, ForeignKey("am_projects.id"), nullable=False)
    phase_id       = Column(Integer, ForeignKey("am_project_phases.id"), nullable=True)
    description    = Column(Text, nullable=False)
    status         = Column(String(32), default=ProjectTaskStatus.PENDING)
    assigned_agent = Column(String(64), nullable=True)    # agent role
    pm_task_id     = Column(String(64), nullable=True)    # link to TaskTracker pm-{uuid}
    result         = Column(Text, default="{}")           # JSON
    order_index    = Column(Integer, default=0)
    created_at     = Column(DateTime, default=datetime.utcnow)
    completed_at   = Column(DateTime, nullable=True)


class ProjectMilestone_(Base):
    """Key deliverables and checkpoints."""
    __tablename__ = "am_project_milestones"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    project_id   = Column(Integer, ForeignKey("am_projects.id"), nullable=False)
    phase_id     = Column(Integer, ForeignKey("am_project_phases.id"), nullable=True)
    name         = Column(String(256), nullable=False)
    description  = Column(Text, default="")
    due_date     = Column(DateTime, nullable=True)
    status       = Column(String(32), default=MilestoneStatus.PENDING)
    completed_at = Column(DateTime, nullable=True)


class ProjectReport_(Base):
    """Project status reports (auto-generated or manual)."""
    __tablename__ = "am_project_reports"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    project_id   = Column(Integer, ForeignKey("am_projects.id"), nullable=False)
    report_type  = Column(String(32), default="status")   # status|milestone|risk|final
    content_json = Column(Text, default="{}")              # JSON
    generated_by = Column(String(64), default="system")
    generated_at = Column(DateTime, default=datetime.utcnow)


class ProjectRisk_(Base):
    """Risk identification and tracking."""
    __tablename__ = "am_project_risks"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    project_id  = Column(Integer, ForeignKey("am_projects.id"), nullable=False)
    description = Column(Text, nullable=False)
    severity    = Column(String(16), default=RiskSeverity.MEDIUM)
    mitigation  = Column(Text, default="")
    status      = Column(String(32), default=RiskStatus.IDENTIFIED)
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PMAgentRecord_(Base):
    """PM Agent assignment tracking for projects."""
    __tablename__ = "am_pm_agents"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    project_id   = Column(Integer, ForeignKey("am_projects.id"), nullable=False)
    pm_task_id   = Column(String(64), nullable=True)      # TaskTracker task ID
    status       = Column(String(32), default=PMAgentStatus.IDLE)
    context_json = Column(Text, default="{}")              # JSON: PM context
    assigned_at  = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class ProjectActivityLog_(Base):
    """Audit trail for all project actions."""
    __tablename__ = "am_project_activity_logs"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    project_id   = Column(Integer, ForeignKey("am_projects.id"), nullable=False)
    action       = Column(String(64), nullable=False)     # created|transitioned|phase_added|...
    details_json = Column(Text, default="{}")             # JSON
    actor        = Column(String(64), default="system")   # system|user|pm_agent
    timestamp    = Column(DateTime, default=datetime.utcnow)


class ProjectDependency_(Base):
    """Task dependency tracking (finish-to-start)."""
    __tablename__ = "am_project_dependencies"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    task_id             = Column(Integer, ForeignKey("am_project_tasks.id"), nullable=False)
    depends_on_task_id  = Column(Integer, ForeignKey("am_project_tasks.id"), nullable=False)
    dependency_type     = Column(String(32), default="finish_to_start")  # finish_to_start|start_to_start

class WorkArtifact_(Base):
    """V2 Phase 2: Work artifacts created by PM Agents."""
    __tablename__ = "am_work_artifacts"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    project_id   = Column(Integer, ForeignKey("am_projects.id"), nullable=True)
    session_id   = Column(String(128), nullable=True)
    artifact_type = Column(String(32), nullable=False)     # file|service|workflow|script|config
    name         = Column(String(512), nullable=False)     # e.g., "monitor.py"
    path         = Column(String(1024), nullable=True)     # filesystem path or URL
    description  = Column(Text, default="")                # what it does
    created_by   = Column(String(64), default="pm_agent")  # which agent
    pm_task_id   = Column(String(64), nullable=True)       # PM task that created it
    created_at   = Column(DateTime, default=datetime.utcnow)
    status       = Column(String(32), default="active")    # active|deprecated|deleted

