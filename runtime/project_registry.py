# -*- coding: utf-8 -*-
"""
ArcMind — Project Registry (V2 Phase 1)
=========================================
CRUD + lifecycle management for projects.
Persistent via SQLAlchemy (SQLite).
Thread-safe singleton.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger("arcmind.project_registry")


class ProjectRegistry:
    """Project lifecycle service — CRUD + state management."""

    def __init__(self):
        self._lock = threading.Lock()

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _get_db(self):
        from db.schema import SessionLocal
        return SessionLocal()

    def _to_dict(self, obj) -> dict:
        """Convert SQLAlchemy ORM object to dict."""
        d = {}
        for c in obj.__table__.columns:
            v = getattr(obj, c.name if c.name != "metadata_" else "metadata_")
            if isinstance(v, datetime):
                v = v.isoformat()
            d[c.name.rstrip("_") if c.name == "metadata_" else c.name] = v
        return d

    def _emit_event(self, event_name: str, payload: dict) -> None:
        """Fire-and-forget event emission."""
        try:
            from runtime.event_bus import event_bus, Event, EventType
            event_bus.emit(Event(
                type=EventType.SYSTEM_EVENT,
                source="project_registry",
                payload={"event": event_name, **payload},
            ))
        except Exception as e:
            logger.debug("[ProjectRegistry] Event emission failed: %s", e)

    # ── Project CRUD ─────────────────────────────────────────────────────────

    def create_project(
        self,
        name: str,
        description: str = "",
        session_id: str | None = None,
        priority: str = "medium",
        tags: list[str] | None = None,
    ) -> dict:
        """Create a new project in PROPOSED state."""
        from db.project_schema import Project_, ProjectStatus

        db = self._get_db()
        try:
            project = Project_(
                name=name,
                description=description,
                status=ProjectStatus.PROPOSED,
                priority=priority,
                owner_session_id=session_id,
                tags=json.dumps(tags or []),
            )
            db.add(project)
            db.commit()
            db.refresh(project)
            result = self._to_dict(project)

            self.log_activity(result["id"], "created",
                              {"name": name, "priority": priority}, "system", db=db)

            self._emit_event("project_created", {
                "project_id": result["id"],
                "name": name,
                "session_id": session_id,
            })
            logger.info("[ProjectRegistry] Created project %d: %s", result["id"], name)
            return result
        finally:
            db.close()

    def get_project(self, project_id: int) -> dict | None:
        """Get project by ID."""
        from db.project_schema import Project_
        db = self._get_db()
        try:
            p = db.query(Project_).filter(Project_.id == project_id).first()
            return self._to_dict(p) if p else None
        finally:
            db.close()

    def list_projects(
        self,
        session_id: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """List projects with optional filters."""
        from db.project_schema import Project_
        db = self._get_db()
        try:
            q = db.query(Project_)
            if session_id:
                q = q.filter(Project_.owner_session_id == session_id)
            if status:
                q = q.filter(Project_.status == status)
            q = q.order_by(Project_.updated_at.desc()).limit(limit)
            return [self._to_dict(p) for p in q.all()]
        finally:
            db.close()

    def update_project(self, project_id: int, **kwargs) -> dict | None:
        """Update project fields (name, description, priority, tags)."""
        from db.project_schema import Project_
        allowed = {"name", "description", "priority", "tags", "progress"}
        db = self._get_db()
        try:
            p = db.query(Project_).filter(Project_.id == project_id).first()
            if not p:
                return None
            changes = {}
            for k, v in kwargs.items():
                if k in allowed:
                    if k == "tags" and isinstance(v, list):
                        v = json.dumps(v)
                    setattr(p, k, v)
                    changes[k] = v
            p.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(p)

            if changes:
                self.log_activity(project_id, "updated", changes, "system", db=db)

            return self._to_dict(p)
        finally:
            db.close()

    def transition_project(self, project_id: int, new_status: str) -> dict:
        """
        Transition project to new status using state machine.
        Raises ValueError if transition is invalid.
        """
        from db.project_schema import Project_
        from runtime.project_state_machine import ProjectStateMachine

        db = self._get_db()
        try:
            # with_for_update() locks the row to prevent TOCTOU race conditions
            # when multiple PM agents transition the same project concurrently
            p = db.query(Project_).filter(Project_.id == project_id).with_for_update().first()
            if not p:
                raise ValueError(f"Project {project_id} not found")

            old_status = p.status
            # State machine validates transition
            ProjectStateMachine.transition(old_status, new_status)

            p.status = new_status
            p.updated_at = datetime.utcnow()

            # Set completed_at for terminal-ish states
            if new_status in ("completed", "cancelled", "failed", "closed"):
                p.completed_at = datetime.utcnow()
                if new_status == "completed":
                    p.progress = 1.0

            db.commit()
            db.refresh(p)

            self.log_activity(project_id, "transitioned",
                              {"from": old_status, "to": new_status}, "system", db=db)

            self._emit_event("project_status_changed", {
                "project_id": project_id,
                "from": old_status,
                "to": new_status,
            })

            if new_status in ("completed", "closed"):
                self._emit_event("project_completed", {
                    "project_id": project_id,
                    "name": p.name,
                })

            logger.info("[ProjectRegistry] Project %d: %s → %s",
                        project_id, old_status, new_status)
            return self._to_dict(p)
        finally:
            db.close()

    # ── Phase Management ─────────────────────────────────────────────────────

    def add_phase(
        self,
        project_id: int,
        name: str,
        description: str = "",
        order_index: int = 0,
    ) -> dict:
        """Add a phase to a project."""
        from db.project_schema import ProjectPhase_
        db = self._get_db()
        try:
            phase = ProjectPhase_(
                project_id=project_id,
                name=name,
                description=description,
                order_index=order_index,
            )
            db.add(phase)
            db.commit()
            db.refresh(phase)

            self.log_activity(project_id, "phase_added",
                              {"phase_id": phase.id, "name": name}, "system", db=db)
            return self._to_dict(phase)
        finally:
            db.close()

    def list_phases(self, project_id: int) -> list[dict]:
        """List all phases for a project, ordered by order_index."""
        from db.project_schema import ProjectPhase_
        db = self._get_db()
        try:
            phases = (
                db.query(ProjectPhase_)
                .filter(ProjectPhase_.project_id == project_id)
                .order_by(ProjectPhase_.order_index)
                .all()
            )
            return [self._to_dict(p) for p in phases]
        finally:
            db.close()

    def complete_phase(self, project_id: int, phase_id: int) -> dict:
        """Mark a phase as completed."""
        from db.project_schema import ProjectPhase_, PhaseStatus
        db = self._get_db()
        try:
            phase = (
                db.query(ProjectPhase_)
                .filter(ProjectPhase_.id == phase_id,
                        ProjectPhase_.project_id == project_id)
                .first()
            )
            if not phase:
                raise ValueError(f"Phase {phase_id} not found in project {project_id}")
            phase.status = PhaseStatus.COMPLETED
            phase.completed_at = datetime.utcnow()
            db.commit()
            db.refresh(phase)

            self.log_activity(project_id, "phase_completed",
                              {"phase_id": phase_id, "name": phase.name}, "system", db=db)

            # Auto-update project progress based on completed phases
            self._update_project_progress(project_id, db)

            return self._to_dict(phase)
        finally:
            db.close()

    def _update_project_progress(self, project_id: int, db=None) -> None:
        """Recalculate project progress from phase completion."""
        from db.project_schema import ProjectPhase_, PhaseStatus, Project_
        close_db = False
        if db is None:
            db = self._get_db()
            close_db = True
        try:
            phases = (
                db.query(ProjectPhase_)
                .filter(ProjectPhase_.project_id == project_id)
                .all()
            )
            if not phases:
                return
            completed = sum(1 for p in phases if p.status == PhaseStatus.COMPLETED)
            progress = completed / len(phases)

            p = db.query(Project_).filter(Project_.id == project_id).first()
            if p:
                p.progress = round(progress, 2)
                p.updated_at = datetime.utcnow()
                db.commit()
        finally:
            if close_db:
                db.close()

    # ── Task Management ──────────────────────────────────────────────────────

    def add_task(
        self,
        project_id: int,
        description: str,
        phase_id: int | None = None,
        order_index: int = 0,
    ) -> dict:
        """Add a task to a project (optionally within a phase)."""
        from db.project_schema import ProjectTask_
        db = self._get_db()
        try:
            task = ProjectTask_(
                project_id=project_id,
                phase_id=phase_id,
                description=description,
                order_index=order_index,
            )
            db.add(task)
            db.commit()
            db.refresh(task)

            self.log_activity(project_id, "task_added",
                              {"task_id": task.id, "description": description[:100]},
                              "system", db=db)
            return self._to_dict(task)
        finally:
            db.close()

    def list_tasks(self, project_id: int, phase_id: int | None = None) -> list[dict]:
        """List tasks for a project, optionally filtered by phase."""
        from db.project_schema import ProjectTask_
        db = self._get_db()
        try:
            q = db.query(ProjectTask_).filter(ProjectTask_.project_id == project_id)
            if phase_id is not None:
                q = q.filter(ProjectTask_.phase_id == phase_id)
            return [self._to_dict(t) for t in q.order_by(ProjectTask_.order_index).all()]
        finally:
            db.close()

    def assign_task(self, task_id: int, pm_task_id: str, agent: str = "pm") -> dict:
        """Link a project task to a PM Agent task."""
        from db.project_schema import ProjectTask_, ProjectTaskStatus
        db = self._get_db()
        try:
            task = db.query(ProjectTask_).filter(ProjectTask_.id == task_id).first()
            if not task:
                raise ValueError(f"Task {task_id} not found")
            task.status = ProjectTaskStatus.ASSIGNED
            task.pm_task_id = pm_task_id
            task.assigned_agent = agent
            db.commit()
            db.refresh(task)

            self.log_activity(task.project_id, "task_assigned",
                              {"task_id": task_id, "pm_task_id": pm_task_id},
                              "system", db=db)
            return self._to_dict(task)
        finally:
            db.close()

    def complete_task(self, task_id: int, result: str = "") -> dict:
        """Mark a project task as completed."""
        from db.project_schema import ProjectTask_, ProjectTaskStatus
        db = self._get_db()
        try:
            task = db.query(ProjectTask_).filter(ProjectTask_.id == task_id).first()
            if not task:
                raise ValueError(f"Task {task_id} not found")
            task.status = ProjectTaskStatus.COMPLETED
            task.result = result if isinstance(result, str) else json.dumps(result)
            task.completed_at = datetime.utcnow()
            db.commit()
            db.refresh(task)

            self.log_activity(task.project_id, "task_completed",
                              {"task_id": task_id}, "system", db=db)
            return self._to_dict(task)
        finally:
            db.close()

    # ── Milestone Management ─────────────────────────────────────────────────

    def add_milestone(
        self,
        project_id: int,
        name: str,
        phase_id: int | None = None,
        due_date: str | None = None,
        description: str = "",
    ) -> dict:
        """Add a milestone to a project."""
        from db.project_schema import ProjectMilestone_
        db = self._get_db()
        try:
            milestone = ProjectMilestone_(
                project_id=project_id,
                phase_id=phase_id,
                name=name,
                description=description,
                due_date=datetime.fromisoformat(due_date) if due_date else None,
            )
            db.add(milestone)
            db.commit()
            db.refresh(milestone)

            self.log_activity(project_id, "milestone_added",
                              {"milestone_id": milestone.id, "name": name},
                              "system", db=db)
            return self._to_dict(milestone)
        finally:
            db.close()

    def complete_milestone(self, milestone_id: int) -> dict:
        """Mark a milestone as completed."""
        from db.project_schema import ProjectMilestone_, MilestoneStatus
        db = self._get_db()
        try:
            m = db.query(ProjectMilestone_).filter(ProjectMilestone_.id == milestone_id).first()
            if not m:
                raise ValueError(f"Milestone {milestone_id} not found")
            m.status = MilestoneStatus.COMPLETED
            m.completed_at = datetime.utcnow()
            db.commit()
            db.refresh(m)

            self.log_activity(m.project_id, "milestone_completed",
                              {"milestone_id": milestone_id, "name": m.name},
                              "system", db=db)
            return self._to_dict(m)
        finally:
            db.close()

    # ── Risk Management ──────────────────────────────────────────────────────

    def add_risk(
        self,
        project_id: int,
        description: str,
        severity: str = "medium",
        mitigation: str = "",
    ) -> dict:
        """Add a risk to a project."""
        from db.project_schema import ProjectRisk_
        db = self._get_db()
        try:
            risk = ProjectRisk_(
                project_id=project_id,
                description=description,
                severity=severity,
                mitigation=mitigation,
            )
            db.add(risk)
            db.commit()
            db.refresh(risk)

            self.log_activity(project_id, "risk_added",
                              {"risk_id": risk.id, "severity": severity},
                              "system", db=db)
            return self._to_dict(risk)
        finally:
            db.close()

    def list_risks(self, project_id: int) -> list[dict]:
        """List risks for a project."""
        from db.project_schema import ProjectRisk_
        db = self._get_db()
        try:
            risks = (
                db.query(ProjectRisk_)
                .filter(ProjectRisk_.project_id == project_id)
                .all()
            )
            return [self._to_dict(r) for r in risks]
        finally:
            db.close()

    # ── Reports ──────────────────────────────────────────────────────────────

    def generate_report(self, project_id: int, report_type: str = "status",
                        content: str | None = None, metadata: dict | None = None) -> dict:
        """Generate a project report. If content is provided, store it directly (PM completion report)."""
        from db.project_schema import ProjectReport_

        project = self.get_project(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        if content is not None:
            # V2 Phase 2: Direct content storage (e.g., PM completion report)
            report_data = {
                "content": content,
                "metadata": metadata or {},
                "generated_at": datetime.utcnow().isoformat(),
            }
        else:
            # Original auto-generation
            phases = self.list_phases(project_id)
            tasks = self.list_tasks(project_id)
            risks = self.list_risks(project_id)

            report_data = {
                "project": project,
                "phases": phases,
                "tasks_total": len(tasks),
                "tasks_completed": sum(1 for t in tasks if t.get("status") == "completed"),
                "tasks_in_progress": sum(1 for t in tasks if t.get("status") in ("assigned", "executing")),
                "risks": risks,
                "generated_at": datetime.utcnow().isoformat(),
            }

        db = self._get_db()
        try:
            report = ProjectReport_(
                project_id=project_id,
                report_type=report_type,
                content_json=json.dumps(report_data, ensure_ascii=False),
            )
            db.add(report)
            db.commit()
            db.refresh(report)

            self.log_activity(project_id, "report_generated",
                              {"report_id": report.id, "type": report_type},
                              "system", db=db)
            return self._to_dict(report)
        finally:
            db.close()

    def list_reports(self, project_id: int) -> list[dict]:
        """List reports for a project."""
        from db.project_schema import ProjectReport_
        db = self._get_db()
        try:
            reports = (
                db.query(ProjectReport_)
                .filter(ProjectReport_.project_id == project_id)
                .order_by(ProjectReport_.generated_at.desc())
                .all()
            )
            return [self._to_dict(r) for r in reports]
        finally:
            db.close()

    # ── Activity Log ─────────────────────────────────────────────────────────

    def log_activity(
        self,
        project_id: int,
        action: str,
        details: dict | None = None,
        actor: str = "system",
        db=None,
    ) -> None:
        """Log an activity for audit trail."""
        from db.project_schema import ProjectActivityLog_
        close_db = False
        if db is None:
            db = self._get_db()
            close_db = True
        try:
            log = ProjectActivityLog_(
                project_id=project_id,
                action=action,
                details_json=json.dumps(details or {}, ensure_ascii=False),
                actor=actor,
            )
            db.add(log)
            db.commit()
        except Exception as e:
            logger.debug("[ProjectRegistry] Activity log failed: %s", e)
        finally:
            if close_db:
                db.close()

    # ── Progress Formatting ──────────────────────────────────────────────────


    # ── Work Artifacts (V2 Phase 2) ──────────────────────────────────────────

    def record_artifact(self, project_id: int, artifact_type: str, name: str,
                        path: str = "", description: str = "",
                        created_by: str = "pm_agent", pm_task_id: str = "",
                        session_id: str = "") -> dict:
        """Record a work artifact created by PM Agent."""
        from db.project_schema import WorkArtifact_
        db = self._get_db()
        try:
            artifact = WorkArtifact_(
                project_id=project_id,
                session_id=session_id,
                artifact_type=artifact_type,
                name=name,
                path=path,
                description=description,
                created_by=created_by,
                pm_task_id=pm_task_id,
            )
            db.add(artifact)
            db.commit()
            db.refresh(artifact)
            return self._to_dict(artifact)
        finally:
            db.close()

    def list_artifacts(self, project_id: int = None, session_id: str = None) -> list[dict]:
        """List work artifacts, optionally filtered by project or session."""
        from db.project_schema import WorkArtifact_
        db = self._get_db()
        try:
            q = db.query(WorkArtifact_).filter(WorkArtifact_.status == "active")
            if project_id:
                q = q.filter(WorkArtifact_.project_id == project_id)
            if session_id:
                q = q.filter(WorkArtifact_.session_id == session_id)
            results = q.order_by(WorkArtifact_.created_at.desc()).all()
            return [self._to_dict(a) for a in results]
        finally:
            db.close()

    def format_work_memory(self, session_id: str = None) -> str:
        """Format all artifacts as context for Main Agent / progress queries."""
        artifacts = self.list_artifacts(session_id=session_id)
        if not artifacts:
            return ""
        lines = ["\n\U0001f9e0 **工作记忆 (已完成的工作成果):**"]
        for a in artifacts[:20]:  # Limit to 20 most recent
            icon = {"file": "\U0001f4c4", "service": "\u2699\ufe0f", "workflow": "\U0001f504",
                     "script": "\U0001f4dc", "config": "\U0001f527"}.get(a.get("artifact_type", ""), "\U0001f4e6")
            name = a.get("name", "?")
            desc = a.get("description", "")[:60]
            path = a.get("path", "")
            line = f"  {icon} {name}"
            if desc:
                line += f" — {desc}"
            if path:
                line += f" ({path})"
            lines.append(line)
        return "\n".join(lines)

    def format_project_progress(self, project_id: int) -> str:
        """Human-readable project progress for LLM response."""
        project = self.get_project(project_id)
        if not project:
            return f"项目 {project_id} 不存在。"

        STATUS_ICONS = {
            "proposed": "📝", "planning": "📐", "in_progress": "🔧",
            "on_hold": "⏸️", "review": "🔍", "completed": "✅",
            "cancelled": "🚫", "failed": "❌", "archived": "📦",
            "closed": "🔒",
        }

        icon = STATUS_ICONS.get(project["status"], "❓")
        lines = [
            f"{icon} **项目: {project['name']}**",
            f"   状态: {project['status']} | 优先级: {project['priority']} | 进度: {int(project.get('progress', 0) * 100)}%",
        ]

        # Phases
        phases = self.list_phases(project_id)
        if phases:
            lines.append("   **阶段:**")
            for phase in phases:
                p_icon = "✅" if phase["status"] == "completed" else "⬜" if phase["status"] == "pending" else "🔧"
                lines.append(f"     {p_icon} {phase['order_index']+1}. {phase['name']} [{phase['status']}]")

        # Tasks summary
        tasks = self.list_tasks(project_id)
        if tasks:
            done = sum(1 for t in tasks if t["status"] == "completed")
            total = len(tasks)
            lines.append(f"   **任务:** {done}/{total} 已完成")

        # Active risks
        risks = self.list_risks(project_id)
        active_risks = [r for r in risks if r["status"] == "identified"]
        if active_risks:
            lines.append(f"   ⚠️ **风险:** {len(active_risks)} 个活跃风险")

        return "\n".join(lines)

    def format_all_projects(self, session_id: str | None = None) -> str:
        """Format all active projects for LLM response."""
        from db.project_schema import ProjectStatus
        active_statuses = [
            ProjectStatus.PROPOSED, ProjectStatus.PLANNING,
            ProjectStatus.IN_PROGRESS, ProjectStatus.ON_HOLD,
            ProjectStatus.REVIEW,
        ]

        db = self._get_db()
        try:
            from db.project_schema import Project_
            q = db.query(Project_).filter(Project_.status.in_(active_statuses))
            if session_id:
                q = q.filter(Project_.owner_session_id == session_id)
            projects = q.order_by(Project_.updated_at.desc()).all()

            if not projects:
                return ""

            # V2: Check TaskTracker for real-time PM progress
            pm_progress = {}
            try:
                from runtime.task_tracker import task_tracker
                from db.project_schema import PMAgentRecord_
                for p in projects:
                    recs = (
                        db.query(PMAgentRecord_)
                        .filter(PMAgentRecord_.project_id == p.id)
                        .all()
                    )
                    for rec in recs:
                        if rec.pm_task_id:
                            tracked = task_tracker.get(rec.pm_task_id)
                            if tracked and tracked.progress_pct > 0:
                                pm_progress[p.id] = tracked.progress_pct
            except Exception:
                pass

            lines = ["📊 **活跃项目:**"]
            for p in projects:
                icon = {"proposed": "📝", "planning": "📐", "in_progress": "🔧",
                         "on_hold": "⏸️", "review": "🔍"}.get(p.status, "❓")
                real_progress = pm_progress.get(p.id, p.progress or 0)
                progress_pct = int(real_progress * 100)
                lines.append(
                    f"  {icon} [{p.id}] {p.name} — {p.status} ({progress_pct}%)"
                )

            return "\n".join(lines)
        finally:
            db.close()

    # ── PM Agent Tracking ────────────────────────────────────────────────────

    def assign_pm_agent(self, project_id: int, pm_task_id: str) -> dict:
        """Record a PM Agent assignment for a project."""
        from db.project_schema import PMAgentRecord_, PMAgentStatus
        db = self._get_db()
        try:
            record = PMAgentRecord_(
                project_id=project_id,
                pm_task_id=pm_task_id,
                status=PMAgentStatus.ASSIGNED,
            )
            db.add(record)
            db.commit()
            db.refresh(record)

            self.log_activity(project_id, "pm_assigned",
                              {"pm_task_id": pm_task_id}, "system", db=db)
            return self._to_dict(record)
        finally:
            db.close()

    def update_pm_status(self, pm_record_id: int, new_status: str) -> dict:
        """Update PM Agent status using state machine."""
        from db.project_schema import PMAgentRecord_
        from runtime.project_state_machine import PMAgentStateMachine

        db = self._get_db()
        try:
            record = db.query(PMAgentRecord_).filter(PMAgentRecord_.id == pm_record_id).first()
            if not record:
                raise ValueError(f"PM Agent record {pm_record_id} not found")

            old_status = record.status
            PMAgentStateMachine.transition(old_status, new_status)
            record.status = new_status

            if new_status in ("completed", "failed", "terminated"):
                record.completed_at = datetime.utcnow()

            db.commit()
            db.refresh(record)
            return self._to_dict(record)
        finally:
            db.close()


# Singleton
project_registry = ProjectRegistry()
