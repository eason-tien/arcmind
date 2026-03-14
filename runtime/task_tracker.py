# -*- coding: utf-8 -*-
"""
TaskTracker — 线程安全的后台任务注册表（带 SQLite 持久化）。
PM Agent 通过此模块追踪任务状态和进度。

P0-A1: 新增 SQLite write-through 層：
  - __init__ 時建表並載入未完成任務
  - create/update_status/set_result 時 write-through
  - 重啟後自動恢復 active 任務
"""
from __future__ import annotations

import json
import logging
import pathlib
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger("arcmind.task_tracker")

_DB_PATH = pathlib.Path(__file__).parent.parent / "data" / "task_tracker.db"


class TaskStatus(Enum):
    CREATED = "created"
    QUEUED = "queued"
    PLANNING = "planning"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    # V2 Phase 2
    PAUSED = "paused"
    AUDIT_REVIEW = "audit_review"


@dataclass
class TaskStep:
    index: int
    description: str
    status: TaskStatus = TaskStatus.CREATED
    result: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0


@dataclass
class TrackedTask:
    task_id: str
    command: str
    session_id: Optional[int] = None
    status: TaskStatus = TaskStatus.CREATED
    steps: list[TaskStep] = field(default_factory=list)
    current_step: int = 0
    progress_pct: float = 0.0
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    completed_at: float = 0.0
    result: Any = None
    error: Optional[str] = None
    tokens_used: int = 0
    ended_at: float = 0.0           # V2 Phase 2: when task completed/failed
    log: list[str] = field(default_factory=list)
    # V3: Worker identity
    worker_id: str = ""
    model: str = ""


class TaskTracker:
    """Thread-safe task tracker singleton with SQLite persistence."""

    def __init__(self):
        self._lock = threading.Lock()
        self._tasks: dict[str, TrackedTask] = {}
        self._db_ok = False
        self._init_db()
        self._load_active_tasks()

    # ── SQLite persistence layer ──────────────────────────────────────────

    def _init_db(self) -> None:
        try:
            _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(_DB_PATH), timeout=5)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id     TEXT PRIMARY KEY,
                    command     TEXT NOT NULL,
                    session_id  INTEGER,
                    status      TEXT NOT NULL DEFAULT 'created',
                    progress    REAL DEFAULT 0.0,
                    result_json TEXT,
                    tokens_used INTEGER DEFAULT 0,
                    worker_id   TEXT DEFAULT '',
                    model       TEXT DEFAULT '',
                    created_at  REAL,
                    started_at  REAL DEFAULT 0.0,
                    ended_at    REAL DEFAULT 0.0
                )
            """)
            conn.commit()
            conn.close()
            self._db_ok = True
            logger.info("[TaskTracker] SQLite initialized at %s", _DB_PATH)
        except Exception as e:
            logger.warning("[TaskTracker] SQLite init failed, memory-only mode: %s", e)

    def _load_active_tasks(self) -> None:
        """Restore active tasks from SQLite on startup."""
        if not self._db_ok:
            return
        try:
            conn = sqlite3.connect(str(_DB_PATH), timeout=5)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM tasks WHERE status NOT IN ('completed', 'failed', 'cancelled')"
            ).fetchall()
            conn.close()
            for row in rows:
                task = TrackedTask(
                    task_id=row["task_id"],
                    command=row["command"],
                    session_id=row["session_id"],
                    status=TaskStatus(row["status"]),
                    progress_pct=row["progress"] or 0.0,
                    tokens_used=row["tokens_used"] or 0,
                    worker_id=row["worker_id"] or "",
                    model=row["model"] or "",
                    created_at=row["created_at"] or time.time(),
                    started_at=row["started_at"] or 0.0,
                    ended_at=row["ended_at"] or 0.0,
                )
                try:
                    if row["result_json"]:
                        task.result = json.loads(row["result_json"])
                except Exception:
                    pass
                self._tasks[task.task_id] = task
            if rows:
                logger.info("[TaskTracker] Restored %d active tasks from SQLite", len(rows))
        except Exception as e:
            logger.warning("[TaskTracker] Failed to load tasks from SQLite: %s", e)

    def _persist_task(self, task: TrackedTask) -> None:
        """Write-through a single task to SQLite."""
        if not self._db_ok:
            return
        try:
            result_json = json.dumps(task.result, default=str, ensure_ascii=False)[:2000] if task.result else None
            conn = sqlite3.connect(str(_DB_PATH), timeout=5)
            conn.execute("""
                INSERT OR REPLACE INTO tasks
                    (task_id, command, session_id, status, progress, result_json,
                     tokens_used, worker_id, model, created_at, started_at, ended_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                task.task_id, task.command[:500], task.session_id,
                task.status.value, task.progress_pct, result_json,
                task.tokens_used, task.worker_id, task.model,
                task.created_at, task.started_at, task.ended_at,
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug("[TaskTracker] SQLite persist failed: %s", e)

    # ── Core API ──────────────────────────────────────────────────────────

    def create(self, command: str, session_id: int = None) -> str:
        task_id = f"pm-{uuid.uuid4().hex[:8]}"
        task = TrackedTask(task_id=task_id, command=command, session_id=session_id)
        with self._lock:
            self._tasks[task_id] = task
        self._persist_task(task)
        return task_id

    def get(self, task_id: str) -> Optional[TrackedTask]:
        with self._lock:
            return self._tasks.get(task_id)

    def get_active_for_session(self, session_id: int) -> list[TrackedTask]:
        with self._lock:
            return [
                t for t in self._tasks.values()
                if t.session_id == session_id
                and t.status in (TaskStatus.CREATED, TaskStatus.QUEUED,
                                 TaskStatus.PLANNING, TaskStatus.EXECUTING)
            ]

    def get_all_active(self) -> list[TrackedTask]:
        with self._lock:
            return [
                t for t in self._tasks.values()
                if t.status in (TaskStatus.CREATED, TaskStatus.QUEUED,
                                 TaskStatus.PLANNING, TaskStatus.EXECUTING)
            ]

    def update_status(self, task_id: str, status: TaskStatus,
                      progress_pct: float = None, log_msg: str = None) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task.status = status
            if progress_pct is not None:
                task.progress_pct = progress_pct
            if log_msg:
                task.log.append(f"[{time.strftime('%H:%M:%S')}] {log_msg}")
                # Prevent unbounded log growth
                if len(task.log) > 200:
                    task.log = task.log[-100:]
            if status == TaskStatus.EXECUTING and task.started_at == 0:
                task.started_at = time.time()
            if status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                task.completed_at = time.time()
                task.ended_at = time.time()
        # Write-through to SQLite (outside lock to avoid blocking)
        if task:
            self._persist_task(task)

    def set_plan(self, task_id: str, steps: list[str]) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task.steps = [TaskStep(index=i, description=d) for i, d in enumerate(steps)]

    def advance_step(self, task_id: str, step_index: int,
                     status: TaskStatus, result: str = "") -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task or step_index >= len(task.steps):
                return
            step = task.steps[step_index]
            step.status = status
            step.result = result[:500]
            if status == TaskStatus.EXECUTING:
                step.started_at = time.time()
            elif status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                step.completed_at = time.time()
            completed = sum(1 for s in task.steps if s.status == TaskStatus.COMPLETED)
            task.progress_pct = completed / len(task.steps) if task.steps else 0.0
            task.current_step = step_index

    def set_worker_info(self, task_id: str, worker_id: str, model: str) -> None:
        """V3: Record PM worker identity for monitoring."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.worker_id = worker_id
                task.model = model

    def set_result(self, task_id: str, result: Any, tokens: int = 0) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.result = result
                task.tokens_used = tokens
        # Write-through to SQLite
        if task:
            self._persist_task(task)


    def get_recently_completed(self, session_id: int = None, within_minutes: int = 30) -> list[TrackedTask]:
        """V2 Phase 2: Return tasks completed within the last N minutes."""
        cutoff = time.time() - (within_minutes * 60)
        with self._lock:
            return [
                t for t in self._tasks.values()
                if (session_id is None or t.session_id == session_id)
                and t.status == TaskStatus.COMPLETED
                and t.ended_at > 0 and t.ended_at >= cutoff
            ]

    def format_progress(self, task_id: str) -> str:
        task = self.get(task_id)
        if not task:
            return "Task not found."
        elapsed = time.time() - task.created_at
        if elapsed < 60:
            elapsed_str = f"{int(elapsed)}s"
        else:
            elapsed_str = f"{int(elapsed/60)}m{int(elapsed%60)}s"

        # V3: Worker identity line
        worker_info = ""
        if task.worker_id:
            worker_info = f" | Worker: {task.worker_id}"
        if task.model:
            worker_info += f" | Model: {task.model.split(':')[-1]}"

        # Progress bar
        bar_len = 10
        filled = int(task.progress_pct * bar_len)
        bar = "█" * filled + "░" * (bar_len - filled)

        lines = [
            f"📋 任务: {task.command[:80]}",
            f"状态: {task.status.value} | [{bar}] {task.progress_pct:.0%} | 耗时: {elapsed_str}{worker_info}",
        ]
        if task.steps:
            for step in task.steps:
                icons = {
                    "created": "⬜", "queued": "⏳", "planning": "📐",
                    "executing": "🔧", "completed": "✅", "failed": "❌",
                    "cancelled": "🚫",
                }
                icon = icons.get(step.status.value, "⬜")
                lines.append(f"  {icon} Step {step.index+1}: {step.description[:60]}")
        if task.log:
            lines.append(f"\n最新: {task.log[-1]}")
        if task.result and task.status == TaskStatus.COMPLETED:
            preview = str(task.result)[:200]
            lines.append(f"\n结果预览: {preview}")
        return "\n".join(lines)

    def format_all_active(self, session_id: int = None) -> str:
        if session_id:
            tasks = self.get_active_for_session(session_id)
        else:
            tasks = self.get_all_active()
        if not tasks:
            return ""
        reports = [self.format_progress(t.task_id) for t in tasks]
        return "\n\n---\n\n".join(reports)

    def format_pm_dashboard(self, session_id: int = None) -> str:
        """V3: CEO-level PM pool monitoring dashboard."""
        try:
            from runtime.pm_agent import pm_pool
            stats = pm_pool.get_pool_stats()
            workers = pm_pool.get_worker_status()
        except Exception:
            stats = {}
            workers = []

        lines = ["🏭 **PM Agent 多线程面板**"]
        lines.append(
            f"  Workers: {stats.get('active', 0)}/{stats.get('max_workers', 5)} 活跃 | "
            f"总投递: {stats.get('total_submitted', 0)} | "
            f"完成: {stats.get('total_completed', 0)} | "
            f"失败: {stats.get('total_failed', 0)}"
        )

        if workers:
            lines.append("")
            for w in workers:
                status_icon = "🟢" if w.get("running") else "⚪"
                elapsed = w.get("elapsed_s", 0)
                if elapsed < 60:
                    elapsed_str = f"{int(elapsed)}s"
                else:
                    elapsed_str = f"{int(elapsed/60)}m{int(elapsed%60)}s"
                model_short = w.get("model", "?").split(":")[-1]
                lines.append(
                    f"  {status_icon} [{w.get('worker_id', '?')}] "
                    f"{w.get('command', '?')[:50]} "
                    f"({model_short}, {elapsed_str})"
                )

        # Active task details
        task_report = self.format_all_active(session_id)
        if task_report:
            lines.append(f"\n{'─' * 40}")
            lines.append(task_report)

        if not workers and not task_report:
            lines.append("  当前无 PM 任务在运行。")

        return "\n".join(lines)

    def cleanup_old(self, max_age_hours: float = 24.0) -> int:
        cutoff = time.time() - max_age_hours * 3600
        removed = 0
        with self._lock:
            to_remove = [
                tid for tid, t in self._tasks.items()
                if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
                and t.completed_at > 0 and t.completed_at < cutoff
            ]
            for tid in to_remove:
                del self._tasks[tid]
                removed += 1
        return removed


# Singleton
task_tracker = TaskTracker()
