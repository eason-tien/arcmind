"""
Skill: memory_kg
Knowledge Graph + Vector Search 記憶系統

功能:
- store_fact: 儲存事實/知識
- query_facts: 用自然語言查詢
- list_entities: 列出所有實體
- relate: 建立實體間關係
- search_similar: 語義相似度搜尋 (cosine similarity)
- forget: 刪除事實

底層: SQLite FTS5 + embedding cosine similarity（零外部依賴）
DB 路徑: <arcmind>/data/memory_kg.db
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("arcmind.skill.memory_kg")

_ARCMIND_DIR = Path(__file__).resolve().parent.parent
_DB_PATH = _ARCMIND_DIR / "data" / "memory_kg.db"


def _get_db() -> sqlite3.Connection:
    """Get or create the KG database."""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    # Core tables
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS entities (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            entity_type TEXT DEFAULT 'concept',
            description TEXT DEFAULT '',
            metadata TEXT DEFAULT '{}',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS facts (
            id TEXT PRIMARY KEY,
            subject TEXT NOT NULL,
            predicate TEXT NOT NULL,
            object TEXT NOT NULL,
            confidence REAL DEFAULT 1.0,
            source TEXT DEFAULT '',
            metadata TEXT DEFAULT '{}',
            created_at REAL NOT NULL,
            FOREIGN KEY (subject) REFERENCES entities(id),
            FOREIGN KEY (object) REFERENCES entities(id)
        );

        CREATE TABLE IF NOT EXISTS embeddings (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            content_type TEXT DEFAULT 'fact',
            ref_id TEXT DEFAULT '',
            vector TEXT NOT NULL,
            created_at REAL NOT NULL
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
            subject, predicate, object, source,
            content='facts',
            content_rowid='rowid'
        );
    """)
    return conn


def _entity_id(name: str) -> str:
    """Generate consistent entity ID from name."""
    return hashlib.md5(name.lower().strip().encode()).hexdigest()[:12]


def _fact_id(subject: str, predicate: str, obj: str) -> str:
    """Generate fact ID from triple."""
    return hashlib.md5(f"{subject}|{predicate}|{obj}".lower().encode()).hexdigest()[:16]


def _get_embedding(text: str) -> list[float] | None:
    """Get text embedding using model router (if available)."""
    try:
        from runtime.model_router import model_router
        result = model_router.embed(text)
        if result and hasattr(result, 'embedding'):
            return result.embedding
        if isinstance(result, list):
            return result
    except Exception as e:
        logger.debug("[memory_kg] Embedding failed: %s", e)
    return None


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ── Actions ──────────────────────────────────────────────────

def _store_fact(inputs: dict) -> dict:
    """Store a fact as a subject-predicate-object triple."""
    subject = inputs.get("subject", "").strip()
    predicate = inputs.get("predicate", "").strip()
    obj = inputs.get("object", "").strip()
    source = inputs.get("source", "user")
    confidence = float(inputs.get("confidence", 1.0))

    if not all([subject, predicate, obj]):
        return {"success": False, "error": "subject, predicate, object 都是必填"}

    now = time.time()
    conn = _get_db()

    # Ensure entities exist
    for name in [subject, obj]:
        eid = _entity_id(name)
        conn.execute(
            "INSERT OR IGNORE INTO entities (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (eid, name, now, now)
        )

    # Insert fact
    fid = _fact_id(subject, predicate, obj)
    conn.execute(
        "INSERT OR REPLACE INTO facts (id, subject, predicate, object, confidence, source, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (fid, subject, predicate, obj, confidence, source, now)
    )

    # Update FTS
    try:
        conn.execute(
            "INSERT INTO facts_fts (rowid, subject, predicate, object, source) "
            "SELECT rowid, subject, predicate, object, source FROM facts WHERE id = ?",
            (fid,)
        )
    except Exception:
        pass  # FTS sync error is non-fatal

    # Store embedding for semantic search
    fact_text = f"{subject} {predicate} {obj}"
    embedding = _get_embedding(fact_text)
    if embedding:
        conn.execute(
            "INSERT OR REPLACE INTO embeddings (id, content, content_type, ref_id, vector, created_at) "
            "VALUES (?, ?, 'fact', ?, ?, ?)",
            (fid, fact_text, fid, json.dumps(embedding), now)
        )

    conn.commit()
    conn.close()

    return {"success": True, "fact_id": fid, "triple": f"{subject} → {predicate} → {obj}"}


def _query_facts(inputs: dict) -> dict:
    """Query facts using FTS5 full-text search."""
    query = inputs.get("query", "").strip()
    max_results = int(inputs.get("max_results", 20))

    if not query:
        return {"success": False, "error": "query 為必填"}

    conn = _get_db()

    # FTS5 search
    try:
        rows = conn.execute(
            "SELECT f.* FROM facts f "
            "JOIN facts_fts fts ON f.rowid = fts.rowid "
            "WHERE facts_fts MATCH ? LIMIT ?",
            (query, max_results)
        ).fetchall()
    except Exception:
        # Fallback to LIKE search
        rows = conn.execute(
            "SELECT * FROM facts WHERE subject LIKE ? OR predicate LIKE ? OR object LIKE ? LIMIT ?",
            (f"%{query}%", f"%{query}%", f"%{query}%", max_results)
        ).fetchall()

    facts = [
        {
            "id": r["id"],
            "subject": r["subject"],
            "predicate": r["predicate"],
            "object": r["object"],
            "confidence": r["confidence"],
            "source": r["source"],
        }
        for r in rows
    ]

    conn.close()
    return {"success": True, "facts": facts, "count": len(facts)}


def _list_entities(inputs: dict) -> dict:
    """List all entities in the knowledge graph."""
    entity_type = inputs.get("entity_type", "")
    max_results = int(inputs.get("max_results", 50))

    conn = _get_db()

    if entity_type:
        rows = conn.execute(
            "SELECT * FROM entities WHERE entity_type = ? ORDER BY updated_at DESC LIMIT ?",
            (entity_type, max_results)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM entities ORDER BY updated_at DESC LIMIT ?",
            (max_results,)
        ).fetchall()

    entities = [
        {
            "id": r["id"],
            "name": r["name"],
            "type": r["entity_type"],
            "description": r["description"],
        }
        for r in rows
    ]

    conn.close()
    return {"success": True, "entities": entities, "count": len(entities)}


def _relate(inputs: dict) -> dict:
    """Create a relation between two entities (convenience wrapper for store_fact)."""
    entity_a = inputs.get("entity_a", "").strip()
    relation = inputs.get("relation", "").strip()
    entity_b = inputs.get("entity_b", "").strip()

    if not all([entity_a, relation, entity_b]):
        return {"success": False, "error": "entity_a, relation, entity_b 都是必填"}

    return _store_fact({
        "subject": entity_a,
        "predicate": relation,
        "object": entity_b,
        "source": inputs.get("source", "user"),
    })


def _search_similar(inputs: dict) -> dict:
    """Search for semantically similar content using embeddings."""
    query = inputs.get("query", "").strip()
    max_results = int(inputs.get("max_results", 10))
    threshold = float(inputs.get("threshold", 0.6))

    if not query:
        return {"success": False, "error": "query 為必填"}

    query_embedding = _get_embedding(query)
    if not query_embedding:
        # Fallback to FTS search
        logger.info("[memory_kg] No embedding available, falling back to FTS")
        return _query_facts(inputs)

    conn = _get_db()
    rows = conn.execute("SELECT * FROM embeddings").fetchall()

    results = []
    for row in rows:
        try:
            stored_vec = json.loads(row["vector"])
            sim = _cosine_similarity(query_embedding, stored_vec)
            if sim >= threshold:
                results.append({
                    "content": row["content"],
                    "type": row["content_type"],
                    "ref_id": row["ref_id"],
                    "similarity": round(sim, 4),
                })
        except Exception:
            continue

    results.sort(key=lambda x: x["similarity"], reverse=True)
    results = results[:max_results]

    conn.close()
    return {"success": True, "results": results, "count": len(results)}


def _forget(inputs: dict) -> dict:
    """Delete a fact by ID or by triple match."""
    fact_id = inputs.get("fact_id", "")
    subject = inputs.get("subject", "")
    predicate = inputs.get("predicate", "")
    obj = inputs.get("object", "")

    conn = _get_db()

    if fact_id:
        conn.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
        conn.execute("DELETE FROM embeddings WHERE ref_id = ?", (fact_id,))
    elif subject and predicate and obj:
        fid = _fact_id(subject, predicate, obj)
        conn.execute("DELETE FROM facts WHERE id = ?", (fid,))
        conn.execute("DELETE FROM embeddings WHERE ref_id = ?", (fid,))
    else:
        conn.close()
        return {"success": False, "error": "需要 fact_id 或完整的 subject/predicate/object"}

    conn.commit()
    deleted = conn.total_changes
    conn.close()

    return {"success": True, "deleted": deleted}


def _stats(inputs: dict) -> dict:
    """Get knowledge graph statistics."""
    conn = _get_db()
    entity_count = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    fact_count = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
    embedding_count = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
    conn.close()

    return {
        "success": True,
        "entities": entity_count,
        "facts": fact_count,
        "embeddings": embedding_count,
        "db_path": str(_DB_PATH),
    }


# ── Main Entry ────────────────────────────────────────────────

def run(inputs: dict) -> dict:
    """
    Knowledge Graph skill entry point.

    inputs:
      action: store_fact | query_facts | list_entities | relate |
              search_similar | forget | stats
    """
    action = inputs.get("action", "stats")

    handlers = {
        "store_fact": _store_fact,
        "query_facts": _query_facts,
        "list_entities": _list_entities,
        "relate": _relate,
        "search_similar": _search_similar,
        "forget": _forget,
        "stats": _stats,
    }

    handler = handlers.get(action)
    if not handler:
        return {
            "success": False,
            "error": f"未知 action: {action}",
            "available_actions": list(handlers.keys()),
        }

    try:
        return handler(inputs)
    except Exception as e:
        logger.error("[memory_kg] %s failed: %s", action, e)
        return {"success": False, "error": str(e), "action": action}
