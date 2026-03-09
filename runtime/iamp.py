# -*- coding: utf-8 -*-
"""
ArcMind — Inter-Agent Message Protocol (IAMP)
===============================================
零人類公司 Agent 間結構化通訊協議。

Message Types:
  - task_assign    : CEO 分派任務給 sub-agent
  - task_complete  : sub-agent 回報任務完成
  - task_escalate  : sub-agent 升級任務（超出能力範圍）
  - info_request   : Agent 向另一 Agent 請求資訊
  - info_response  : 回應資訊請求
  - status_report  : Agent 回報狀態
  - handoff        : Agent 將任務交接給下一個 Agent

Shared Working Memory:
  - 每個任務有一個共享 context，所有參與 Agent 可讀寫
  - 支援鎖定以防止併發寫入衝突

用法：
  from runtime.iamp import message_bus, SharedMemory

  # CEO 發送任務
  msg = message_bus.send(
      sender="main",
      receiver="code",
      msg_type="task_assign",
      payload={"task": "寫一個排序演算法", "priority": "high"}
  )

  # 共享工作記憶
  mem = SharedMemory(task_id="t-123")
  mem.write("main", "research_result", {"findings": "React 是前端框架..."})
  data = mem.read("research_result")
"""
from __future__ import annotations

import logging
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from threading import Lock
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("arcmind.iamp")

_MAX_MESSAGES = 10_000
_MAX_MEMORY_ENTRIES = 1_000


class MessageType(str, Enum):
    TASK_ASSIGN = "task_assign"
    TASK_COMPLETE = "task_complete"
    TASK_ESCALATE = "task_escalate"
    INFO_REQUEST = "info_request"
    INFO_RESPONSE = "info_response"
    STATUS_REPORT = "status_report"
    HANDOFF = "handoff"


@dataclass
class AgentMessage:
    """A structured message between agents."""
    id: str
    sender: str
    receiver: str
    msg_type: MessageType
    payload: Dict[str, Any]
    timestamp: float
    reply_to: Optional[str] = None  # Reference to another message id
    task_id: Optional[str] = None   # Associated task


class MessageBus:
    """
    Central message bus for inter-agent communication.
    Supports publish/subscribe and direct messaging.
    """

    def __init__(self):
        self._messages: OrderedDict[str, AgentMessage] = OrderedDict()
        self._subscribers: Dict[str, List[Callable]] = {}  # agent_id → callbacks
        self._type_subscribers: Dict[MessageType, List[Callable]] = {}
        self._lock = Lock()

    def send(
        self,
        sender: str,
        receiver: str,
        msg_type: str | MessageType,
        payload: Dict[str, Any],
        reply_to: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> AgentMessage:
        """Send a message from one agent to another."""
        if isinstance(msg_type, str):
            msg_type = MessageType(msg_type)

        msg = AgentMessage(
            id=uuid.uuid4().hex[:12],
            sender=sender,
            receiver=receiver,
            msg_type=msg_type,
            payload=payload,
            timestamp=time.time(),
            reply_to=reply_to,
            task_id=task_id,
        )

        with self._lock:
            self._messages[msg.id] = msg
            # Evict old messages if over limit
            while len(self._messages) > _MAX_MESSAGES:
                self._messages.popitem(last=False)

        logger.info("[IAMP] %s → %s [%s] task=%s",
                    sender, receiver, msg_type.value, task_id or "none")

        # Notify subscribers
        self._notify(msg)

        # ── Bridge to EventBus (Event-Driven 混合驅動) ──
        self._bridge_to_event_bus(msg)

        return msg

    def subscribe(self, agent_id: str, callback: Callable[[AgentMessage], None]):
        """Subscribe an agent to receive messages directed to it."""
        with self._lock:
            if agent_id not in self._subscribers:
                self._subscribers[agent_id] = []
            self._subscribers[agent_id].append(callback)

    def subscribe_type(self, msg_type: MessageType, callback: Callable[[AgentMessage], None]):
        """Subscribe to all messages of a specific type."""
        with self._lock:
            if msg_type not in self._type_subscribers:
                self._type_subscribers[msg_type] = []
            self._type_subscribers[msg_type].append(callback)

    def _bridge_to_event_bus(self, msg: AgentMessage) -> None:
        """Bridge IAMP messages into the central EventBus for event-driven processing."""
        try:
            from runtime.event_bus import event_bus, Event, EventType
            event_bus.emit(Event(
                type=EventType.IAMP_MESSAGE,
                source=f"iamp:{msg.sender}",
                payload={
                    "msg_type": msg.msg_type.value,
                    "sender": msg.sender,
                    "receiver": msg.receiver,
                    "payload": msg.payload,
                    "task_id": msg.task_id,
                },
                correlation_id=msg.task_id or "",
            ))
        except Exception as e:
            logger.debug("[IAMP] EventBus bridge failed (non-fatal): %s", e)

    def _notify(self, msg: AgentMessage):
        """Notify relevant subscribers."""
        # Snapshot callback lists under lock to avoid races with subscribe()
        with self._lock:
            callbacks = list(self._subscribers.get(msg.receiver, []))
            type_callbacks = list(self._type_subscribers.get(msg.msg_type, []))
        # Direct subscribers (by receiver agent_id)
        for cb in callbacks:
            try:
                cb(msg)
            except Exception as e:
                logger.error("[IAMP] Subscriber error for %s: %s", msg.receiver, e)

        # Type subscribers
        for cb in type_callbacks:
            try:
                cb(msg)
            except Exception as e:
                logger.error("[IAMP] Type subscriber error for %s: %s", msg.msg_type, e)

    def get_inbox(self, agent_id: str, limit: int = 50) -> List[AgentMessage]:
        """Get recent messages for an agent."""
        with self._lock:
            return [
                m for m in reversed(self._messages.values())
                if m.receiver == agent_id
            ][:limit]

    def get_conversation(self, task_id: str) -> List[AgentMessage]:
        """Get all messages related to a task, ordered by time."""
        with self._lock:
            return sorted(
                [m for m in self._messages.values() if m.task_id == task_id],
                key=lambda m: m.timestamp,
            )

    def get_message(self, msg_id: str) -> Optional[AgentMessage]:
        """Get a specific message by ID."""
        with self._lock:
            return self._messages.get(msg_id)

    def stats(self) -> Dict[str, Any]:
        """Get message bus statistics."""
        with self._lock:
            by_type = {}
            by_agent = {}
            for m in self._messages.values():
                by_type[m.msg_type.value] = by_type.get(m.msg_type.value, 0) + 1
                by_agent[m.sender] = by_agent.get(m.sender, 0) + 1
            return {
                "total_messages": len(self._messages),
                "by_type": by_type,
                "by_sender": by_agent,
                "subscribers": len(self._subscribers),
            }


class SharedMemory:
    """
    Shared working memory for a task.
    Multiple agents can read/write context during multi-agent collaboration.
    """

    def __init__(self, task_id: str):
        self.task_id = task_id
        self._data: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._lock = Lock()

    def write(self, agent_id: str, key: str, value: Any):
        """Write a value to shared memory."""
        with self._lock:
            self._data[key] = {
                "value": value,
                "written_by": agent_id,
                "timestamp": time.time(),
            }
            # Evict old entries
            while len(self._data) > _MAX_MEMORY_ENTRIES:
                self._data.popitem(last=False)
        logger.debug("[SharedMemory:%s] %s wrote '%s'", self.task_id, agent_id, key)

    def read(self, key: str) -> Optional[Any]:
        """Read a value from shared memory."""
        with self._lock:
            entry = self._data.get(key)
            return entry["value"] if entry else None

    def read_all(self) -> Dict[str, Any]:
        """Read all shared memory as {key: value}."""
        with self._lock:
            return {k: v["value"] for k, v in self._data.items()}

    def keys(self) -> List[str]:
        with self._lock:
            return list(self._data.keys())

    def summary(self) -> Dict[str, Any]:
        """Summarize shared memory state."""
        with self._lock:
            return {
                "task_id": self.task_id,
                "entries": len(self._data),
                "keys": list(self._data.keys()),
                "writers": list(set(v["written_by"] for v in self._data.values())),
            }


class SharedMemoryManager:
    """Manages shared memory instances per task."""

    def __init__(self):
        self._memories: Dict[str, SharedMemory] = {}
        self._lock = Lock()

    def get(self, task_id: str) -> SharedMemory:
        """Get or create shared memory for a task."""
        with self._lock:
            if task_id not in self._memories:
                self._memories[task_id] = SharedMemory(task_id)
                # Limit total tracked tasks
                while len(self._memories) > 1000:
                    oldest = next(iter(self._memories))
                    del self._memories[oldest]
            return self._memories[task_id]

    def cleanup(self, task_id: str):
        """Remove shared memory for a completed task."""
        with self._lock:
            self._memories.pop(task_id, None)


# ── Global singletons ──
message_bus = MessageBus()
shared_memory_manager = SharedMemoryManager()
