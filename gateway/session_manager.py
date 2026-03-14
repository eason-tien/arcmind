# -*- coding: utf-8 -*-
"""
ArcMind Gateway — Session Manager
===================================
有狀態的會話管理器：建立、恢復、銷毀 Session，
整合 TaskStateMachine、Context Compressor 與 DB 持久化。

架構：Write-Through Cache
  - 每次寫入操作同時更新 RAM 和 SQLite
  - 讀取優先從 RAM（快），未命中則從 DB 載入
  - 永不丟資料：每次操作都持久化
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from db.schema import SessionLocal, Session_

logger = logging.getLogger("arcmind.gateway.session")


# ── Data Structures ─────────────────────────────────────────────────────────

@dataclass
class ConversationTurn:
    """Single conversation turn."""
    role: str           # user | assistant | system
    content: str
    timestamp: str = ""
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class SessionContext:
    """
    Session context — 同時作為 RAM 快取和 DB 的橋樑。
    每個 session 維護完整的對話歷史、任務狀態、上下文。
    """
    session_id: str
    channel: str = "unknown"            # telegram | cli | websocket | api
    user_id: str = ""

    # ── Task State ──
    active_task_id: int | None = None
    state: str = "idle"                 # idle | compiling | planning | acting | verifying | done | failed

    # ── Conversation ──
    history: list[dict] = field(default_factory=list)    # [{role, content, timestamp}]
    context_summary: str = ""                             # compressed context

    # ── Persona ──
    agent_type: str = "main"            # main | group | specialist

    # ── Budget ──
    turn_count: int = 0
    tokens_used: int = 0
    max_turns: int = 100
    max_tokens: int = 100_000

    # ── Timestamps ──
    created_at: str = ""
    updated_at: str = ""
    last_activity: str = ""

    def __post_init__(self):
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now
        if not self.last_activity:
            self.last_activity = now

    # ── Conversation helpers ──

    def add_turn(self, role: str, content: str, **metadata) -> None:
        """Add a conversation turn to history."""
        turn = ConversationTurn(role=role, content=content, metadata=metadata)
        self.history.append(asdict(turn))
        self.turn_count += 1
        self.last_activity = datetime.now(timezone.utc).isoformat()
        self.updated_at = self.last_activity
        # Cap in-memory history to prevent unbounded growth
        if len(self.history) > 200:
            self.history = self.history[-100:]

    def get_recent_history(self, n: int = 20) -> list[dict]:
        """Get last N turns of conversation history."""
        return self.history[-n:]

    def is_over_budget(self) -> bool:
        return self.tokens_used >= self.max_tokens or self.turn_count >= self.max_turns

    @property
    def has_active_task(self) -> bool:
        return (
            self.active_task_id is not None
            and self.state not in ("idle", "done", "failed", "cancelled")
        )


# ── Session Manager ─────────────────────────────────────────────────────────

class SessionManager:
    """
    Write-Through Cache 式 Session Manager。
    
    每次寫入同時更新 RAM + SQLite，讀取優先從 RAM。
    不再需要背景線程或 dirty flag，永不丟資料。
    """

    def __init__(self):
        self._sessions: dict[str, SessionContext] = {}
        self._lock = threading.RLock()
        logger.info("[SessionManager] initialized (write-through mode)")

    def stop(self) -> None:
        """Graceful shutdown — no background thread to stop."""
        logger.info("[SessionManager] stopped")

    # ── CRUD ──────────────────────────────────────────────────────────────

    def get_or_create(
        self,
        session_id: str,
        channel: str = "unknown",
        user_id: str = "",
        agent_type: str = "main",
    ) -> SessionContext:
        """Get existing session or create a new one."""
        with self._lock:
            # 1. Check RAM cache
            if session_id in self._sessions:
                return self._sessions[session_id]

            # 2. Try to restore from DB
            ctx = self._load_from_db(session_id)
            if ctx:
                self._sessions[session_id] = ctx
                logger.info("[SessionManager] restored session %s from DB", session_id)
                return ctx

            # 3. Create new → immediately persist
            ctx = SessionContext(
                session_id=session_id,
                channel=channel,
                user_id=user_id,
                agent_type=agent_type,
            )
            self._sessions[session_id] = ctx
            self._save_to_db(ctx)
            logger.info("[SessionManager] new session: %s (channel=%s, agent=%s)",
                        session_id, channel, agent_type)
            return ctx

    def get(self, session_id: str) -> SessionContext | None:
        """Get session without creating."""
        with self._lock:
            ctx = self._sessions.get(session_id)
            if ctx:
                return ctx
            # Try DB
            ctx = self._load_from_db(session_id)
            if ctx:
                self._sessions[session_id] = ctx
            return ctx

    def update(self, session_id: str, **kwargs) -> SessionContext | None:
        """Update session fields and persist immediately."""
        with self._lock:
            ctx = self._sessions.get(session_id)
            if not ctx:
                return None
            for k, v in kwargs.items():
                if hasattr(ctx, k):
                    setattr(ctx, k, v)
            ctx.updated_at = datetime.now(timezone.utc).isoformat()
            self._save_to_db(ctx)
            return ctx

    def end_session(self, session_id: str) -> None:
        """End and archive a session."""
        with self._lock:
            ctx = self._sessions.pop(session_id, None)
            if ctx:
                self._update_db_status(session_id, "ended")
                logger.info("[SessionManager] ended session %s (turns=%d, tokens=%d)",
                            session_id, ctx.turn_count, ctx.tokens_used)

    # ── Task management ──

    def set_active_task(self, session_id: str, task_id: int, state: str = "compiling") -> None:
        """Mark a task as active in this session."""
        self.update(session_id, active_task_id=task_id, state=state)

    def clear_task(self, session_id: str) -> None:
        """Clear active task (task done/failed/cancelled)."""
        self.update(session_id, active_task_id=None, state="idle")

    # ── Conversation ──

    def add_turn(self, session_id: str, role: str, content: str, **metadata) -> None:
        """Add a conversation turn and immediately persist."""
        with self._lock:
            ctx = self._sessions.get(session_id)
            if ctx:
                ctx.add_turn(role, content, **metadata)
                self._save_to_db(ctx)

    def consume_tokens(self, session_id: str, tokens: int) -> None:
        """Record token usage and immediately persist."""
        with self._lock:
            ctx = self._sessions.get(session_id)
            if ctx:
                ctx.tokens_used += tokens
                ctx.updated_at = datetime.now(timezone.utc).isoformat()
                self._save_to_db(ctx)

    # ── Listing / Debug ──

    def list_sessions(self) -> list[dict]:
        """List all active sessions."""
        with self._lock:
            return [
                {
                    "session_id": ctx.session_id,
                    "channel": ctx.channel,
                    "user_id": ctx.user_id,
                    "agent_type": ctx.agent_type,
                    "state": ctx.state,
                    "turn_count": ctx.turn_count,
                    "tokens_used": ctx.tokens_used,
                    "has_active_task": ctx.has_active_task,
                    "last_activity": ctx.last_activity,
                }
                for ctx in self._sessions.values()
            ]

    def active_count(self) -> int:
        with self._lock:
            return len(self._sessions)

    def summary(self) -> dict:
        return {
            "active_sessions": self.active_count(),
            "sessions": self.list_sessions(),
        }

    # ── DB Persistence ───────────────────────────────────────────────────

    def _load_from_db(self, session_id: str) -> SessionContext | None:
        """Load session from DB."""
        db = None
        try:
            db = SessionLocal()
            row = db.query(Session_).filter(
                Session_.name == session_id,
                Session_.status == "active",
            ).first()
            if not row:
                return None

            ctx_data = json.loads(row.context or "{}")
            ctx = SessionContext(
                session_id=session_id,
                channel=ctx_data.get("channel", "unknown"),
                user_id=ctx_data.get("user_id", ""),
                agent_type=ctx_data.get("agent_type", "main"),
                history=ctx_data.get("history", []),
                context_summary=ctx_data.get("context_summary", ""),
                state=ctx_data.get("state", "idle"),
                turn_count=ctx_data.get("turn_count", 0),
                tokens_used=ctx_data.get("tokens_used", 0),
                created_at=row.created_at.isoformat() if row.created_at else "",
                updated_at=row.updated_at.isoformat() if row.updated_at else "",
            )
            return ctx
        except Exception as e:
            logger.warning("[SessionManager] DB load failed for %s: %s", session_id, e)
            return None
        finally:
            if db:
                db.close()

    def _save_to_db(self, ctx: SessionContext) -> None:
        """Save session state to DB (write-through) with proper error handling."""
        db = None
        try:
            db = SessionLocal()
            ctx_json = json.dumps({
                "channel": ctx.channel,
                "user_id": ctx.user_id,
                "agent_type": ctx.agent_type,
                "state": ctx.state,
                "history": ctx.history[-50:],  # Keep last 50 turns in DB
                "context_summary": ctx.context_summary,
                "turn_count": ctx.turn_count,
                "tokens_used": ctx.tokens_used,
            }, ensure_ascii=False, default=str)

            row = db.query(Session_).filter(Session_.name == ctx.session_id).first()
            if row:
                row.context = ctx_json
                row.status = "active"
            else:
                row = Session_(
                    name=ctx.session_id,
                    status="active",
                    context=ctx_json,
                )
                db.add(row)
            db.commit()
        except Exception as e:
            if db:
                db.rollback()
            logger.warning("[SessionManager] DB save failed for %s: %s", ctx.session_id, e)
        finally:
            if db:
                db.close()

    def _update_db_status(self, session_id: str, status: str) -> None:
        """Update session status in DB."""
        db = None
        try:
            db = SessionLocal()
            row = db.query(Session_).filter(Session_.name == session_id).first()
            if row:
                row.status = status
                db.commit()
        except Exception as e:
            if db:
                db.rollback()
            logger.warning("[SessionManager] DB update failed for %s: %s", session_id, e)
        finally:
            if db:
                db.close()

    # ── Context Compression (migrated from ARCHILLX v0.44) ───────────────

    def compress_context(self, session_id: str) -> str:
        """
        Compress session history into a structured summary.
        Migrated from ARCHILLX v0.44 session/compressor.py.
        Avoids「越用越慢」by capping context length.
        """
        with self._lock:
            ctx = self._sessions.get(session_id)
            if not ctx:
                return ""

            lines = []
            if ctx.state != "idle":
                lines.append(f"[狀態] {ctx.state}")
            if ctx.agent_type != "main":
                lines.append(f"[Agent] {ctx.agent_type}")

            # Recent intents
            user_msgs = [t for t in ctx.history if t.get("role") == "user"]
            if user_msgs:
                recent_intents = [m["content"][:60] for m in user_msgs[-5:]]
                lines.append(f"[近期意圖] {' → '.join(recent_intents)}")

            # Key results from assistant
            asst_msgs = [t for t in ctx.history if t.get("role") == "assistant"]
            for msg in asst_msgs[-3:]:
                content = msg.get("content", "")
                for marker in ("✅", "完成", "結果:", "結論:"):
                    if marker in content:
                        idx = content.index(marker)
                        fact = content[idx:idx+80].split("\n")[0].strip()
                        if len(fact) > 5:
                            lines.append(f"[結果] {fact}")
                        break

            summary = "\n".join(lines)[:4000]
            ctx.context_summary = summary
            self._save_to_db(ctx)
            return summary


# ── Singleton ──
session_manager = SessionManager()
