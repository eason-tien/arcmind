# -*- coding: utf-8 -*-
"""
ArcMind — Event-Driven Hybrid Bus
====================================
統一事件匯流排，驅動 OODA Loop 與所有子系統。

混合驅動模式：
  1. 同步路徑 (Request-Response): API/WebSocket → MainLoop.run()
  2. 異步路徑 (Event-Driven): EventBus → Handler → MainLoop

事件來源 (Event Sources):
  - user_message     : 用戶消息（Telegram / API / WebSocket）
  - cron_trigger     : Cron 排程觸發
  - agent_complete   : Sub-Agent 完成任務
  - agent_escalate   : Sub-Agent 升級任務
  - system_event     : 系統事件（啟動、健康檢查、錯誤）
  - webhook          : 外部 Webhook 回調
  - iamp_message     : IAMP Agent 間通訊轉發

用法：
  from runtime.event_bus import event_bus, Event, EventType

  # 發佈事件
  event_bus.emit(Event(
      type=EventType.CRON_TRIGGER,
      source="cron:daily-report",
      payload={"skill": "daily_report", "input": {}},
  ))

  # 訂閱事件
  @event_bus.on(EventType.AGENT_COMPLETE)
  async def handle_agent_done(event: Event):
      print(f"Agent finished: {event.payload}")
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable, Optional

logger = logging.getLogger("arcmind.event_bus")


# ── Event Types ──────────────────────────────────────────────────────────────

class EventType(str, Enum):
    """All event types in ArcMind."""
    USER_MESSAGE = "user_message"
    CRON_TRIGGER = "cron_trigger"
    AGENT_COMPLETE = "agent_complete"
    AGENT_ESCALATE = "agent_escalate"
    SYSTEM_EVENT = "system_event"
    WEBHOOK = "webhook"
    IAMP_MESSAGE = "iamp_message"
    TASK_CREATED = "task_created"
    TASK_FAILED = "task_failed"


class EventPriority(int, Enum):
    """Event processing priority (lower = higher priority)."""
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3
    BACKGROUND = 4


# ── Event ────────────────────────────────────────────────────────────────────

@dataclass
class Event:
    """A single event in the ArcMind system."""
    type: EventType
    source: str                                # e.g. "cron:daily-report", "user:tg_12345"
    payload: dict[str, Any] = field(default_factory=dict)
    priority: EventPriority = EventPriority.NORMAL
    id: str = ""
    timestamp: float = 0.0
    correlation_id: str = ""                   # Link related events (e.g. task chain)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:12]
        if not self.timestamp:
            self.timestamp = time.time()


# ── Handler type ─────────────────────────────────────────────────────────────

EventHandler = Callable[[Event], Awaitable[None]]


# ── EventBus ─────────────────────────────────────────────────────────────────

class EventBus:
    """
    Central event bus for ArcMind.

    Features:
    - Typed event subscription (per EventType or wildcard)
    - Priority queue processing
    - Async handler execution
    - Dead letter queue for failed events
    - Metrics tracking
    """

    def __init__(self, max_queue_size: int = 5000):
        self._handlers: dict[EventType, list[EventHandler]] = defaultdict(list)
        self._wildcard_handlers: list[EventHandler] = []
        self._queue: asyncio.PriorityQueue | None = None
        self._max_queue_size = max_queue_size
        self._running = False
        self._worker_task: asyncio.Task | None = None
        self._dead_letters: list[Event] = []
        self._max_dead_letters = 100

        # Metrics
        self._emitted = 0
        self._processed = 0
        self._failed = 0

    # ── Subscription ─────────────────────────────────────────────────────────

    def on(self, event_type: EventType | None = None):
        """
        Decorator to subscribe a handler to an event type.
        If event_type is None, subscribes to ALL events (wildcard).

        Usage:
            @event_bus.on(EventType.CRON_TRIGGER)
            async def handle_cron(event: Event):
                ...
        """
        def decorator(fn: EventHandler) -> EventHandler:
            if event_type is None:
                self._wildcard_handlers.append(fn)
            else:
                self._handlers[event_type].append(fn)
            logger.info("[EventBus] subscribed: %s → %s",
                        event_type or "*", fn.__name__)
            return fn
        return decorator

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Imperative subscription (non-decorator)."""
        self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Remove a handler."""
        handlers = self._handlers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)

    # ── Emit ─────────────────────────────────────────────────────────────────

    def emit(self, event: Event) -> None:
        """
        Emit an event into the bus.
        If the bus is running (async worker active), queues for async processing.
        Otherwise, processes synchronously via fire-and-forget.
        """
        self._emitted += 1
        logger.info("[EventBus] emit: type=%s source=%s id=%s pri=%s",
                    event.type.value, event.source, event.id, event.priority.name)

        if self._running and self._queue is not None:
            try:
                self._queue.put_nowait((event.priority.value, event.timestamp, event))
            except asyncio.QueueFull:
                logger.warning("[EventBus] Queue full, dropping event %s", event.id)
                self._dead_letters.append(event)
                self._trim_dead_letters()
        else:
            # Synchronous fallback: try to schedule in running loop
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._dispatch(event))
            except RuntimeError:
                # No event loop — skip async dispatch
                logger.debug("[EventBus] No event loop, event %s queued for later", event.id)

    async def emit_async(self, event: Event) -> None:
        """Async emit — directly dispatches."""
        self._emitted += 1
        logger.info("[EventBus] emit_async: type=%s source=%s id=%s",
                    event.type.value, event.source, event.id)
        await self._dispatch(event)

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the async event processing worker."""
        if self._running:
            return
        self._queue = asyncio.PriorityQueue(maxsize=self._max_queue_size)
        self._running = True
        self._worker_task = asyncio.create_task(self._worker(), name="event_bus_worker")
        logger.info("[EventBus] started (queue_size=%d)", self._max_queue_size)

    async def stop(self) -> None:
        """Gracefully stop the event bus."""
        if not self._running:
            return
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info("[EventBus] stopped (emitted=%d processed=%d failed=%d)",
                    self._emitted, self._processed, self._failed)

    # ── Worker ───────────────────────────────────────────────────────────────

    async def _worker(self) -> None:
        """Background worker that processes events from the priority queue."""
        logger.info("[EventBus] worker started")
        while self._running:
            try:
                priority, ts, event = await asyncio.wait_for(
                    self._queue.get(), timeout=1.0
                )
                await self._dispatch(event)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[EventBus] worker error: %s", e)

    async def _dispatch(self, event: Event) -> None:
        """Dispatch event to all matching handlers."""
        handlers = list(self._handlers.get(event.type, []))
        handlers.extend(self._wildcard_handlers)

        if not handlers:
            logger.debug("[EventBus] no handlers for %s", event.type.value)
            return

        for handler in handlers:
            try:
                await handler(event)
                self._processed += 1
            except Exception as e:
                self._failed += 1
                logger.error("[EventBus] handler %s failed for event %s: %s",
                             handler.__name__, event.id, e)
                self._dead_letters.append(event)
                self._trim_dead_letters()

    def _trim_dead_letters(self) -> None:
        while len(self._dead_letters) > self._max_dead_letters:
            self._dead_letters.pop(0)

    # ── Stats ────────────────────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        """Return event bus metrics."""
        return {
            "running": self._running,
            "emitted": self._emitted,
            "processed": self._processed,
            "failed": self._failed,
            "dead_letters": len(self._dead_letters),
            "handlers": {
                et.value: len(hs) for et, hs in self._handlers.items() if hs
            },
            "wildcard_handlers": len(self._wildcard_handlers),
            "queue_size": self._queue.qsize() if self._queue else 0,
        }


# ── Global Singleton ─────────────────────────────────────────────────────────
event_bus = EventBus()
