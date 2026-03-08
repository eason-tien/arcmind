"""
ArcMind 生命週期管理器
Session / Task / Agent 三層狀態機，支援跨次恢復。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional

from db.schema import Session_, Task_, Agent_, get_db

logger = logging.getLogger("arcmind.lifecycle")


# ── Session ───────────────────────────────────────────────────────────────────

class SessionManager:
    """Session 生命週期: start → active → paused → resumed → ended"""

    def create(self, name: str, context: dict | None = None) -> int:
        db = next(get_db())
        s = Session_(
            name=name,
            status="active",
            context=json.dumps(context or {}),
        )
        db.add(s)
        db.commit()
        db.refresh(s)
        logger.info("Session created: id=%d name=%s", s.id, name)
        return s.id

    def get(self, session_id: int) -> dict | None:
        db = next(get_db())
        s = db.query(Session_).filter_by(id=session_id).first()
        if not s:
            return None
        return self._to_dict(s)

    def pause(self, session_id: int, context: dict | None = None) -> None:
        db = next(get_db())
        s = db.query(Session_).filter_by(id=session_id).first()
        if s:
            s.status = "paused"
            if context:
                s.context = json.dumps(context)
            db.commit()

    def resume(self, session_id: int) -> dict | None:
        db = next(get_db())
        s = db.query(Session_).filter_by(id=session_id).first()
        if s and s.status == "paused":
            s.status = "active"
            db.commit()
        return self._to_dict(s) if s else None

    def end(self, session_id: int) -> None:
        db = next(get_db())
        s = db.query(Session_).filter_by(id=session_id).first()
        if s:
            s.status = "ended"
            db.commit()

    def update_context(self, session_id: int, updates: dict) -> None:
        db = next(get_db())
        s = db.query(Session_).filter_by(id=session_id).first()
        if s:
            ctx = json.loads(s.context or "{}")
            ctx.update(updates)
            s.context = json.dumps(ctx)
            db.commit()

    def list_active(self) -> list[dict]:
        db = next(get_db())
        rows = db.query(Session_).filter_by(status="active").all()
        return [self._to_dict(r) for r in rows]

    def list_paused(self) -> list[dict]:
        db = next(get_db())
        rows = db.query(Session_).filter_by(status="paused").all()
        return [self._to_dict(r) for r in rows]

    def _to_dict(self, s: Session_) -> dict:
        return {
            "id": s.id,
            "name": s.name,
            "status": s.status,
            "context": json.loads(s.context or "{}"),
            "goal_ids": json.loads(s.goal_ids or "[]"),
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        }


# ── Task ──────────────────────────────────────────────────────────────────────

class TaskManager:
    """
    任務生命週期: created → assigned → executing → verifying → closed/failed
    """

    def create(self, title: str, skill_name: str | None = None,
               task_type: str = "general", session_id: int | None = None,
               input_data: dict | None = None) -> int:
        db = next(get_db())
        t = Task_(
            title=title,
            skill_name=skill_name,
            task_type=task_type,
            session_id=session_id,
            status="created",
            input_data=json.dumps(input_data or {}),
        )
        db.add(t)
        db.commit()
        db.refresh(t)
        logger.info("Task created: id=%d title=%s", t.id, title)
        return t.id

    def assign(self, task_id: int, skill_name: str,
               governor_ok: bool = False, model: str | None = None) -> None:
        db = next(get_db())
        t = db.query(Task_).filter_by(id=task_id).first()
        if t:
            t.status = "assigned"
            t.skill_name = skill_name
            t.governor_ok = governor_ok
            if model:
                t.model_used = model
            db.commit()

    def start_executing(self, task_id: int) -> None:
        self._set_status(task_id, "executing")

    def start_verifying(self, task_id: int) -> None:
        self._set_status(task_id, "verifying")

    def close(self, task_id: int, output_data: dict | None = None,
              tokens_used: int = 0) -> None:
        db = next(get_db())
        t = db.query(Task_).filter_by(id=task_id).first()
        if t:
            t.status = "closed"
            t.output_data = json.dumps(output_data or {})
            t.tokens_used = tokens_used
            t.closed_at = datetime.utcnow()
            db.commit()

    def fail(self, task_id: int, error_msg: str) -> None:
        db = next(get_db())
        t = db.query(Task_).filter_by(id=task_id).first()
        if t:
            t.status = "failed"
            t.error_msg = error_msg
            t.closed_at = datetime.utcnow()
            db.commit()

    def get(self, task_id: int) -> dict | None:
        db = next(get_db())
        t = db.query(Task_).filter_by(id=task_id).first()
        return self._to_dict(t) if t else None

    def list_by_session(self, session_id: int) -> list[dict]:
        db = next(get_db())
        rows = db.query(Task_).filter_by(session_id=session_id).all()
        return [self._to_dict(r) for r in rows]

    def list_open(self) -> list[dict]:
        db = next(get_db())
        rows = db.query(Task_).filter(
            Task_.status.in_(["created", "assigned", "executing", "verifying"])
        ).all()
        return [self._to_dict(r) for r in rows]

    def _set_status(self, task_id: int, status: str) -> None:
        db = next(get_db())
        t = db.query(Task_).filter_by(id=task_id).first()
        if t:
            t.status = status
            db.commit()

    def _to_dict(self, t: Task_) -> dict:
        return {
            "id": t.id,
            "session_id": t.session_id,
            "title": t.title,
            "skill_name": t.skill_name,
            "task_type": t.task_type,
            "status": t.status,
            "input_data": json.loads(t.input_data or "{}"),
            "output_data": json.loads(t.output_data or "{}"),
            "governor_ok": t.governor_ok,
            "model_used": t.model_used,
            "tokens_used": t.tokens_used,
            "error_msg": t.error_msg,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "closed_at": t.closed_at.isoformat() if t.closed_at else None,
        }


# ── Agent ─────────────────────────────────────────────────────────────────────

class AgentManager:
    """Agent 生命週期: spawned → running → idle → terminated"""

    MAX_AGENTS = 10  # 最大並發 agent 數

    def spawn(self, agent_type: str = "general",
              session_id: int | None = None) -> int:
        db = next(get_db())
        count = db.query(Agent_).filter(
            Agent_.status.in_(["spawned", "running", "idle"])
        ).count()
        if count >= self.MAX_AGENTS:
            raise RuntimeError(f"Max agents ({self.MAX_AGENTS}) reached.")
        a = Agent_(
            agent_type=agent_type,
            session_id=session_id,
            status="spawned",
        )
        db.add(a)
        db.commit()
        db.refresh(a)
        logger.info("Agent spawned: id=%d type=%s", a.id, agent_type)
        return a.id

    def set_running(self, agent_id: int, task_id: int | None = None) -> None:
        db = next(get_db())
        a = db.query(Agent_).filter_by(id=agent_id).first()
        if a:
            a.status = "running"
            a.current_task = task_id
            db.commit()

    def set_idle(self, agent_id: int) -> None:
        db = next(get_db())
        a = db.query(Agent_).filter_by(id=agent_id).first()
        if a:
            a.status = "idle"
            a.current_task = None
            db.commit()

    def terminate(self, agent_id: int) -> None:
        db = next(get_db())
        a = db.query(Agent_).filter_by(id=agent_id).first()
        if a:
            a.status = "terminated"
            a.terminated_at = datetime.utcnow()
            db.commit()

    def list_active(self) -> list[dict]:
        db = next(get_db())
        rows = db.query(Agent_).filter(
            Agent_.status.in_(["spawned", "running", "idle"])
        ).all()
        return [self._to_dict(r) for r in rows]

    def _to_dict(self, a: Agent_) -> dict:
        return {
            "id": a.id,
            "agent_type": a.agent_type,
            "session_id": a.session_id,
            "status": a.status,
            "current_task": a.current_task,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "terminated_at": a.terminated_at.isoformat() if a.terminated_at else None,
        }


# ── 統一 Lifecycle 入口 ───────────────────────────────────────────────────────

class LifecycleManager:
    def __init__(self):
        self.sessions = SessionManager()
        self.tasks = TaskManager()
        self.agents = AgentManager()

    def summary(self) -> dict:
        return {
            "active_sessions": len(self.sessions.list_active()),
            "paused_sessions": len(self.sessions.list_paused()),
            "open_tasks": len(self.tasks.list_open()),
            "active_agents": len(self.agents.list_active()),
        }


lifecycle = LifecycleManager()
