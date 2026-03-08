# -*- coding: utf-8 -*-
"""
ArcMind Gateway — WebSocket Server
=====================================
OpenClaw 風格的 Gateway 控制面：
- WebSocket `/ws` 端點，管理長連線
- Message Delivery Queue，per-session 消息投遞
- REST endpoint `/v1/chat` 供非 WebSocket 客戶端使用
- Channel 消息接入點
- System command 處理

這是 ArcMind 的中樞：所有消息流經此處。

架構參照：
  Channel (Telegram/CLI/WS) → Gateway → Router → OODA Loop → Response → Channel
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from gateway.session_manager import session_manager, SessionContext
from gateway.router import (
    InboundMessage, OutboundMessage,
    message_router, RouteAction,
)

logger = logging.getLogger("arcmind.gateway.server")

router = APIRouter()


# ── Delivery Queue ──────────────────────────────────────────────────────────

class DeliveryQueue:
    """
    Per-session async message delivery queue.
    OpenClaw 風格：Gateway 統一管理所有 session 的響應投遞。
    """

    def __init__(self):
        self._queues: dict[str, asyncio.Queue] = {}
        self._callbacks: dict[str, list] = defaultdict(list)

    def get_queue(self, session_id: str) -> asyncio.Queue:
        if session_id not in self._queues:
            self._queues[session_id] = asyncio.Queue()
        return self._queues[session_id]

    async def put(self, msg: OutboundMessage) -> None:
        """Enqueue a response for delivery."""
        q = self.get_queue(msg.session_id)
        await q.put(msg)

        # Also notify registered callbacks (for Telegram, etc.)
        for cb in self._callbacks.get(msg.session_id, []):
            try:
                await cb(msg)
            except Exception as e:
                logger.warning("[DeliveryQueue] callback error for %s: %s",
                               msg.session_id, e)

    async def get(self, session_id: str, timeout: float = 30.0) -> OutboundMessage | None:
        """Wait for next response message."""
        q = self.get_queue(session_id)
        try:
            return await asyncio.wait_for(q.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    def register_callback(self, session_id: str, callback) -> None:
        """Register a callback for when responses arrive (for push channels)."""
        self._callbacks[session_id].append(callback)

    def unregister_callback(self, session_id: str, callback) -> None:
        """Remove a callback."""
        cbs = self._callbacks.get(session_id, [])
        if callback in cbs:
            cbs.remove(callback)

    def cleanup(self, session_id: str) -> None:
        """Clean up queue for ended session."""
        self._queues.pop(session_id, None)
        self._callbacks.pop(session_id, None)


delivery_queue = DeliveryQueue()


# ── Message Processing Pipeline ─────────────────────────────────────────────

async def process_message(msg: InboundMessage) -> OutboundMessage:
    """
    Core message processing pipeline.
    All messages from all channels flow through here.

    Pipeline:
    1. Get/create session
    2. Record user turn
    3. Route message
    4. Execute appropriate handler
    5. Record assistant turn
    6. Return response
    """
    t0 = time.monotonic()

    # 1. Get or create session
    ctx = session_manager.get_or_create(
        session_id=msg.session_id,
        channel=msg.channel,
        user_id=msg.user_id,
    )

    # 2. Record user turn
    session_manager.add_turn(msg.session_id, "user", msg.text)
    # Persist to MySQL episodic memory
    try:
        from memory.memory_store import memory_store
        memory_store.add_episodic(
            content=f"[用戶] {msg.text[:500]}",
            source=msg.channel or "telegram",
            session_id=msg.session_id,
        )
    except Exception:
        pass

    # 3. Route
    route = message_router.route(msg, {
        "has_active_task": ctx.has_active_task,
        "agent_type": ctx.agent_type,
        "state": ctx.state,
    })

    # 4. Execute
    response_text = ""

    if route.action == RouteAction.SYSTEM_COMMAND:
        response_text = await _handle_system_command(route.command, ctx)

    elif route.action in (RouteAction.NEW_TASK, RouteAction.CONTINUE_TASK):
        response_text = await _handle_agent_task(msg, ctx, route)

    else:
        response_text = "抱歉，我不確定如何處理這個請求。"

    elapsed = time.monotonic() - t0

    # 5. Record assistant turn
    session_manager.add_turn(msg.session_id, "assistant", response_text)
    # Persist to MySQL episodic memory
    try:
        from memory.memory_store import memory_store
        memory_store.add_episodic(
            content=f"[助理] {response_text[:500]}",
            source="agent",
            session_id=msg.session_id,
        )
    except Exception:
        pass

    logger.info("[Gateway] %s → %s (%.2fs, route=%s, agent=%s)",
                msg.session_id, msg.text[:40], elapsed,
                route.action.value, route.agent_type)

    # 6. Build response
    response = OutboundMessage(
        session_id=msg.session_id,
        text=response_text,
        channel=msg.channel,
        metadata={"elapsed_s": round(elapsed, 3)},
    )

    # Enqueue for delivery
    await delivery_queue.put(response)

    return response


# ── System Command Handler ──────────────────────────────────────────────────

async def _handle_system_command(command: str, ctx: SessionContext) -> str:
    """Handle system commands that bypass the OODA loop."""
    if command == "/cancel":
        if ctx.has_active_task:
            session_manager.clear_task(ctx.session_id)
            return "✅ 已取消當前任務。"
        return "目前沒有進行中的任務。"

    elif command == "/status":
        return (
            f"📊 Session: `{ctx.session_id}`\n"
            f"狀態: {ctx.state}\n"
            f"Agent: {ctx.agent_type}\n"
            f"對話輪次: {ctx.turn_count}\n"
            f"Token 使用: {ctx.tokens_used}\n"
            f"活動任務: {ctx.active_task_id or '無'}"
        )

    elif command == "/sessions":
        sessions = session_manager.list_sessions()
        if not sessions:
            return "目前沒有活動的 Session。"
        lines = ["📋 活動 Sessions:"]
        for s in sessions:
            lines.append(
                f"  • `{s['session_id']}` [{s['channel']}] "
                f"turns={s['turn_count']} state={s['state']}"
            )
        return "\n".join(lines)

    elif command == "/reset":
        session_manager.end_session(ctx.session_id)
        return "🔄 Session 已重置。"

    elif command == "/help":
        return (
            "🧠 **ArcMind 指令**\n\n"
            "⚡ *模型 / 輸出*\n"
            "• `/model` — 切換 AI 模型（按鈕選擇）\n"
            "• `/mode` — 切換輸出模式（簡潔/詳細/程式碼）\n"
            "• `/models` — 列出可用模型 Provider\n\n"
            "📋 *Session 管理*\n"
            "• `/status` — 查看當前 Session 狀態\n"
            "• `/sessions` — 列出所有活動 Sessions\n"
            "• `/cancel` — 取消當前任務\n"
            "• `/reset` — 重置 Session\n\n"
            "🧩 *技能管理*\n"
            "• `/skills` — 列出已安裝技能\n"
            "• `/install <github_url>` — 從 GitHub 安裝技能\n"
            "• `/remove_skill <name>` — 移除已安裝技能\n\n"
            "🔧 *系統*\n"
            "• `/health` — 系統健康檢查\n"
            "• `/version` — 版本資訊"
        )

    elif command == "/skills" or command.startswith("/skills"):
        try:
            from runtime.skill_installer import skill_installer
            skills = skill_installer.list_installed()
            if not skills:
                return "目前沒有已載入的技能。"
            lines = ["🧩 已安裝技能:"]
            for s in skills:
                source = "🏠" if s["source"] == "built-in" else "📦"
                removable = " *(可移除)*" if s.get("removable") else ""
                lines.append(f"  {source} **{s['name']}** v{s.get('version', '?')}{removable}")
            lines.append("\n💡 `/install <github_url>` 安裝新技能")
            return "\n".join(lines)
        except Exception as e:
            return f"⚠️ 無法載入技能列表: {e}"

    elif command == "/models":
        try:
            from runtime.model_router import model_router
            providers = model_router.list_providers()
            if not providers:
                return "目前沒有可用的 AI Provider。"
            lines = ["🤖 可用 AI Providers:"]
            for p in providers:
                lines.append(f"  • **{p['provider']}** — {p.get('status', 'ready')}")
            return "\n".join(lines)
        except Exception as e:
            return f"⚠️ 無法載入模型列表: {e}"

    elif command == "/health":
        return (
            f"💚 ArcMind Gateway 運行中\n"
            f"Sessions: {session_manager.active_count()}\n"
            f"Version: 0.3.0"
        )

    elif command == "/version":
        return "ArcMind v0.3.0 (Gateway Architecture)"

    elif command.startswith("/install "):
        url = command[len("/install "):].strip()
        if not url:
            return "用法: `/install <github_url>`\n例: `/install owner/repo`"
        try:
            from runtime.skill_installer import skill_installer
            result = skill_installer.install(url)
            if result["success"]:
                perms = ", ".join(result.get("permissions", [])) or "無"
                return (
                    f"✅ **{result['name']}** 安裝成功\n\n"
                    f"版本: {result.get('version', '?')}\n"
                    f"說明: {result.get('description', '-')}\n"
                    f"權限: {perms}\n\n"
                    f"已自動載入，可直接使用。"
                )
            else:
                return f"❌ 安裝失敗\n{result['message']}"
        except Exception as e:
            return f"❌ 安裝錯誤: {e}"

    elif command.startswith("/remove_skill "):
        name = command[len("/remove_skill "):].strip()
        if not name:
            return "用法: `/remove_skill <name>`"
        try:
            from runtime.skill_installer import skill_installer
            result = skill_installer.remove(name)
            return result["message"]
        except Exception as e:
            return f"❌ 移除錯誤: {e}"

    return f"未知指令: {command}"


# ── Agent Task Handler ──────────────────────────────────────────────────────

async def _handle_agent_task(
    msg: InboundMessage,
    ctx: SessionContext,
    route,
) -> str:
    """
    Handle an agent task via the OODA loop.
    Routes through the registered handler or falls back to direct loop call.
    """
    try:
        # Try registered handler first
        handler = message_router.get_handler(route.agent_type)
        if handler:
            if asyncio.iscoroutinefunction(handler):
                return await handler(msg, ctx)
            else:
                return handler(msg, ctx)

        # Fallback: direct OODA loop call
        from loop.main_loop import main_loop, LoopInput

        # Build session context with conversation history for continuity
        session_context = {
            "session_id": ctx.session_id,
            "agent_type": ctx.agent_type,
            "state": ctx.state,
            "channel": ctx.channel,
        }

        # Include recent conversation history so LLM has context
        recent_turns = ctx.get_recent_history(20)
        if recent_turns:
            session_context["conversation_history"] = [
                {"role": t["role"], "content": t["content"]}
                for t in recent_turns
            ]

        # ── Per-session model/mode override (from Telegram /model /mode) ──
        model_override = msg.metadata.get("model_override", "")
        output_mode = msg.metadata.get("output_mode", "")
        if model_override:
            session_context["model_override"] = model_override
        if output_mode:
            session_context["output_mode"] = output_mode

        loop_input = LoopInput(
            command=msg.text,
            source=msg.channel,
            session_id=None,  # DB task ID, not session
            task_type="general",
            context=session_context,
            model_hint=model_override or None,
        )

        result = await asyncio.to_thread(main_loop.run, loop_input)

        # Record token usage
        if result.tokens_used:
            session_manager.consume_tokens(ctx.session_id, result.tokens_used)

        if result.success:
            return str(result.output) if result.output else "✅ 完成。"
        else:
            return f"❌ 執行失敗: {result.error or '未知錯誤'}"

    except Exception as e:
        logger.exception("[Gateway] agent task error: %s", e)
        return f"⚠️ 處理過程發生錯誤: {e}"


# ── WebSocket Endpoint ──────────────────────────────────────────────────────

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time bidirectional communication.
    OpenClaw 風格的長連線。
    """
    await websocket.accept()
    session_id = None

    try:
        # Wait for initial handshake
        init_data = await asyncio.wait_for(websocket.receive_json(), timeout=10)
        session_id = init_data.get("session_id", f"ws_{id(websocket)}")
        user_id = init_data.get("user_id", "ws_user")

        logger.info("[Gateway/WS] connected: session=%s, user=%s", session_id, user_id)

        # Send welcome
        await websocket.send_json({
            "type": "connected",
            "session_id": session_id,
            "message": "ArcMind Gateway 已連線",
        })

        # Register delivery callback for push responses
        async def ws_delivery_callback(out_msg: OutboundMessage):
            try:
                await websocket.send_json({
                    "type": "response",
                    "session_id": out_msg.session_id,
                    "text": out_msg.text,
                    "metadata": out_msg.metadata,
                    "timestamp": out_msg.timestamp,
                })
            except Exception:
                pass

        delivery_queue.register_callback(session_id, ws_delivery_callback)

        # Message loop
        while True:
            data = await websocket.receive_json()
            text = data.get("text", "")

            if not text.strip():
                continue

            msg = InboundMessage.from_websocket({
                "session_id": session_id,
                "user_id": user_id,
                "text": text,
                **data,
            })

            # Process in background to avoid blocking the WS loop
            asyncio.create_task(_ws_process_and_respond(websocket, msg))

    except WebSocketDisconnect:
        logger.info("[Gateway/WS] disconnected: session=%s", session_id)
    except asyncio.TimeoutError:
        logger.warning("[Gateway/WS] handshake timeout, closing")
        await websocket.close(code=4001, reason="Handshake timeout")
    except Exception as e:
        logger.exception("[Gateway/WS] error: %s", e)
    finally:
        if session_id:
            delivery_queue.cleanup(session_id)


async def _ws_process_and_respond(websocket: WebSocket, msg: InboundMessage):
    """Process a WS message and send the response back."""
    try:
        response = await process_message(msg)
        # Response is already pushed via delivery callback
    except Exception as e:
        try:
            await websocket.send_json({
                "type": "error",
                "error": str(e),
            })
        except Exception:
            pass


# ── REST Chat Endpoint ──────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    text: str
    session_id: str = ""
    user_id: str = "api"
    channel: str = "api"


class ChatResponse(BaseModel):
    text: str
    session_id: str
    elapsed_s: float = 0.0


@router.post("/v1/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest):
    """
    REST chat endpoint for non-WebSocket clients.
    Same pipeline as WebSocket, just request/response style.
    """
    msg = InboundMessage.from_api(
        command=req.text,
        user_id=req.user_id,
        session_id=req.session_id,
    )

    response = await process_message(msg)

    return ChatResponse(
        text=response.text,
        session_id=response.session_id,
        elapsed_s=response.metadata.get("elapsed_s", 0.0),
    )


# ── Gateway Status ──────────────────────────────────────────────────────────

@router.get("/v1/gateway/status")
def gateway_status():
    return {
        "status": "running",
        "version": "0.3.0",
        "architecture": "OpenClaw-style Gateway",
        "sessions": session_manager.summary(),
    }
