"""
ArcMind 長期目標追蹤器。
維護跨 session 的目標狀態，定期同步到 MGIS 記憶。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from db.schema import Goal_, get_db, get_db_session

logger = logging.getLogger("arcmind.goal_tracker")


class GoalTracker:

    def create(self, title: str, description: str = "",
               priority: int = 5, context: dict | None = None) -> int:
        with get_db_session() as db:
            g = Goal_(
                title=title,
                description=description,
                priority=priority,
                status="active",
                progress=0.0,
                context=json.dumps(context or {}),
            )
            db.add(g)
            db.commit()
            db.refresh(g)
            logger.info("Goal created: id=%d title=%s", g.id, title)
            return g.id

    def update_progress(self, goal_id: int, progress: float,
                        notes: str | None = None) -> None:
        progress = max(0.0, min(1.0, progress))
        with get_db_session() as db:
            g = db.query(Goal_).filter_by(id=goal_id).first()
            if g:
                g.progress = progress
                if progress >= 1.0:
                    g.status = "completed"
                if notes:
                    ctx = json.loads(g.context or "{}")
                    ctx.setdefault("notes", []).append({
                        "ts": datetime.utcnow().isoformat(),
                        "note": notes,
                    })
                    g.context = json.dumps(ctx)
                db.commit()

    def pause(self, goal_id: int) -> None:
        self._set_status(goal_id, "paused")

    def resume(self, goal_id: int) -> None:
        self._set_status(goal_id, "active")

    def abandon(self, goal_id: int) -> None:
        self._set_status(goal_id, "abandoned")

    def complete(self, goal_id: int) -> None:
        with get_db_session() as db:
            g = db.query(Goal_).filter_by(id=goal_id).first()
            if g:
                g.status = "completed"
                g.progress = 1.0
                db.commit()

    def get(self, goal_id: int) -> dict | None:
        with get_db_session() as db:
            g = db.query(Goal_).filter_by(id=goal_id).first()
            return self._to_dict(g) if g else None

    def list_active(self) -> list[dict]:
        with get_db_session() as db:
            rows = db.query(Goal_).filter_by(status="active").order_by(Goal_.priority).all()
            return [self._to_dict(r) for r in rows]

    def list_all(self) -> list[dict]:
        with get_db_session() as db:
            rows = db.query(Goal_).order_by(Goal_.priority, Goal_.created_at).all()
            return [self._to_dict(r) for r in rows]

    def sync_to_mgis(self, goal_id: int) -> None:
        """將目標狀態同步寫入 MGIS 記憶，供 SharedBrain 參考"""
        g = self.get(goal_id)
        if not g:
            return
        from foundation.mgis_client import mgis
        mgis.memory_add(
            content=f"[ArcMind Goal] {g['title']}: progress={g['progress']:.0%} status={g['status']}",
            tags=["arcmind", "goal", f"goal:{goal_id}"],
            source="arcmind",
            metadata=g,
        )
        logger.info("Goal %d synced to MGIS memory.", goal_id)

    def _set_status(self, goal_id: int, status: str) -> None:
        with get_db_session() as db:
            g = db.query(Goal_).filter_by(id=goal_id).first()
            if g:
                g.status = status
                db.commit()

    def _to_dict(self, g: Goal_) -> dict:
        return {
            "id": g.id,
            "title": g.title,
            "description": g.description,
            "status": g.status,
            "progress": g.progress,
            "priority": g.priority,
            "context": json.loads(g.context or "{}"),
            "created_at": g.created_at.isoformat() if g.created_at else None,
            "updated_at": g.updated_at.isoformat() if g.updated_at else None,
        }


goal_tracker = GoalTracker()
