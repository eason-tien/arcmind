# -*- coding: utf-8 -*-
"""
ArcMind — Long-Running Agent Harness Engine
=============================================
將大任務拆分為可恢復的 Step，逐步呼叫 OODA MainLoop。
每步 Checkpoint 持久化到 SQLite，失敗後從斷點恢復。

Usage:
    from runtime.harness import harness_engine

    run_id = await harness_engine.create_run(
        title="研究報告",
        plan=[
            {"name": "research",   "command": "搜集 AI Agent 最新論文"},
            {"name": "analysis",   "command": "分析搜集到的資料"},
            {"name": "report",     "command": "撰寫完整研究報告"},
        ],
    )
    result = await harness_engine.execute_run(run_id)
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Any, Optional

from db.schema import get_db
from db.harness_schema import HarnessRun_, HarnessStep_

logger = logging.getLogger("arcmind.harness")


# ── Status Constants ────────────────────────────────────────────────────────
class RunStatus:
    PENDING    = "pending"
    RUNNING    = "running"
    PAUSED     = "paused"
    COMPLETED  = "completed"
    FAILED     = "failed"
    CANCELLED  = "cancelled"


class StepStatus:
    PENDING    = "pending"
    RUNNING    = "running"
    COMPLETED  = "completed"
    FAILED     = "failed"
    SKIPPED    = "skipped"


# ── Data Classes ────────────────────────────────────────────────────────────

class HarnessRunInfo:
    """Read-only snapshot of a harness run."""
    def __init__(self, row: HarnessRun_, steps: list[dict] | None = None):
        self.id = row.id
        self.title = row.title
        self.status = row.status
        self.goal_id = row.goal_id
        self.current_step_idx = row.current_step_idx
        self.context = json.loads(row.context or "{}")
        self.plan = json.loads(row.plan_json or "[]")
        self.error = row.error
        self.created_at = row.created_at
        self.updated_at = row.updated_at
        self.completed_at = row.completed_at
        self.steps = steps or []

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "goal_id": self.goal_id,
            "current_step_idx": self.current_step_idx,
            "context": self.context,
            "error": self.error,
            "steps": self.steps,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


# ── Harness Engine ──────────────────────────────────────────────────────────

class HarnessEngine:
    """
    Long-running task orchestration engine.
    Wraps the OODA MainLoop: each step = one MainLoop.run() call.
    """

    # ── Create ─────────────────────────────────────────────────────────

    async def create_run(
        self,
        title: str,
        plan: list[dict],
        goal_id: int | None = None,
        context: dict | None = None,
        retry_max: int = 3,
        retry_backoff_s: int = 60,
        timeout_s: int = 600,
        notify_channel: str = "telegram",
    ) -> str:
        """
        Create a new harness run with a step plan.

        Each plan item must have:
            {"name": "step_name", "command": "指令..."}
        Optional fields:
            {"skill_hint": "skill_name"}
        """
        run_id = str(uuid.uuid4())[:8]  # short, human-friendly
        now = datetime.utcnow()

        db = next(get_db())
        try:
            run = HarnessRun_(
                id=run_id,
                goal_id=goal_id,
                title=title,
                status=RunStatus.PENDING,
                plan_json=json.dumps(plan, ensure_ascii=False),
                context=json.dumps(context or {}, ensure_ascii=False),
                current_step_idx=0,
                retry_max=retry_max,
                retry_backoff_s=retry_backoff_s,
                timeout_s=timeout_s,
                notify_channel=notify_channel,
                created_at=now,
                updated_at=now,
            )
            db.add(run)

            for idx, step_def in enumerate(plan):
                step = HarnessStep_(
                    run_id=run_id,
                    step_idx=idx,
                    name=step_def.get("name", f"step_{idx}"),
                    command=step_def["command"],
                    skill_hint=step_def.get("skill_hint"),
                    status=StepStatus.PENDING,
                    input_snapshot="{}",
                    output_snapshot="{}",
                )
                db.add(step)

            db.commit()
            logger.info("[Harness] Run created: id=%s title=%s steps=%d",
                        run_id, title, len(plan))
            return run_id
        finally:
            db.close()

    # ── Execute ────────────────────────────────────────────────────────

    async def execute_run(self, run_id: str) -> dict:
        """
        Execute a harness run from its current step index.
        Returns the run info dict on completion.
        """
        from loop.main_loop import main_loop, LoopInput

        db = next(get_db())
        try:
            run = db.query(HarnessRun_).filter_by(id=run_id).first()
            if not run:
                return {"error": f"Run {run_id} not found"}

            if run.status not in (RunStatus.PENDING, RunStatus.PAUSED):
                return {"error": f"Run {run_id} is {run.status}, cannot execute"}

            run.status = RunStatus.RUNNING
            run.updated_at = datetime.utcnow()
            db.commit()
        finally:
            db.close()

        steps = self._load_steps(run_id)
        context = self._load_context(run_id)
        start_idx = self._load_current_idx(run_id)

        logger.info("[Harness] Executing run=%s from step=%d/%d",
                    run_id, start_idx, len(steps))

        for idx in range(start_idx, len(steps)):
            # Check if paused or cancelled
            current_status = self._load_status(run_id)
            if current_status == RunStatus.PAUSED:
                logger.info("[Harness] Run %s paused at step %d", run_id, idx)
                return self.get_run(run_id)
            if current_status == RunStatus.CANCELLED:
                logger.info("[Harness] Run %s cancelled at step %d", run_id, idx)
                return self.get_run(run_id)

            step = steps[idx]
            step_name = step["name"]
            step_command = step["command"]
            retries_allowed = self._load_retry_max(run_id)
            backoff_s = self._load_retry_backoff(run_id)
            timeout_s = self._load_timeout(run_id)

            # Inject previous step context into command
            enriched_command = step_command
            if context:
                context_summary = "; ".join(
                    f"{k}={v}" for k, v in list(context.items())[-5:]
                )
                enriched_command = (
                    f"[前序步驟上下文] {context_summary}\n\n{step_command}"
                )

            # Save checkpoint: input
            self._update_step(run_id, idx, {
                "status": StepStatus.RUNNING,
                "input_snapshot": json.dumps(context, ensure_ascii=False),
                "started_at": datetime.utcnow(),
            })
            self._update_run_idx(run_id, idx)

            # Execute with retry
            success = False
            last_error = None
            attempt = 0

            while attempt <= retries_allowed:
                try:
                    loop_input = LoopInput(
                        command=enriched_command,
                        source="harness",
                        skill_hint=step.get("skill_hint"),
                        task_type="harness_step",
                    )

                    # Run with timeout
                    result = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(
                            None, main_loop.run, loop_input
                        ),
                        timeout=timeout_s,
                    )

                    if result.success:
                        # Extract output to context
                        output_text = str(result.output)[:2000] if result.output else ""
                        context[f"step_{idx}_{step_name}"] = output_text

                        self._update_step(run_id, idx, {
                            "status": StepStatus.COMPLETED,
                            "output_snapshot": json.dumps({
                                "output": output_text,
                                "tokens": result.tokens_used,
                                "model": result.model_used,
                            }, ensure_ascii=False),
                            "completed_at": datetime.utcnow(),
                            "retries": attempt,
                        })
                        self._save_context(run_id, context)
                        success = True

                        logger.info("[Harness] Step %d/%d (%s) completed (attempt %d)",
                                    idx + 1, len(steps), step_name, attempt + 1)
                        # Notify progress
                        await self._notify_progress(
                            run_id, idx + 1, len(steps), step_name, "completed"
                        )
                        break
                    else:
                        last_error = result.error or "OODA returned failure"
                        logger.warning("[Harness] Step %s failed (attempt %d): %s",
                                       step_name, attempt + 1, last_error)

                except asyncio.TimeoutError:
                    last_error = f"Step timeout after {timeout_s}s"
                    logger.warning("[Harness] Step %s timed out (attempt %d)",
                                   step_name, attempt + 1)
                except Exception as e:
                    last_error = str(e)
                    logger.error("[Harness] Step %s error (attempt %d): %s",
                                 step_name, attempt + 1, e)

                attempt += 1
                if attempt <= retries_allowed:
                    wait_time = backoff_s * attempt
                    logger.info("[Harness] Retrying step %s in %ds...",
                                step_name, wait_time)
                    await asyncio.sleep(wait_time)

            if not success:
                self._update_step(run_id, idx, {
                    "status": StepStatus.FAILED,
                    "error": last_error,
                    "retries": attempt - 1,
                    "completed_at": datetime.utcnow(),
                })
                self._set_run_status(run_id, RunStatus.FAILED, error=last_error)
                await self._notify_progress(
                    run_id, idx + 1, len(steps), step_name, "failed"
                )
                logger.error("[Harness] Run %s FAILED at step %d (%s): %s",
                             run_id, idx, step_name, last_error)
                return self.get_run(run_id)

        # All steps completed
        self._set_run_status(run_id, RunStatus.COMPLETED)
        self._update_goal_progress(run_id, 1.0)
        await self._notify_progress(run_id, len(steps), len(steps), "all", "completed")
        logger.info("[Harness] Run %s COMPLETED (%d steps)", run_id, len(steps))
        return self.get_run(run_id)

    # ── Lifecycle Controls ─────────────────────────────────────────────

    async def pause_run(self, run_id: str) -> dict:
        """Pause a running harness run."""
        status = self._load_status(run_id)
        if status != RunStatus.RUNNING:
            return {"error": f"Run {run_id} is {status}, cannot pause"}
        self._set_run_status(run_id, RunStatus.PAUSED)
        logger.info("[Harness] Run %s PAUSED", run_id)
        return self.get_run(run_id)

    async def resume_run(self, run_id: str) -> dict:
        """Resume a paused run from its checkpoint."""
        status = self._load_status(run_id)
        if status != RunStatus.PAUSED:
            return {"error": f"Run {run_id} is {status}, cannot resume"}
        # execute_run will pick up from current_step_idx
        self._set_run_status(run_id, RunStatus.PAUSED)  # keep paused until execute_run changes it
        return await self.execute_run(run_id)

    async def retry_run(self, run_id: str) -> dict:
        """Retry a failed run from the failed step."""
        status = self._load_status(run_id)
        if status != RunStatus.FAILED:
            return {"error": f"Run {run_id} is {status}, cannot retry"}

        # Reset the failed step to pending
        current_idx = self._load_current_idx(run_id)
        self._update_step(run_id, current_idx, {
            "status": StepStatus.PENDING,
            "error": None,
            "retries": 0,
        })
        self._set_run_status(run_id, RunStatus.PENDING)
        return await self.execute_run(run_id)

    async def cancel_run(self, run_id: str) -> dict:
        """Cancel a run."""
        status = self._load_status(run_id)
        if status in (RunStatus.COMPLETED, RunStatus.CANCELLED):
            return {"error": f"Run {run_id} is already {status}"}
        self._set_run_status(run_id, RunStatus.CANCELLED)
        logger.info("[Harness] Run %s CANCELLED", run_id)
        return self.get_run(run_id)

    # ── Query ──────────────────────────────────────────────────────────

    def get_run(self, run_id: str) -> dict:
        """Get run info with all steps."""
        db = next(get_db())
        try:
            run = db.query(HarnessRun_).filter_by(id=run_id).first()
            if not run:
                return {"error": f"Run {run_id} not found"}

            steps_rows = (
                db.query(HarnessStep_)
                .filter_by(run_id=run_id)
                .order_by(HarnessStep_.step_idx)
                .all()
            )
            steps = [
                {
                    "idx": s.step_idx,
                    "name": s.name,
                    "status": s.status,
                    "retries": s.retries,
                    "error": s.error,
                    "started_at": s.started_at.isoformat() if s.started_at else None,
                    "completed_at": s.completed_at.isoformat() if s.completed_at else None,
                }
                for s in steps_rows
            ]
            info = HarnessRunInfo(run, steps)
            return info.to_dict()
        finally:
            db.close()

    def list_runs(self, status: str | None = None, limit: int = 20) -> list[dict]:
        """List harness runs, optionally filtered by status."""
        db = next(get_db())
        try:
            q = db.query(HarnessRun_).order_by(HarnessRun_.created_at.desc())
            if status:
                q = q.filter_by(status=status)
            runs = q.limit(limit).all()
            return [
                {
                    "id": r.id,
                    "title": r.title,
                    "status": r.status,
                    "current_step_idx": r.current_step_idx,
                    "total_steps": len(json.loads(r.plan_json or "[]")),
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in runs
            ]
        finally:
            db.close()

    # ── Internal Helpers ───────────────────────────────────────────────

    def _load_steps(self, run_id: str) -> list[dict]:
        db = next(get_db())
        try:
            run = db.query(HarnessRun_).filter_by(id=run_id).first()
            return json.loads(run.plan_json or "[]") if run else []
        finally:
            db.close()

    def _load_context(self, run_id: str) -> dict:
        db = next(get_db())
        try:
            run = db.query(HarnessRun_).filter_by(id=run_id).first()
            return json.loads(run.context or "{}") if run else {}
        finally:
            db.close()

    def _save_context(self, run_id: str, context: dict) -> None:
        db = next(get_db())
        try:
            run = db.query(HarnessRun_).filter_by(id=run_id).first()
            if run:
                run.context = json.dumps(context, ensure_ascii=False)
                run.updated_at = datetime.utcnow()
                db.commit()
        finally:
            db.close()

    def _load_status(self, run_id: str) -> str:
        db = next(get_db())
        try:
            run = db.query(HarnessRun_).filter_by(id=run_id).first()
            return run.status if run else RunStatus.FAILED
        finally:
            db.close()

    def _load_current_idx(self, run_id: str) -> int:
        db = next(get_db())
        try:
            run = db.query(HarnessRun_).filter_by(id=run_id).first()
            return run.current_step_idx if run else 0
        finally:
            db.close()

    def _load_retry_max(self, run_id: str) -> int:
        db = next(get_db())
        try:
            run = db.query(HarnessRun_).filter_by(id=run_id).first()
            return run.retry_max if run else 3
        finally:
            db.close()

    def _load_retry_backoff(self, run_id: str) -> int:
        db = next(get_db())
        try:
            run = db.query(HarnessRun_).filter_by(id=run_id).first()
            return run.retry_backoff_s if run else 60
        finally:
            db.close()

    def _load_timeout(self, run_id: str) -> int:
        db = next(get_db())
        try:
            run = db.query(HarnessRun_).filter_by(id=run_id).first()
            return run.timeout_s if run else 600
        finally:
            db.close()

    def _update_run_idx(self, run_id: str, idx: int) -> None:
        db = next(get_db())
        try:
            run = db.query(HarnessRun_).filter_by(id=run_id).first()
            if run:
                run.current_step_idx = idx
                run.updated_at = datetime.utcnow()
                db.commit()
        finally:
            db.close()

    def _set_run_status(self, run_id: str, status: str,
                        error: str | None = None) -> None:
        db = next(get_db())
        try:
            run = db.query(HarnessRun_).filter_by(id=run_id).first()
            if run:
                run.status = status
                run.error = error
                run.updated_at = datetime.utcnow()
                if status in (RunStatus.COMPLETED, RunStatus.FAILED,
                              RunStatus.CANCELLED):
                    run.completed_at = datetime.utcnow()
                db.commit()
        finally:
            db.close()

    def _update_step(self, run_id: str, step_idx: int,
                     updates: dict[str, Any]) -> None:
        db = next(get_db())
        try:
            step = (
                db.query(HarnessStep_)
                .filter_by(run_id=run_id, step_idx=step_idx)
                .first()
            )
            if step:
                for k, v in updates.items():
                    setattr(step, k, v)
                db.commit()
        finally:
            db.close()

    def _update_goal_progress(self, run_id: str, progress: float) -> None:
        """Sync harness completion to GoalTracker if linked."""
        db = next(get_db())
        try:
            run = db.query(HarnessRun_).filter_by(id=run_id).first()
            if run and run.goal_id:
                try:
                    from loop.goal_tracker import goal_tracker
                    goal_tracker.update_progress(
                        run.goal_id, progress,
                        notes=f"Harness run {run_id} completed",
                    )
                except Exception as e:
                    logger.warning("[Harness] Failed to update goal: %s", e)
        finally:
            db.close()

    async def _notify_progress(
        self, run_id: str, current: int, total: int,
        step_name: str, step_status: str,
    ) -> None:
        """Send progress notification to configured channel."""
        db = next(get_db())
        try:
            run = db.query(HarnessRun_).filter_by(id=run_id).first()
            if not run or run.notify_channel == "none":
                return
            channel = run.notify_channel
            title = run.title
        finally:
            db.close()

        bar_len = 10
        filled = int(bar_len * current / total) if total > 0 else 0
        bar = "█" * filled + "░" * (bar_len - filled)
        pct = current / total * 100 if total > 0 else 0

        icon = "✅" if step_status == "completed" else "❌"
        msg = (
            f"🔄 **Harness: {title}**\n"
            f"{bar} {pct:.0f}% ({current}/{total})\n"
            f"{icon} Step `{step_name}` → {step_status}"
        )

        if step_status == "completed" and current == total:
            msg = (
                f"🎉 **Harness 完成: {title}**\n"
                f"{bar} 100% ({total}/{total})\n"
                f"所有 {total} 個步驟已完成！"
            )

        try:
            if channel == "telegram":
                from channels.telegram_bot import send_telegram_message
                await asyncio.get_event_loop().run_in_executor(
                    None, send_telegram_message, msg
                )
            logger.info("[Harness] Progress notification sent: %s", msg[:80])
        except Exception as e:
            logger.warning("[Harness] Notification failed: %s", e)


# ── Singleton ──
harness_engine = HarnessEngine()
