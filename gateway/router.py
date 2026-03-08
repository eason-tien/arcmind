# -*- coding: utf-8 -*-
"""
ArcMind Gateway — Message Router
==================================
OpenClaw 風格的消息路由器：根據 session context 將消息分發到正確的
Agent / OODA Loop 處理器。

路由策略：
1. 已有活動任務的 session → 續接（continuation）
2. /cancel 等指令 → 直接處理
3. 新消息 → 根據 agent_type 選擇處理管道
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Awaitable

logger = logging.getLogger("arcmind.gateway.router")


# ── Message Protocol ────────────────────────────────────────────────────────

@dataclass
class InboundMessage:
    """
    Unified inbound message protocol for all channels.
    Migrated from ARCHILLX v0.44 channels/inbound.py.
    """
    channel: str                        # telegram | cli | websocket | api
    user_id: str
    session_id: str
    text: str
    attachments: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    timestamp: str = ""
    message_id: str = ""
    reply_to: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        if not self.session_id:
            self.session_id = f"{self.channel}_{self.user_id}"

    # ── Factory Methods ──

    @classmethod
    def from_telegram(cls, update: dict, chat_id: int | str,
                      session_id: str = "") -> "InboundMessage":
        msg = update.get("message", update)
        text = msg.get("text", "")
        user = msg.get("from", {})
        user_id = str(user.get("id", chat_id))

        attachments = []
        for att_type in ("photo", "document", "audio", "video", "voice"):
            if att_type in msg:
                att = msg[att_type]
                if isinstance(att, list):
                    att = att[-1]
                attachments.append({
                    "type": att_type,
                    "file_id": att.get("file_id", ""),
                })

        return cls(
            channel="telegram",
            user_id=user_id,
            session_id=session_id or f"tg_{chat_id}",
            text=text,
            attachments=attachments,
            metadata={
                "chat_id": str(chat_id),
                "message_id": str(msg.get("message_id", "")),
                "username": user.get("username", ""),
                "first_name": user.get("first_name", ""),
            },
            message_id=str(msg.get("message_id", "")),
        )

    @classmethod
    def from_cli(cls, text: str, user_id: str = "cli") -> "InboundMessage":
        return cls(
            channel="cli",
            user_id=user_id,
            session_id=f"cli_{user_id}",
            text=text,
        )

    @classmethod
    def from_websocket(cls, data: dict) -> "InboundMessage":
        return cls(
            channel="websocket",
            user_id=data.get("user_id", "ws"),
            session_id=data.get("session_id", f"ws_{data.get('user_id', 'anon')}"),
            text=data.get("text", ""),
            attachments=data.get("attachments", []),
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def from_api(cls, command: str, user_id: str = "api",
                 session_id: str = "", **kwargs) -> "InboundMessage":
        return cls(
            channel="api",
            user_id=user_id,
            session_id=session_id or f"api_{user_id}",
            text=command,
            metadata=kwargs,
        )


@dataclass
class OutboundMessage:
    """Response message from the agent back to the channel."""
    session_id: str
    text: str
    channel: str = ""
    attachments: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


# ── Route Decision ──────────────────────────────────────────────────────────

class RouteAction(str, Enum):
    """What the router decides to do with a message."""
    CONTINUE_TASK = "continue_task"      # Continue existing active task
    NEW_TASK = "new_task"                # Start a new OODA loop iteration
    SYSTEM_COMMAND = "system_command"     # Internal command (/cancel, /status, etc.)
    HEARTBEAT_REPLY = "heartbeat_reply"  # Respond to a heartbeat prompt


@dataclass
class RouteDecision:
    """Result of routing a message."""
    action: RouteAction
    session_id: str
    agent_type: str = "main"
    command: str = ""         # for SYSTEM_COMMAND
    confidence: float = 1.0


# ── Router ──────────────────────────────────────────────────────────────────

# System commands that bypass the OODA loop
_SYSTEM_COMMANDS = {
    "/cancel", "/status", "/help", "/reset", "/sessions",
    "/health", "/skills", "/models", "/version",
    "/install", "/remove_skill",
}


class MessageRouter:
    """
    OpenClaw-style message router.
    Decides how to handle each inbound message based on session context.
    """

    def __init__(self):
        self._agent_handlers: dict[str, Callable] = {}
        logger.info("[MessageRouter] initialized")

    def register_agent(self, agent_type: str, handler: Callable) -> None:
        """Register a handler for a specific agent type."""
        self._agent_handlers[agent_type] = handler
        logger.info("[MessageRouter] registered agent handler: %s", agent_type)

    def route(self, msg: InboundMessage, session_context: dict | None = None) -> RouteDecision:
        """
        Decide how to handle an inbound message.

        Priority:
        1. System commands → SYSTEM_COMMAND
        2. Session has active task → CONTINUE_TASK
        3. Otherwise → NEW_TASK
        """
        text = msg.text.strip()

        # 1. System commands
        cmd = text.split()[0].lower() if text else ""
        if cmd in _SYSTEM_COMMANDS:
            return RouteDecision(
                action=RouteAction.SYSTEM_COMMAND,
                session_id=msg.session_id,
                command=text,  # Pass full text so arguments are preserved
            )

        # 2. Session has active task → continuation
        if session_context and session_context.get("has_active_task"):
            return RouteDecision(
                action=RouteAction.CONTINUE_TASK,
                session_id=msg.session_id,
                agent_type=session_context.get("agent_type", "main"),
            )

        # 3. New task → determine agent type
        agent_type = self._pick_agent(msg, session_context)
        return RouteDecision(
            action=RouteAction.NEW_TASK,
            session_id=msg.session_id,
            agent_type=agent_type,
        )

    def _pick_agent(self, msg: InboundMessage, session_context: dict | None) -> str:
        """
        Pick appropriate agent type for a new task.
        Simple rule-based routing (can upgrade to LLM-based later).
        """
        # If session already has an assigned agent type, use it
        if session_context:
            return session_context.get("agent_type", "main")

        # Group chat detection (Telegram group_id in metadata)
        if msg.metadata.get("chat_type") in ("group", "supergroup"):
            return "group"

        return "main"

    def get_handler(self, agent_type: str) -> Callable | None:
        """Get the registered handler for an agent type."""
        return self._agent_handlers.get(agent_type)


# ── Singleton ──
message_router = MessageRouter()
