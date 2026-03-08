# -*- coding: utf-8 -*-
"""
ArcMind — Incident Logger
============================
寫入故障事件到 MySQL causal 記憶，供主 Agent 重啟後讀取。
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger("arcmind.incident")

_INCIDENT_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "logs", "incidents.jsonl"
)


def log_incident(cause: str, action: str, result: str,
                 repaired: bool = False) -> None:
    """Log an incident to both JSONL file and MySQL memory."""
    ts = datetime.now(timezone.utc).isoformat()
    record = {
        "ts": ts,
        "cause": cause,
        "action": action,
        "result": result,
        "repaired": repaired,
    }

    # JSONL file (always works, even if MySQL is down)
    try:
        os.makedirs(os.path.dirname(_INCIDENT_FILE), exist_ok=True)
        with open(_INCIDENT_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.error("[Incident] JSONL write failed: %s", e)

    # MySQL causal memory
    try:
        import sys
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from memory.memory_store import memory_store
        memory_store.add_causal(
            cause=cause[:200],
            effect=f"修復動作: {action[:100]} → 結果: {result[:100]}",
            confidence=0.95 if repaired else 0.5,
        )
        # Also add a semantic memory so the main agent remembers
        memory_store.add_semantic(
            content=f"[系統事件] {ts}: {cause[:100]} → {action[:100]} ({'已修復' if repaired else '未修復'})",
            source="repair_agent",
            importance=0.9,
        )
    except Exception as e:
        logger.warning("[Incident] MySQL write failed (non-fatal): %s", e)

    logger.info("[Incident] %s → %s → %s (repaired=%s)", cause, action, result, repaired)


def get_recent_incidents(limit: int = 5) -> list[dict]:
    """Read recent incidents from MySQL memory."""
    try:
        import sys
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from memory.memory_store import memory_store
        hits = memory_store.query(
            query="系統事件 修復 故障",
            top_k=limit,
            memory_types=["causal", "semantic"],
            tags=["causal", "inference"],
        )
        return [h for h in hits if "系統事件" in h.get("content", "") or "修復" in h.get("content", "")]
    except Exception:
        # Fallback to JSONL
        try:
            with open(_INCIDENT_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
            return [json.loads(line) for line in lines[-limit:]]
        except Exception:
            return []
