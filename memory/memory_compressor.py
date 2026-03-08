# -*- coding: utf-8 -*-
"""
ArcMind — Memory Compressor
=============================
定期壓縮 episodic 記憶 → semantic 記憶。
避免 episodic 無限增長，保留長期知識。

策略：
  1. 掃描超過 N 天的 episodic 記憶
  2. 按來源/時段分組
  3. 合併為 semantic 摘要
  4. 刪除已壓縮的 episodic 原文

適合作為 CRON job 每天跑一次。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("arcmind.memory_compressor")


def compress_episodic(days_old: int = 7, max_batch: int = 20) -> dict:
    """
    Compress old episodic memories into semantic summaries.
    
    Args:
        days_old: Compress memories older than this many days
        max_batch: Max number of memories to compress per run
    
    Returns:
        Stats dict with counts
    """
    from memory.memory_store import memory_store

    # Get episodic count
    counts = memory_store.count()
    total_episodic = counts.get("episodic", 0)
    if total_episodic == 0:
        return {"compressed": 0, "deleted": 0, "skipped": 0, "total_episodic": 0}

    cutoff = (datetime.utcnow() - timedelta(days=days_old)).isoformat()

    # Query old episodic memories directly from SQLite
    import sqlite3
    with memory_store._conn() as conn:
        rows = conn.execute(
            "SELECT id, content, source, created_at FROM memories "
            "WHERE memory_type = 'episodic' AND created_at < ? "
            "ORDER BY created_at ASC LIMIT ?",
            (cutoff, max_batch),
        ).fetchall()

    if not rows:
        return {"compressed": 0, "deleted": 0, "skipped": 0, "total_episodic": total_episodic}

    old_items = [
        {"id": r["id"], "content": r["content"],
         "source": r["source"] or "unknown", "created_at": r["created_at"]}
        for r in rows
    ]

    # Batch compress: group by source
    groups: dict[str, list] = {}
    for item in old_items:
        src = item["source"]
        groups.setdefault(src, []).append(item)

    compressed = 0
    deleted = 0

    for source, items in groups.items():
        if len(items) < 2:
            # Single item, skip compression (not worth it)
            continue

        # Build summary from multiple episodic entries
        content_parts = [item["content"][:200] for item in items]
        date_range = f"{items[0]['created_at'][:10]} ~ {items[-1]['created_at'][:10]}"
        summary = (
            f"[壓縮記憶] 來源: {source} | 期間: {date_range} | "
            f"原始 {len(items)} 筆\n"
            + "\n".join(f"- {p}" for p in content_parts[:10])
        )

        # Write as semantic
        result = memory_store.add_semantic(
            content=summary,
            source=f"compressed:{source}",
            importance=0.6,
        )

        if result:
            compressed += 1
            # Delete compressed episodic entries
            for item in items:
                try:
                    memory_store.delete(item["id"], memory_type="episodic")
                    deleted += 1
                except Exception:
                    pass

    # Get updated count
    updated_counts = memory_store.count()
    stats = {
        "compressed": compressed,
        "deleted": deleted,
        "skipped": len(old_items) - deleted,
        "total_episodic": updated_counts.get("episodic", 0),
        "groups": len(groups),
    }
    logger.info("[MemoryCompressor] %s", stats)
    return stats


def run(inputs: dict | None = None) -> dict:
    """
    Entry point for CRON / skill invocation.
    
    Inputs:
        days_old: int (default 7) — compress memories older than N days
        max_batch: int (default 20) — max entries per run
    """
    inputs = inputs or {}
    days = inputs.get("days_old", 7)
    batch = inputs.get("max_batch", 20)

    try:
        stats = compress_episodic(days_old=days, max_batch=batch)
        return {"success": True, **stats}
    except Exception as e:
        logger.error("[MemoryCompressor] failed: %s", e)
        return {"success": False, "error": str(e)}
