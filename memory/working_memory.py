# -*- coding: utf-8 -*-
"""
ArcMind — Working Memory
==========================
移植自 ARCHILLX v0.44 memory/working_memory.py。

Per-task in-memory buffer：任務進行中存放中間步驟，
完成後 flush 重要結論到長期記憶（semantic）。
"""
from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger("arcmind.working_memory")

_MAX_SUMMARY_LEN = 300
_lock = threading.Lock()


class WorkingMemory:
    """Per-task working memory. Thread-safe."""

    def __init__(self, max_items: int = 20):
        self.max_items = max_items
        self._tasks: dict[str, list[dict[str, Any]]] = {}
        self._summaries: dict[str, str] = {}

    def add(self, task_id: str, content: str, kind: str = "observation") -> None:
        """Append an observation to this task's working memory."""
        with _lock:
            items = self._tasks.setdefault(task_id, [])
            items.append({"kind": kind, "content": content[:500]})
            if len(items) > self.max_items:
                self._compact(task_id)

    def get(self, task_id: str) -> list[dict[str, Any]]:
        with _lock:
            return list(self._tasks.get(task_id, []))

    def get_summary(self, task_id: str) -> str:
        with _lock:
            return self._summaries.get(task_id, "")

    def clear(self, task_id: str) -> None:
        with _lock:
            self._tasks.pop(task_id, None)
            self._summaries.pop(task_id, None)

    def flush(self, task_id: str, memory_store, user_command: str = "") -> None:
        """
        Task complete: write important conclusions to semantic memory,
        then clear working memory.
        """
        with _lock:
            items = self._tasks.get(task_id, [])
            if not items:
                return

            action_items = [
                it for it in items
                if it["kind"] in ("action", "result", "conclusion")
            ]
            if not action_items:
                action_items = items[-3:]

            summary_parts = [it["content"][:100] for it in action_items]
            summary = "; ".join(summary_parts)[:_MAX_SUMMARY_LEN]

        if summary and memory_store:
            try:
                memory_store.add_semantic(
                    content=f"任務：{user_command[:100]}\n結論：{summary}",
                    source="working_memory",
                    importance=0.6,
                )
                logger.info(
                    "[WorkingMem] flushed %d items to semantic (task=%s)",
                    len(action_items), task_id[:16],
                )
            except Exception as e:
                logger.warning("[WorkingMem] flush failed: %s", e)

        self.clear(task_id)

    def _compact(self, task_id: str) -> None:
        items = self._tasks.get(task_id, [])
        keep_tail = self.max_items // 2
        to_drop = items[:-keep_tail]
        remaining = items[-keep_tail:]

        summary = "; ".join(it["content"][:60] for it in to_drop)[:_MAX_SUMMARY_LEN]
        self._summaries[task_id] = summary
        self._tasks[task_id] = remaining


# ── Context Pruning Helpers (for Tool Loop) ─────────────────────────────────

def flush_step_logs(messages: list[dict], keep_recent: int = 4) -> list[dict]:
    """
    Remove verbose tool_call / tool_result messages from conversation history,
    keeping only the most recent `keep_recent` tool exchanges.

    Preserves:
      - All system messages
      - The initial user message
      - The last `keep_recent` assistant+tool pairs
      - Any non-tool assistant messages

    Returns a new pruned message list (does not mutate the input).
    """
    # Separate system/initial messages from tool exchange messages
    preserved = []
    tool_exchanges = []

    for msg in messages:
        role = msg.get("role", "")
        # System messages always kept
        if role == "system":
            preserved.append(msg)
        # First user message always kept
        elif role == "user" and not preserved:
            preserved.append(msg)
        elif role == "user" and not any(
            isinstance(c, dict) and c.get("type") == "tool_result"
            for c in (msg.get("content", []) if isinstance(msg.get("content"), list) else [])
        ):
            # Regular user message (not an Anthropic tool_result wrapper)
            preserved.append(msg)
        else:
            tool_exchanges.append(msg)

    # Keep only the last `keep_recent` tool exchange messages
    if len(tool_exchanges) > keep_recent:
        pruned_count = len(tool_exchanges) - keep_recent
        tool_exchanges = tool_exchanges[-keep_recent:]
        logger.info("[ContextPrune] flushed %d tool messages, kept %d", pruned_count, keep_recent)

    return preserved + tool_exchanges


def inject_checkpoint(messages: list[dict], summary: str) -> list[dict]:
    """
    Inject a checkpoint summary into the message history.
    Replaces verbose tool history with a condensed progress note.

    The summary is injected as a system message right before the last
    tool exchange block, so the LLM knows what was accomplished.
    """
    if not summary:
        return messages

    checkpoint_msg = {
        "role": "system" if messages and messages[0].get("role") == "system" else "user",
        "content": f"[Checkpoint] 前序步驟完成摘要：\n{summary}\n\n請基於以上進度繼續執行。",
    }

    # If the first message is system, inject after system; otherwise prepend
    # Find the right insertion point: after system messages, before tool exchanges
    insert_idx = 0
    for i, msg in enumerate(messages):
        if msg.get("role") == "system":
            insert_idx = i + 1
        elif msg.get("role") == "user":
            insert_idx = i + 1
            break

    result = list(messages)
    result.insert(insert_idx, checkpoint_msg)
    logger.info("[Checkpoint] injected summary (%d chars) at position %d", len(summary), insert_idx)
    return result


# Singleton
working_memory = WorkingMemory()

