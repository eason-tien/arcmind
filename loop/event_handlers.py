# -*- coding: utf-8 -*-
"""
ArcMind — Event Handlers
=================================
Background workers that listen to EventBus and trigger the MainLoop asynchronously.
Transforms ArcMind into a Hybrid Event-Driven Engine.
"""
import asyncio
import logging
from typing import Any

from runtime.event_bus import event_bus, Event, EventType
from gateway.router import InboundMessage
from gateway.session_manager import session_manager
from loop.main_loop import main_loop, LoopInput

logger = logging.getLogger("arcmind.event_handlers")


@event_bus.on(EventType.USER_MESSAGE)
async def handle_user_message(event: Event):
    """
    Handle inbound messages asynchronously.
    The payload is expected to contain the actual message dict and context.
    """
    payload = event.payload
    msg_data = payload.get("message")
    session_context = payload.get("session_context", {})

    if not msg_data:
        logger.error("[EventHandler] USER_MESSAGE event missing 'message' payload")
        return

    # Reconstruct InboundMessage wrapper for standardized handling
    from gateway.router import InboundMessage
    msg = InboundMessage(**msg_data)

    loop_input = LoopInput(
        command=msg.text,
        source=msg.channel,
        session_id=session_context.get("session_id") or msg.session_id,
        task_type="general",
        context=session_context,
        model_hint=msg.metadata.get("model_override") or None,
    )

    try:
        # Run OODA loop in background thread to avoid blocking EventBus worker
        result = await asyncio.wait_for(
            asyncio.to_thread(main_loop.run, loop_input),
            timeout=300,  # 5 min timeout per turn
        )

        from gateway.server import delivery_queue
        from gateway.router import OutboundMessage

        # Record tokens
        if result.tokens_used:
            session_manager.consume_tokens(msg.session_id, result.tokens_used)

        text_out = str(result.output) if result.success else f"❌ 執行失敗: {result.error or 'Unknown error'}"

        out_msg = OutboundMessage(
            session_id=msg.session_id,
            text=text_out,
            channel=msg.channel,
            metadata={"elapsed_s": result.elapsed_s}
        )

        # Asynchronously deliver the output back to the connected client (WebSocket/Telegram)
        await delivery_queue.put(out_msg)

    except (asyncio.TimeoutError, TimeoutError):
        logger.error("[EventHandler] USER_MESSAGE timed out (300s): %s", msg.text[:80])
        from gateway.server import delivery_queue
        from gateway.router import OutboundMessage
        error_msg = OutboundMessage(
            session_id=msg.session_id,
            text=f"❌ 系統錯誤: 請求處理超時（5分鐘），請簡化指令或稍後重試。\n原始指令: {msg.text[:100]}",
            channel=msg.channel,
        )
        await delivery_queue.put(error_msg)

    except asyncio.CancelledError:
        # CancelledError is BaseException in Python 3.9+ — str() returns ""
        logger.error("[EventHandler] USER_MESSAGE cancelled: %s", msg.text[:80])
        from gateway.server import delivery_queue
        from gateway.router import OutboundMessage
        error_msg = OutboundMessage(
            session_id=msg.session_id,
            text=f"❌ 系統錯誤: 請求被取消，請稍後重試。\n原始指令: {msg.text[:100]}",
            channel=msg.channel,
        )
        await delivery_queue.put(error_msg)

    except BaseException as e:
        # Catch ALL exceptions including BaseException subclasses
        error_text = str(e) or type(e).__name__ or "未知錯誤"
        logger.exception("[EventHandler] Error processing USER_MESSAGE: %s", error_text)
        from gateway.server import delivery_queue
        from gateway.router import OutboundMessage
        error_msg = OutboundMessage(
            session_id=msg.session_id,
            text=f"❌ 系統錯誤: {error_text}",
            channel=msg.channel,
        )
        await delivery_queue.put(error_msg)


@event_bus.on(EventType.TASK_CREATED)
async def handle_task_created(event: Event):
    """
    Instantly wakes up a sub-agent when a task is delegated.
    Replaces the brittle polling of worker_heartbeat.py.
    """
    payload = event.payload
    task_id = payload.get("task_id")
    assigned_to = payload.get("assigned_to")
    description = payload.get("description")

    if not task_id or not assigned_to:
        # Not a delegated task — no sub-agent to wake up. Silent skip.
        return

    logger.info("[EventHandler] Waking up %s for task %s", assigned_to, task_id)

    loop_input = LoopInput(
        command=description or f"Proceed with delegated task {task_id}",
        source="system",
        session_id=task_id, # Link directly to the sub-task
        task_type="delegated",
        context={
            "sub_agent_role": assigned_to,
            "parent_task_id": payload.get("parent_task_id"),
        }
    )

    try:
        # Run OODA loop in background thread
        result = await asyncio.wait_for(
            asyncio.to_thread(main_loop.run, loop_input),
            timeout=600,  # Delegated tasks might take longer
        )

        # Mark task resolved in DB
        from runtime.lifecycle import lifecycle
        if result.success:
            lifecycle.tasks.close(task_id, result.output)
            # Notify gateway that sub-agent completed its chunk
            from gateway.server import broadcast_activity, ActivityPayload
            await broadcast_activity(ActivityPayload(
                agent=assigned_to,
                action="Task Finished",
                details=f"Task {task_id} done",
                status="success"
            ))
        else:
            lifecycle.tasks.fail(task_id, result.error)

    except Exception as e:
        logger.exception("[EventHandler] Sub-agent crash on TASK_CREATED: %s", e)
        from runtime.lifecycle import lifecycle
        lifecycle.tasks.fail(task_id, str(e))


@event_bus.on(EventType.FEDERATION_RESULT)
async def handle_federation_result(event: Event):
    """
    遠端 ArcMind peer 完成委派任務後的結果回調處理。
    將結果投遞到 delivery_queue → 回傳給原始用戶。
    """
    payload = event.payload
    task_id = payload.get("task_id", "")
    session_id = payload.get("session_id", "")
    channel = payload.get("channel", "")
    responder = payload.get("responder", "unknown")
    result = payload.get("result", {})

    success = result.get("success", False)
    output = result.get("output", "")
    error = result.get("error", "")
    elapsed = result.get("elapsed_s", 0)
    agent_id = result.get("agent_id", "unknown")

    logger.info("[EventHandler] Federation result: task=%s from=%s agent=%s success=%s elapsed=%.1fs",
                task_id, responder, agent_id, success, elapsed)

    if not session_id and not channel:
        logger.warning("[EventHandler] Federation result has no session_id or channel, cannot deliver")
        return

    from gateway.server import delivery_queue
    from gateway.router import OutboundMessage

    if success:
        text = f"🔗 [{responder}] {output}"
    else:
        text = f"🔗 [{responder}] ❌ 遠端執行失敗: {error or 'Unknown error'}"

    out_msg = OutboundMessage(
        session_id=session_id,
        text=text,
        channel=channel,
        metadata={
            "federation": True,
            "responder": responder,
            "agent_id": agent_id,
            "elapsed_s": elapsed,
            "task_id": task_id,
        },
    )
    await delivery_queue.put(out_msg)
