# -*- coding: utf-8 -*-
"""
ArcMind Gateway — Unit Tests
==============================
Tests for Phase 1: Gateway Control Plane

Covers:
- SessionManager: create, get, update, persist, compression
- MessageRouter: routing decisions, system commands, agent selection
- InboundMessage: factory methods for all channels
- OutboundMessage: construction
- DeliveryQueue: put/get operations
"""
from __future__ import annotations

import asyncio
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Override DB to use in-memory SQLite for tests
os.environ["ARCMIND_ENV"] = "test"

import pytest


# ──────────────────────────────────────────────────────────────────────────────
#  Session Manager Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestSessionManager:
    """Tests for gateway/session_manager.py"""

    def setup_method(self):
        """Reset singleton state for each test."""
        from gateway.session_manager import SessionManager
        self.sm = SessionManager()

    def test_get_or_create_new_session(self):
        ctx = self.sm.get_or_create("test_session_1", channel="cli", user_id="user1")
        assert ctx.session_id == "test_session_1"
        assert ctx.channel == "cli"
        assert ctx.user_id == "user1"
        assert ctx.state == "idle"
        assert ctx.turn_count == 0

    def test_get_or_create_returns_existing(self):
        ctx1 = self.sm.get_or_create("test_session_2")
        ctx2 = self.sm.get_or_create("test_session_2")
        assert ctx1 is ctx2  # Same object

    def test_update_session(self):
        self.sm.get_or_create("test_session_3")
        ctx = self.sm.update("test_session_3", state="acting", tokens_used=100)
        assert ctx.state == "acting"
        assert ctx.tokens_used == 100

    def test_update_nonexistent_returns_none(self):
        result = self.sm.update("nonexistent", state="idle")
        assert result is None

    def test_add_turn(self):
        self.sm.get_or_create("test_session_4")
        self.sm.add_turn("test_session_4", "user", "Hello")
        self.sm.add_turn("test_session_4", "assistant", "Hi there!")
        ctx = self.sm.get("test_session_4")
        assert ctx.turn_count == 2
        assert len(ctx.history) == 2
        assert ctx.history[0]["role"] == "user"
        assert ctx.history[1]["content"] == "Hi there!"

    def test_set_and_clear_task(self):
        self.sm.get_or_create("test_session_5")
        self.sm.set_active_task("test_session_5", task_id=42, state="compiling")
        ctx = self.sm.get("test_session_5")
        assert ctx.active_task_id == 42
        assert ctx.state == "compiling"
        assert ctx.has_active_task is True

        self.sm.clear_task("test_session_5")
        ctx = self.sm.get("test_session_5")
        assert ctx.active_task_id is None
        assert ctx.state == "idle"
        assert ctx.has_active_task is False

    def test_end_session(self):
        self.sm.get_or_create("test_session_6")
        self.sm.end_session("test_session_6")
        assert self.sm.get("test_session_6") is None

    def test_list_sessions(self):
        self.sm.get_or_create("s1", channel="cli")
        self.sm.get_or_create("s2", channel="telegram")
        sessions = self.sm.list_sessions()
        assert len(sessions) == 2
        ids = {s["session_id"] for s in sessions}
        assert ids == {"s1", "s2"}

    def test_consume_tokens(self):
        self.sm.get_or_create("test_session_7")
        self.sm.consume_tokens("test_session_7", 500)
        self.sm.consume_tokens("test_session_7", 300)
        ctx = self.sm.get("test_session_7")
        assert ctx.tokens_used == 800

    def test_context_compression(self):
        self.sm.get_or_create("test_session_8")
        self.sm.add_turn("test_session_8", "user", "查詢台積電股價")
        self.sm.add_turn("test_session_8", "assistant", "✅ 台積電目前股價 680")
        self.sm.add_turn("test_session_8", "user", "幫我分析友達")

        summary = self.sm.compress_context("test_session_8")
        assert len(summary) > 0
        assert "查詢" in summary or "友達" in summary

    def test_session_budget(self):
        ctx = self.sm.get_or_create("test_session_9")
        assert ctx.is_over_budget() is False
        ctx.tokens_used = 100_001
        assert ctx.is_over_budget() is True

    def test_recent_history(self):
        ctx = self.sm.get_or_create("test_session_10")
        for i in range(30):
            ctx.add_turn("user", f"message {i}")
        recent = ctx.get_recent_history(5)
        assert len(recent) == 5
        assert recent[0]["content"] == "message 25"


# ──────────────────────────────────────────────────────────────────────────────
#  Message Router Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestMessageRouter:
    """Tests for gateway/router.py"""

    def setup_method(self):
        from gateway.router import MessageRouter
        self.router = MessageRouter()

    def test_system_command_routing(self):
        from gateway.router import InboundMessage, RouteAction
        msg = InboundMessage(channel="cli", user_id="u1", session_id="s1", text="/cancel")
        decision = self.router.route(msg, {})
        assert decision.action == RouteAction.SYSTEM_COMMAND
        assert decision.command == "/cancel"

    def test_continue_task_routing(self):
        from gateway.router import InboundMessage, RouteAction
        msg = InboundMessage(channel="cli", user_id="u1", session_id="s1", text="繼續")
        decision = self.router.route(msg, {"has_active_task": True, "agent_type": "main"})
        assert decision.action == RouteAction.CONTINUE_TASK

    def test_new_task_routing(self):
        from gateway.router import InboundMessage, RouteAction
        msg = InboundMessage(channel="cli", user_id="u1", session_id="s1", text="查詢天氣")
        decision = self.router.route(msg, {"has_active_task": False})
        assert decision.action == RouteAction.NEW_TASK

    def test_group_agent_selection(self):
        from gateway.router import InboundMessage
        msg = InboundMessage(
            channel="telegram", user_id="u1", session_id="s1",
            text="Hello", metadata={"chat_type": "group"}
        )
        decision = self.router.route(msg, {})
        assert decision.agent_type == "group"

    def test_default_agent_is_main(self):
        from gateway.router import InboundMessage
        msg = InboundMessage(channel="cli", user_id="u1", session_id="s1", text="Hello")
        decision = self.router.route(msg, {})
        assert decision.agent_type == "main"

    def test_all_system_commands(self):
        from gateway.router import InboundMessage, RouteAction
        commands = ["/cancel", "/status", "/help", "/reset", "/sessions",
                    "/health", "/skills", "/models", "/version"]
        for cmd in commands:
            msg = InboundMessage(channel="cli", user_id="u1", session_id="s1", text=cmd)
            decision = self.router.route(msg, {})
            assert decision.action == RouteAction.SYSTEM_COMMAND, f"Failed for {cmd}"
            assert decision.command == cmd

    def test_register_agent_handler(self):
        handler = lambda msg, ctx: "test"
        self.router.register_agent("custom", handler)
        assert self.router.get_handler("custom") is handler
        assert self.router.get_handler("nonexistent") is None


# ──────────────────────────────────────────────────────────────────────────────
#  InboundMessage Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestInboundMessage:
    """Tests for InboundMessage factory methods."""

    def test_from_cli(self):
        from gateway.router import InboundMessage
        msg = InboundMessage.from_cli("Hello world")
        assert msg.channel == "cli"
        assert msg.text == "Hello world"
        assert msg.session_id == "cli_cli"
        assert msg.timestamp != ""

    def test_from_api(self):
        from gateway.router import InboundMessage
        msg = InboundMessage.from_api("run task", user_id="admin", session_id="s1")
        assert msg.channel == "api"
        assert msg.text == "run task"
        assert msg.session_id == "s1"

    def test_from_websocket(self):
        from gateway.router import InboundMessage
        msg = InboundMessage.from_websocket({
            "user_id": "eason",
            "session_id": "ws_123",
            "text": "test message",
        })
        assert msg.channel == "websocket"
        assert msg.user_id == "eason"
        assert msg.text == "test message"

    def test_from_telegram(self):
        from gateway.router import InboundMessage
        update = {
            "message": {
                "text": "你好",
                "from": {"id": 12345, "username": "testuser", "first_name": "Test"},
                "message_id": 999,
            }
        }
        msg = InboundMessage.from_telegram(update, chat_id=12345)
        assert msg.channel == "telegram"
        assert msg.text == "你好"
        assert msg.user_id == "12345"
        assert msg.session_id == "tg_12345"
        assert msg.metadata["username"] == "testuser"

    def test_auto_session_id(self):
        from gateway.router import InboundMessage
        msg = InboundMessage(channel="test", user_id="u1", session_id="", text="hi")
        assert msg.session_id == "test_u1"


# ──────────────────────────────────────────────────────────────────────────────
#  DeliveryQueue Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestDeliveryQueue:
    """Tests for the async DeliveryQueue."""

    def test_put_and_get(self):
        from gateway.server import DeliveryQueue
        from gateway.router import OutboundMessage

        queue = DeliveryQueue()
        msg = OutboundMessage(session_id="s1", text="Hello")

        async def run():
            await queue.put(msg)
            result = await queue.get("s1", timeout=1.0)
            assert result is not None
            assert result.text == "Hello"
            assert result.session_id == "s1"

        asyncio.run(run())

    def test_get_timeout(self):
        from gateway.server import DeliveryQueue

        queue = DeliveryQueue()

        async def run():
            result = await queue.get("nonexistent", timeout=0.1)
            assert result is None

        asyncio.run(run())

    def test_callback_registration(self):
        from gateway.server import DeliveryQueue
        from gateway.router import OutboundMessage

        queue = DeliveryQueue()
        received = []

        async def callback(msg):
            received.append(msg)

        queue.register_callback("s1", callback)

        async def run():
            msg = OutboundMessage(session_id="s1", text="Callback test")
            await queue.put(msg)
            assert len(received) == 1
            assert received[0].text == "Callback test"

        asyncio.run(run())

    def test_cleanup(self):
        from gateway.server import DeliveryQueue

        queue = DeliveryQueue()
        queue.get_queue("s1")
        assert "s1" in queue._queues
        queue.cleanup("s1")
        assert "s1" not in queue._queues


# ──────────────────────────────────────────────────────────────────────────────
#  OutboundMessage Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestOutboundMessage:
    def test_construction(self):
        from gateway.router import OutboundMessage
        msg = OutboundMessage(session_id="s1", text="Response", channel="cli")
        assert msg.session_id == "s1"
        assert msg.text == "Response"
        assert msg.channel == "cli"
        assert msg.timestamp != ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
