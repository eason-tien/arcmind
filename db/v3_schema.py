"""
ArcMind — V3 Schema Extensions
Governance, closure, and iteration tracking tables.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Integer, String, Text, Float,
    event, create_engine
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool

from config.settings import settings

# ── Engine ──────────────────────────────────────────────────────────────────
engine = create_engine(
    f"sqlite:///{settings.db_path}",
    connect_args={"check_same_thread": False},
    poolclass=NullPool,
)

@event.listens_for(engine, "connect")
def set_sqlite_pragma(conn, _):
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")


# ── Base ─────────────────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    pass


# ── Iteration Tracking Tables ───────────────────────────────────────────────

class IterationRecord_(Base):
    """迭代追踪记录 — 记录每次修复的内容、时间和结果"""
    __tablename__ = "am_iteration_records"

    id                = Column(Integer, primary_key=True, autoincrement=True)
    
    # 基本信息
    title             = Column(String(256), nullable=False)           # 修复标题
    description       = Column(Text, default="")                      # 修复内容描述
    issue_found_at    = Column(DateTime, nullable=True)                # 发现问题的时间
    fix_started_at    = Column(DateTime, nullable=True)               # 修复开始时间
    fix_completed_at  = Column(DateTime, nullable=True)               # 修复完成时间
    
    # 修复结果
    result            = Column(String(32), default="pending")         # pending|success|partial|failed
    result_detail     = Column(Text, default="")                      # 结果详情
    
    # 涉及内容
    files_involved    = Column(Text, default="[]")                    # JSON: 文件路径列表
    fixer             = Column(String(64), default="system")          # 修复人 (agent_id)
    
    # 操作日志
    operation_log     = Column(Text, default="[]")                    # JSON: 操作步骤列表
    
    # 元数据
    iteration_type    = Column(String(32), default="fix")              # fix|improvement|feature
    severity          = Column(String(16), default="medium")          # low|medium|high|critical
    tags              = Column(Text, default="[]")                     # JSON: 标签列表
    
    created_at         = Column(DateTime, default=datetime.utcnow)
    updated_at         = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class IterationSnapshot_(Base):
    """迭代快照 — 记录每次迭代的系统状态"""
    __tablename__ = "am_iteration_snapshots"

    id                = Column(Integer, primary_key=True, autoincrement=True)
    iteration_id      = Column(Integer, nullable=False)                 # 关联的迭代记录
    
    # 系统状态快照
    task_count        = Column(Integer, default=0)                     # 总任务数
    task_active       = Column(Integer, default=0)                      # 进行中任务数
    task_closed       = Column(Integer, default=0)                      # 已完成任务数
    project_count     = Column(Integer, default=0)                     # 项目数
    
    # 数据库状态
    db_size_kb        = Column(Float, nullable=True)                    # 数据库大小 KB
    table_count       = Column(Integer, default=0)                      # 表数量
    
    # 快照数据
    snapshot_data     = Column(Text, default="{}")                     # JSON: 详细快照
    
    created_at        = Column(DateTime, default=datetime.utcnow)


# ── Init ─────────────────────────────────────────────────────────────────────
def init_v3_schema() -> None:
    """Initialize V3 tables if they don't exist."""
    Base.metadata.create_all(bind=engine)


# ── Helper for session ─────────────────────────────────────────────────────
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_v3_db() -> Session:
    """Get a new database session."""
    return SessionLocal()
