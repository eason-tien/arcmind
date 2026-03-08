# -*- coding: utf-8 -*-
"""
ArcMind — Harness Schema
===========================
長時間任務編排引擎的持久化表結構。
匯入此模組後，Base.metadata.create_all() 會自動建立表。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Column, DateTime, ForeignKey, Integer, String, Text,
)

from db.schema import Base


class HarnessRun_(Base):
    """長時間任務執行記錄"""
    __tablename__ = "am_harness_runs"

    id              = Column(String(36), primary_key=True)       # UUID
    goal_id         = Column(Integer, nullable=True)              # → am_goals.id
    title           = Column(String(256), nullable=False)
    status          = Column(String(32), default="pending")       # pending|running|paused|completed|failed|cancelled
    plan_json       = Column(Text, default="[]")                  # JSON: ordered step definitions
    context         = Column(Text, default="{}")                  # JSON: cross-step shared context
    current_step_idx = Column(Integer, default=0)
    retry_max       = Column(Integer, default=3)
    retry_backoff_s = Column(Integer, default=60)
    timeout_s       = Column(Integer, default=600)                # per-step timeout
    error           = Column(Text, nullable=True)
    notify_channel  = Column(String(32), default="telegram")      # telegram|websocket|none
    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at    = Column(DateTime, nullable=True)


class HarnessStep_(Base):
    """長時間任務的單一步驟"""
    __tablename__ = "am_harness_steps"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    run_id          = Column(String(36), ForeignKey("am_harness_runs.id"), nullable=False)
    step_idx        = Column(Integer, nullable=False)
    name            = Column(String(128), nullable=False)
    command         = Column(Text, nullable=False)                 # 送入 OODA loop 的指令
    skill_hint      = Column(String(128), nullable=True)           # optional skill hint
    status          = Column(String(32), default="pending")        # pending|running|completed|failed|skipped
    input_snapshot  = Column(Text, default="{}")                   # JSON: step 開始時的上下文快照
    output_snapshot = Column(Text, default="{}")                   # JSON: step 完成後的結果
    retries         = Column(Integer, default=0)
    error           = Column(Text, nullable=True)
    started_at      = Column(DateTime, nullable=True)
    completed_at    = Column(DateTime, nullable=True)
