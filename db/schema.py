"""
ArcMind SQLite schema.
獨立 DB，不修改 MGIS 的資料庫。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Generator

from sqlalchemy import (
    Boolean, Column, DateTime, Integer, String, Text,
    Float, create_engine, event
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool

from config.settings import settings

# ── Engine ──────────────────────────────────────────────────────────────────
# NullPool: SQLite 不需要連線池，每次呼叫建立新連線，避免 QueuePool 耗盡
engine = create_engine(
    f"sqlite:///{settings.db_path}",
    connect_args={"check_same_thread": False},
    poolclass=NullPool,
)

# WAL mode for concurrent reads
@event.listens_for(engine, "connect")
def set_sqlite_pragma(conn, _):
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


# ── Base ─────────────────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    pass


# ── Tables ───────────────────────────────────────────────────────────────────

class Session_(Base):
    """使用者 Session 生命週期"""
    __tablename__ = "am_sessions"

    id        = Column(Integer, primary_key=True, autoincrement=True)
    name      = Column(String(128), nullable=False)
    status    = Column(String(32), default="active")   # active|paused|ended
    context   = Column(Text, default="{}")             # JSON
    goal_ids  = Column(Text, default="[]")             # JSON list of goal ids
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Task_(Base):
    """任務生命週期"""
    __tablename__ = "am_tasks"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    session_id   = Column(Integer, nullable=True)
    assigned_to  = Column(String(64), default="ceo")      # sub-agent role/id assigned to
    parent_task_id = Column(Integer, nullable=True)       # for sub-tasks
    title        = Column(String(256), nullable=False)
    skill_name   = Column(String(128), nullable=True)
    task_type    = Column(String(64), default="general")
    status       = Column(String(32), default="created")  # created|assigned|executing|verifying|closed|failed
    input_data   = Column(Text, default="{}")   # JSON
    output_data  = Column(Text, default="{}")   # JSON
    governor_ok  = Column(Boolean, default=False)
    model_used   = Column(String(64), nullable=True)
    tokens_used  = Column(Integer, default=0)
    error_msg    = Column(Text, nullable=True)
    created_at   = Column(DateTime, default=datetime.utcnow)
    updated_at   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    closed_at    = Column(DateTime, nullable=True)


class Agent_(Base):
    """Agent 實例生命週期"""
    __tablename__ = "am_agents"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    session_id   = Column(Integer, nullable=True)
    agent_type   = Column(String(64), default="general")
    status       = Column(String(32), default="idle")   # spawned|running|idle|terminated
    current_task = Column(Integer, nullable=True)       # task id
    metadata_    = Column(Text, default="{}")           # JSON
    created_at   = Column(DateTime, default=datetime.utcnow)
    terminated_at = Column(DateTime, nullable=True)


class Goal_(Base):
    """長期目標追蹤"""
    __tablename__ = "am_goals"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    title       = Column(String(256), nullable=False)
    description = Column(Text, default="")
    status      = Column(String(32), default="active")   # active|paused|completed|abandoned
    progress    = Column(Float, default=0.0)             # 0.0–1.0
    priority    = Column(Integer, default=5)             # 1(highest)–10(lowest)
    context     = Column(Text, default="{}")             # JSON: sub-tasks, notes, links
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SkillRegistry_(Base):
    """本地 Skill 登錄表"""
    __tablename__ = "am_skills"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    name        = Column(String(128), unique=True, nullable=False)
    version     = Column(String(32), default="1.0")
    description = Column(Text, default="")
    manifest    = Column(Text, default="{}")   # JSON: full manifest
    source      = Column(String(32), default="local")  # local|openclaw
    enabled     = Column(Boolean, default=True)
    invoke_count = Column(Integer, default=0)
    error_count  = Column(Integer, default=0)
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CronJob_(Base):
    """Cron 排程任務"""
    __tablename__ = "am_cron_jobs"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    name        = Column(String(128), unique=True, nullable=False)
    cron_expr   = Column(String(64), nullable=True)    # standard cron expression
    interval_s  = Column(Integer, nullable=True)       # interval in seconds (alt to cron)
    skill_name  = Column(String(128), nullable=False)
    input_data  = Column(Text, default="{}")           # JSON input for skill
    enabled     = Column(Boolean, default=True)
    governor_required = Column(Boolean, default=True)
    last_run    = Column(DateTime, nullable=True)
    next_run    = Column(DateTime, nullable=True)
    run_count   = Column(Integer, default=0)
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class BrowserSession_(Base):
    """瀏覽器自動化 Session 記錄"""
    __tablename__ = "am_browser_sessions"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    task_id     = Column(Integer, nullable=True)
    url         = Column(Text, nullable=True)
    status      = Column(String(32), default="active")  # active|closed|error
    actions     = Column(Text, default="[]")             # JSON list of actions taken
    screenshot  = Column(Text, nullable=True)            # base64 last screenshot
    created_at  = Column(DateTime, default=datetime.utcnow)
    closed_at   = Column(DateTime, nullable=True)


class Memory_(Base):
    """四層認知記憶（episodic / semantic / procedural / causal）"""
    __tablename__ = "am_memory"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    content      = Column(Text, nullable=False)
    memory_type  = Column(String(32), default="episodic")  # episodic|semantic|procedural|causal
    source       = Column(String(64), default="conversation")
    importance   = Column(Float, default=0.5)              # 0.0–1.0
    tags         = Column(Text, default="[]")              # JSON list
    metadata_    = Column(Text, default="{}")              # JSON
    embedding_json = Column(Text, nullable=True)           # JSON float array
    created_at   = Column(DateTime, default=datetime.utcnow)
    updated_at   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class IterationRecord_(Base):
    """Weekly self-iteration meeting records"""
    __tablename__ = "am_iterations"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    week_id      = Column(String(16), nullable=False)       # "2026-W10"
    phase        = Column(String(32), default="planned")     # planned|executing|completed|failed
    report       = Column(Text, default="{}")                # JSON: full meeting report
    plan         = Column(Text, default="[]")                # JSON: list of iteration tasks
    results      = Column(Text, default="{}")                # JSON: execution results
    created_at   = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class EnvTopology_(Base):
    """環境拓撲知識圖譜 — 三維度認知掃描持久化"""
    __tablename__ = "am_env_topology"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    layer      = Column(String(8), nullable=False)    # L1 / L2 / L3
    category   = Column(String(64), nullable=False)   # host / ports / services / arp / etc
    data       = Column(Text, default="{}")            # JSON
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── Init ─────────────────────────────────────────────────────────────────────
import db.harness_schema as _harness_schema  # noqa: F401 — register harness tables

def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

from contextlib import contextmanager

@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """Safe context manager to prevent connection leaks."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
