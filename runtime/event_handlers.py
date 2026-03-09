# -*- coding: utf-8 -*-
"""
ArcMind — Event Handlers
==========================
Event-Driven 混合驅動的核心接線層。
將 EventBus 事件路由到 OODA Loop 或直接處理。

Handler 職責：
  - cron_trigger    → 呼叫 MainLoop（source=cron）
  - agent_complete  → 更新 Lifecycle + 通知 CEO
  - agent_escalate  → 升級到 CEO 處理
  - system_event    → 記錄 + 告警
  - iamp_message    → 轉發到目標 Agent inbox
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from runtime.event_bus import event_bus, Event, EventType

logger = logging.getLogger("arcmind.event_handlers")


# ── Cron Trigger Handler ─────────────────────────────────────────────────────

@event_bus.on(EventType.CRON_TRIGGER)
async def handle_cron_trigger(event: Event) -> None:
    """
    Cron 排程觸發 → 走 OODA Loop。
    payload 預期：
      - skill_name: str
      - input_data: dict
      - governor_required: bool
      - cron_name: str
    """
    payload = event.payload
    skill_name = payload.get("skill_name", "")
    cron_name = payload.get("cron_name", event.source)
    input_data = payload.get("input_data", {})
    governor_required = payload.get("governor_required", True)

    logger.info("[Handler:cron] trigger: cron=%s skill=%s", cron_name, skill_name)

    # Governor 審計
    if governor_required:
        try:
            from foundation.mgis_client import mgis
            audit = mgis.audit(
                action=f"cron_execute:{skill_name}",
                context={"cron_name": cron_name, "input_data": input_data},
            )
            if not audit.get("approved", False):
                logger.warning("[Handler:cron] %s blocked by Governor: %s",
                               cron_name, audit.get("reason"))
                return
        except Exception as e:
            logger.warning("[Handler:cron] Governor check failed (proceeding): %s", e)

    # 走 OODA Loop (run in thread to avoid blocking asyncio event loop)
    try:
        from loop.main_loop import main_loop, LoopInput
        inp = LoopInput(
            command=f"[CRON:{cron_name}] Execute skill: {skill_name}",
            source="cron",
            skill_hint=skill_name,
            context={"cron_name": cron_name, **input_data},
        )
        result = await asyncio.to_thread(main_loop.run, inp)
        logger.info("[Handler:cron] %s done: success=%s elapsed=%.2fs",
                    cron_name, result.success, result.elapsed_s)
        # Update cron run record AFTER actual execution
        try:
            from runtime.cron import cron_system
            cron_system._update_run(cron_name, success=result.success)
        except Exception:
            pass
    except Exception as e:
        logger.error("[Handler:cron] %s failed: %s", cron_name, e)
        try:
            from runtime.cron import cron_system
            cron_system._update_run(cron_name, success=False)
        except Exception:
            pass


# ── Agent Complete Handler ───────────────────────────────────────────────────

@event_bus.on(EventType.AGENT_COMPLETE)
async def handle_agent_complete(event: Event) -> None:
    """
    Sub-Agent 完成任務 → 更新 Lifecycle (if not already closed).

    NOTE: Does NOT send IAMP messages to avoid infinite loop:
      handler → IAMP.send → bridge → EventBus → handler → ...
    The IAMP message that triggered this event already serves as CEO notification.

    payload 預期：
      - task_id: int
      - agent_id: str
      - output: Any
      - tokens: int
      - success: bool (from MainLoop emit — task already closed, skip)
    """
    payload = event.payload
    task_id = payload.get("task_id")
    agent_id = payload.get("agent_id", "unknown")

    # Skip if emitted by MainLoop itself (task already closed in LEARN phase)
    if payload.get("success") is not None and event.source not in ("iamp:",):
        logger.debug("[Handler:agent_complete] from MainLoop (already closed), skipping. task=%s", task_id)
        return

    logger.info("[Handler:agent_complete] agent=%s task=%s", agent_id, task_id)

    # Update lifecycle — only if task is still open
    try:
        from runtime.lifecycle import lifecycle
        if task_id:
            task = lifecycle.tasks.get(task_id)
            if task and task["status"] not in ("closed", "failed"):
                lifecycle.tasks.close(
                    task_id,
                    output_data={"output": str(payload.get("output", ""))[:500]},
                    tokens_used=payload.get("tokens", 0),
                )
    except Exception as e:
        logger.warning("[Handler:agent_complete] lifecycle update failed: %s", e)


# ── Agent Escalate Handler ───────────────────────────────────────────────────

@event_bus.on(EventType.AGENT_ESCALATE)
async def handle_agent_escalate(event: Event) -> None:
    """
    Sub-Agent 升級任務 → CEO 接手。
    payload 預期：
      - task_id: int
      - agent_id: str
      - reason: str
      - original_command: str
    """
    payload = event.payload
    task_id = payload.get("task_id")
    agent_id = payload.get("agent_id", "unknown")
    reason = payload.get("reason", "Escalated by sub-agent")

    logger.warning("[Handler:escalate] agent=%s task=%s reason=%s",
                   agent_id, task_id, reason)

    # IAMP escalation message
    try:
        from runtime.iamp import message_bus, MessageType
        message_bus.send(
            sender=agent_id,
            receiver="main",
            msg_type=MessageType.TASK_ESCALATE,
            payload={
                "reason": reason,
                "original_command": payload.get("original_command", ""),
            },
            task_id=str(task_id) if task_id else None,
        )
    except Exception as e:
        logger.warning("[Handler:escalate] IAMP notify failed: %s", e)

    # Re-run via MainLoop as CEO (in thread to avoid blocking event loop)
    original_cmd = payload.get("original_command")
    if original_cmd:
        try:
            from loop.main_loop import main_loop, LoopInput
            inp = LoopInput(
                command=f"[ESCALATED from {agent_id}] {original_cmd}",
                source="escalation",
                context={"escalated_from": agent_id, "reason": reason},
            )
            result = await asyncio.to_thread(main_loop.run, inp)
            logger.info("[Handler:escalate] CEO handled: success=%s", result.success)
        except Exception as e:
            logger.error("[Handler:escalate] CEO handling failed: %s", e)


# ── System Event Handler ─────────────────────────────────────────────────────

@event_bus.on(EventType.SYSTEM_EVENT)
async def handle_system_event(event: Event) -> None:
    """
    系統事件 → 記錄 + 必要時告警。
    payload 預期：
      - action: str (startup | shutdown | health_check | error | warning)
      - detail: str
    """
    action = event.payload.get("action", "unknown")
    detail = event.payload.get("detail", "")

    if action == "error":
        logger.error("[Handler:system] ERROR: %s", detail)
        # Write to causal memory for learning
        try:
            from memory.memory_store import memory_store
            memory_store.add_causal(
                cause=f"System event: {event.source}",
                effect=detail[:300],
                confidence=0.8,
            )
        except Exception:
            pass
    else:
        logger.info("[Handler:system] %s: %s", action, detail[:200])


# ── IAMP Message Bridge Handler ──────────────────────────────────────────────

@event_bus.on(EventType.IAMP_MESSAGE)
async def handle_iamp_bridge(event: Event) -> None:
    """
    IAMP 消息轉發到 EventBus 後的處理。
    主要用於：Agent 完成/升級 → 觸發後續事件鏈。
    """
    payload = event.payload
    msg_type = payload.get("msg_type", "")

    if msg_type == "task_complete":
        # Chain: IAMP task_complete → EventBus AGENT_COMPLETE
        event_bus.emit(Event(
            type=EventType.AGENT_COMPLETE,
            source=event.source,
            payload=payload,
            correlation_id=event.correlation_id,
        ))
    elif msg_type == "task_escalate":
        event_bus.emit(Event(
            type=EventType.AGENT_ESCALATE,
            source=event.source,
            payload=payload,
            correlation_id=event.correlation_id,
        ))


# ── Webhook Handler ──────────────────────────────────────────────────────────

@event_bus.on(EventType.WEBHOOK)
async def handle_webhook(event: Event) -> None:
    """
    外部 Webhook 回調 → 走 OODA Loop 處理。
    payload 預期：
      - source: str (webhook source identifier)
      - data: dict (original webhook payload)
      - headers: dict (X-* headers)
    """
    payload = event.payload
    source = payload.get("source", "external")
    data = payload.get("data", {})

    logger.info("[Handler:webhook] source=%s", source)

    # Extract skill hint from payload if present
    skill_hint = None
    if isinstance(data, dict):
        skill_hint = data.get("skill") or data.get("skill_name")

    # Build command from webhook data
    command_parts = [f"[WEBHOOK:{source}]"]
    if isinstance(data, dict):
        action = data.get("action") or data.get("type") or data.get("event")
        if action:
            command_parts.append(f"Action: {action}")
        message = data.get("message") or data.get("text") or data.get("command")
        if message:
            command_parts.append(str(message)[:500])
        else:
            command_parts.append(f"Process webhook data: {str(data)[:300]}")
    else:
        command_parts.append(f"Process webhook: {str(data)[:300]}")

    # Governor audit
    try:
        from foundation.mgis_client import mgis
        audit = mgis.audit(
            action=f"webhook_process:{source}",
            context={"source": source, "data_keys": list(data.keys()) if isinstance(data, dict) else []},
        )
        if not audit.get("approved", False):
            logger.warning("[Handler:webhook] %s blocked by Governor: %s",
                           source, audit.get("reason"))
            return
    except Exception as e:
        logger.warning("[Handler:webhook] Governor check failed (proceeding): %s", e)

    # Run via OODA Loop
    try:
        from loop.main_loop import main_loop, LoopInput
        inp = LoopInput(
            command=" ".join(command_parts),
            source="webhook",
            skill_hint=skill_hint,
            context={"webhook_source": source, "webhook_data": data},
        )
        result = await asyncio.to_thread(main_loop.run, inp)
        logger.info("[Handler:webhook] %s done: success=%s elapsed=%.2fs",
                    source, result.success, result.elapsed_s)
    except Exception as e:
        logger.error("[Handler:webhook] %s failed: %s", source, e)


# ── Task Created Handler (for metrics/logging) ──────────────────────────────

@event_bus.on(EventType.TASK_CREATED)
async def handle_task_created(event: Event) -> None:
    """Log task creation for observability."""
    logger.info("[Handler:task_created] task=%s source=%s",
                event.payload.get("task_id"), event.source)


# ── Registration helper ──────────────────────────────────────────────────────

def register_all_handlers() -> None:
    """
    Explicitly ensure all handlers are registered.
    Called during app startup. The @event_bus.on decorators above
    register handlers at module import time, so this function
    just needs to trigger the import.
    """
    logger.info("[EventHandlers] All event handlers registered. Stats: %s",
                event_bus.stats())
