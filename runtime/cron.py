"""
ArcMind Cron 排程系統
標準 cron expression + interval 觸發。
所有排程任務執行前必須通過 MGIS Governor 審計。
與 MGIS SharedBrain 排程協調（不衝突）。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config.settings import settings
from db.schema import CronJob_, get_db

logger = logging.getLogger("arcmind.cron")


class CronSystem:
    """
    Cron 排程系統：
    - 支援標準 cron expression（"30 21 * * *"）
    - 支援 interval（每 N 秒）
    - 啟動時從 DB 恢復所有已啟用的排程
    - 執行前通過 MGIS Governor 審計
    """

    def __init__(self):
        self._scheduler = BackgroundScheduler(
            timezone=settings.cron_timezone
        )
        self._started = False

    def startup(self) -> None:
        """啟動排程器，並從 DB 恢復所有啟用的工作"""
        if self._started:
            return
        self._scheduler.start()
        self._started = True
        self._restore_from_db()
        logger.info("Cron system started. Timezone=%s", settings.cron_timezone)

    def shutdown(self) -> None:
        if self._started:
            self._scheduler.shutdown(wait=False)
            self._started = False

    # ── 新增排程 ──────────────────────────────────────────────────────────────

    def add_cron(self, name: str, cron_expr: str, skill_name: str,
                 input_data: dict | None = None,
                 governor_required: bool = True) -> dict:
        """
        新增 cron 排程。
        cron_expr: "30 21 * * *" 格式（分 時 日 月 週）
        """
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            raise ValueError(f"Invalid cron expression: {cron_expr}. Expected 5 fields.")

        minute, hour, day, month, day_of_week = parts
        trigger = CronTrigger(
            minute=minute, hour=hour, day=day,
            month=month, day_of_week=day_of_week,
            timezone=settings.cron_timezone,
        )
        return self._add_job(name, trigger, skill_name, input_data,
                             cron_expr=cron_expr, governor_required=governor_required)

    def add_interval(self, name: str, seconds: int, skill_name: str,
                     input_data: dict | None = None,
                     governor_required: bool = True) -> dict:
        """新增 interval 排程（每 N 秒執行一次）"""
        trigger = IntervalTrigger(seconds=seconds)
        return self._add_job(name, trigger, skill_name, input_data,
                             interval_s=seconds, governor_required=governor_required)

    def _add_job(self, name: str, trigger, skill_name: str,
                 input_data: dict | None,
                 cron_expr: str | None = None,
                 interval_s: int | None = None,
                 governor_required: bool = True) -> dict:
        input_data = input_data or {}

        # 儲存到 DB
        db = next(get_db())
        existing = db.query(CronJob_).filter_by(name=name).first()
        if existing:
            existing.skill_name = skill_name
            existing.cron_expr = cron_expr
            existing.interval_s = interval_s
            existing.input_data = json.dumps(input_data)
            existing.governor_required = governor_required
            existing.enabled = True
            db.commit()
            job_id = existing.id
        else:
            rec = CronJob_(
                name=name,
                cron_expr=cron_expr,
                interval_s=interval_s,
                skill_name=skill_name,
                input_data=json.dumps(input_data),
                governor_required=governor_required,
                enabled=True,
            )
            db.add(rec)
            db.commit()
            db.refresh(rec)
            job_id = rec.id

        # 加入排程器
        self._scheduler.add_job(
            func=self._run_job,
            trigger=trigger,
            id=name,
            replace_existing=True,
            kwargs={"name": name, "skill_name": skill_name,
                    "input_data": input_data, "governor_required": governor_required},
        )

        logger.info("Cron added: name=%s skill=%s cron=%s interval=%s",
                    name, skill_name, cron_expr, interval_s)
        return {"id": job_id, "name": name, "status": "scheduled"}

    # ── 刪除 / 暫停 ───────────────────────────────────────────────────────────

    def remove(self, name: str) -> None:
        try:
            self._scheduler.remove_job(name)
        except Exception:
            pass
        db = next(get_db())
        rec = db.query(CronJob_).filter_by(name=name).first()
        if rec:
            rec.enabled = False
            db.commit()
        logger.info("Cron removed: %s", name)

    def pause_job(self, name: str) -> None:
        self._scheduler.pause_job(name)

    def resume_job(self, name: str) -> None:
        self._scheduler.resume_job(name)

    # ── 執行 ──────────────────────────────────────────────────────────────────

    def _run_job(self, name: str, skill_name: str,
                 input_data: dict, governor_required: bool) -> None:
        logger.info("Cron trigger: name=%s skill=%s", name, skill_name)

        # Governor 審計
        if governor_required:
            from foundation.mgis_client import mgis
            audit = mgis.audit(
                action=f"cron_execute:{skill_name}",
                context={"cron_name": name, "input_data": input_data},
            )
            if not audit.get("approved", True):
                logger.warning("Cron %s blocked by Governor: %s",
                               name, audit.get("reason"))
                return

        # 呼叫技能
        from runtime.skill_manager import skill_manager
        try:
            result = skill_manager.invoke(skill_name, input_data)
            self._update_run(name, success=True)
            logger.info("Cron %s done: success=%s", name, result.get("success"))
        except Exception as e:
            self._update_run(name, success=False)
            logger.error("Cron %s error: %s", name, e)

    def _update_run(self, name: str, success: bool) -> None:
        try:
            db = next(get_db())
            rec = db.query(CronJob_).filter_by(name=name).first()
            if rec:
                rec.last_run = datetime.utcnow()
                rec.run_count += 1
                db.commit()
        except Exception:
            pass

    # ── 恢復 ──────────────────────────────────────────────────────────────────

    def _restore_from_db(self) -> None:
        db = next(get_db())
        jobs = db.query(CronJob_).filter_by(enabled=True).all()
        count = 0
        for job in jobs:
            try:
                input_data = json.loads(job.input_data or "{}")
                if job.cron_expr:
                    self.add_cron(
                        job.name, job.cron_expr, job.skill_name,
                        input_data, job.governor_required,
                    )
                elif job.interval_s:
                    self.add_interval(
                        job.name, job.interval_s, job.skill_name,
                        input_data, job.governor_required,
                    )
                count += 1
            except Exception as e:
                logger.warning("Failed to restore cron job %s: %s", job.name, e)
        logger.info("Restored %d cron jobs from DB.", count)

    # ── 查詢 ──────────────────────────────────────────────────────────────────

    def list_jobs(self) -> list[dict]:
        db = next(get_db())
        rows = db.query(CronJob_).all()
        result = []
        for r in rows:
            next_run = None
            try:
                job = self._scheduler.get_job(r.name)
                if job:
                    next_run = job.next_run_time.isoformat() if job.next_run_time else None
            except Exception:
                pass
            result.append({
                "id": r.id,
                "name": r.name,
                "cron_expr": r.cron_expr,
                "interval_s": r.interval_s,
                "skill_name": r.skill_name,
                "enabled": r.enabled,
                "governor_required": r.governor_required,
                "last_run": r.last_run.isoformat() if r.last_run else None,
                "next_run": next_run,
                "run_count": r.run_count,
            })
        return result

    def trigger_now(self, name: str) -> None:
        """手動立即觸發一個排程工作"""
        db = next(get_db())
        rec = db.query(CronJob_).filter_by(name=name).first()
        if not rec:
            raise ValueError(f"Cron job '{name}' not found.")
        input_data = json.loads(rec.input_data or "{}")
        self._run_job(name, rec.skill_name, input_data, rec.governor_required)


# 全域單例
cron_system = CronSystem()
