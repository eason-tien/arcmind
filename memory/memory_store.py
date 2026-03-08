# -*- coding: utf-8 -*-
"""
ArcMind — Four-Layer Memory Store (SQLite + Vector)
=====================================================
四層認知記憶：
  - episodic   : 對話歷史、事件 (自動衰減)
  - semantic   : 長期知識、用戶偏好 (高持久性)
  - procedural : 技能使用模式 (skill → result)
  - causal     : 因果推理 (cause → effect)

Backend: SQLite (純本地，零依賴)
Embedding: Ollama nomic-embed-text (768-dim)
Search: 真正的向量 cosine similarity (brute-force ANN)

為什麼不用 ChromaDB?
  → Python 3.14 不支持 chromadb 的 pydantic v1 依賴。
  → 自建方案零外部依賴，啟動快，記憶量 <100K 時效能夠。
"""
from __future__ import annotations

import json
import logging
import math
import os
import sqlite3
import struct
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger("arcmind.memory_store")

MemoryType = Literal["episodic", "semantic", "procedural", "causal"]

_DB_PATH = str(Path(__file__).parent.parent / "data" / "vector_memory.db")


# ── Vector Math (pure Python, no numpy) ──────────────────────────────────────

def _cosine_sim(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _vec_to_bytes(vec: list[float]) -> bytes:
    """Pack float vector to compact bytes (4 bytes per float)."""
    return struct.pack(f"{len(vec)}f", *vec)


def _bytes_to_vec(data: bytes) -> list[float]:
    """Unpack bytes back to float vector."""
    n = len(data) // 4
    return list(struct.unpack(f"{n}f", data))


# ── Ollama Embedding ─────────────────────────────────────────────────────────

class _Embedder:
    """Embed text via local Ollama."""

    def __init__(self):
        self._base_url = os.getenv(
            "OLLAMA_BASE_URL", "http://localhost:11434"
        ).replace("/v1", "").rstrip("/")
        self._model = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")

    def embed(self, text: str) -> list[float]:
        """Get embedding for a single text. Returns empty list on failure."""
        import httpx
        try:
            resp = httpx.post(
                f"{self._base_url}/api/embeddings",
                json={"model": self._model, "prompt": text[:2000]},
                timeout=30.0,
            )
            resp.raise_for_status()
            return resp.json().get("embedding", [])
        except Exception as e:
            logger.warning("[Embedder] failed: %s", e)
            return []

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts."""
        return [self.embed(t) for t in texts]


# ── SQLite Schema ─────────────────────────────────────────────────────────────

_INIT_SQL = """
CREATE TABLE IF NOT EXISTS memories (
    id          TEXT PRIMARY KEY,
    content     TEXT NOT NULL,
    memory_type TEXT NOT NULL DEFAULT 'episodic',
    source      TEXT DEFAULT '',
    importance  REAL DEFAULT 0.5,
    tags        TEXT DEFAULT '[]',
    metadata_   TEXT DEFAULT '{}',
    embedding   BLOB,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(memory_type);
CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at);
CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance);
"""


# ── Memory Store ──────────────────────────────────────────────────────────────

class MemoryStore:
    """
    Four-layer memory store with true vector semantic search.
    Pure Python, zero external dependencies beyond httpx (for Ollama).
    """

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or _DB_PATH
        self._embedder = _Embedder()
        self._lock = threading.Lock()

        # Ensure data dir exists
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

        # Init schema
        with self._conn() as conn:
            conn.executescript(_INIT_SQL)

        count = self._count_all()
        logger.info("[MemoryStore] SQLite vector store ready at %s (%d entries)",
                     self._db_path, count)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _count_all(self) -> int:
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

    # ── Write Methods ────────────────────────────────────────────────────────

    def add(self, content: str,
            source: str = "arcmind",
            tags: list[str] | None = None,
            importance: float = 0.5,
            metadata: dict | None = None,
            memory_type: MemoryType = "episodic",
            dedup: bool = True) -> str | None:
        """Add a memory entry. Returns the ID or None if deduped."""
        if not content or not content.strip():
            return None

        # Embed
        embedding = self._embedder.embed(content)

        # Dedup via vector similarity
        if dedup and embedding:
            similar = self._find_similar(embedding, memory_type, threshold=0.85, limit=1)
            if similar:
                logger.debug("[MemoryStore] dedup: similar entry exists (sim=%.3f)",
                              similar[0]["similarity"])
                return None

        doc_id = str(uuid.uuid4())[:12]
        now = datetime.utcnow().isoformat()
        emb_blob = _vec_to_bytes(embedding) if embedding else None

        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO memories 
                       (id, content, memory_type, source, importance, tags, metadata_, embedding, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (doc_id, content, memory_type, source, importance,
                     json.dumps(tags or []), json.dumps(metadata or {}),
                     emb_blob, now, now),
                )

        logger.debug("[MemoryStore] added %s/%s: '%s...' (imp=%.1f, vec=%d)",
                      memory_type, doc_id, content[:40], importance,
                      len(embedding))
        return doc_id

    def add_episodic(self, content: str, source: str = "conversation",
                     session_id: str | None = None, **kw) -> str | None:
        meta = {"session_id": session_id} if session_id else {}
        return self.add(content, source=source, memory_type="episodic",
                        importance=kw.get("importance", 0.4),
                        metadata=meta, dedup=kw.get("dedup", True))

    def add_semantic(self, content: str, source: str = "agent",
                     importance: float = 0.7, **kw) -> str | None:
        return self.add(content, source=source, memory_type="semantic",
                        importance=importance, dedup=True,
                        tags=kw.get("tags"), metadata=kw.get("metadata"))

    def add_procedural(self, content: str, skill_used: str | None = None,
                       importance: float = 0.6, **kw) -> str | None:
        meta = {"skill_used": skill_used} if skill_used else {}
        return self.add(content, source="agent", memory_type="procedural",
                        importance=importance, metadata=meta,
                        tags=kw.get("tags"), dedup=kw.get("dedup", True))

    def add_causal(self, cause: str, effect: str,
                   confidence: float = 0.8, **kw) -> str | None:
        content = f"因: {cause}\n果: {effect}"
        meta = {"confidence": confidence}
        return self.add(content, source="agent", memory_type="causal",
                        importance=confidence, metadata=meta,
                        tags=kw.get("tags"), dedup=kw.get("dedup", True))

    # ── Query Methods ────────────────────────────────────────────────────────

    def _find_similar(self, query_vec: list[float], memory_type: str | None = None,
                      threshold: float = 0.0, limit: int = 5) -> list[dict]:
        """Find similar memories by vector cosine similarity."""
        with self._conn() as conn:
            if memory_type:
                rows = conn.execute(
                    "SELECT * FROM memories WHERE memory_type = ? AND embedding IS NOT NULL",
                    (memory_type,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM memories WHERE embedding IS NOT NULL"
                ).fetchall()

        results = []
        for row in rows:
            doc_vec = _bytes_to_vec(row["embedding"])
            sim = _cosine_sim(query_vec, doc_vec)
            if sim >= threshold:
                results.append({
                    "id": row["id"],
                    "content": row["content"],
                    "memory_type": row["memory_type"],
                    "source": row["source"],
                    "importance": row["importance"],
                    "tags": json.loads(row["tags"] or "[]"),
                    "created_at": row["created_at"],
                    "similarity": sim,
                    "score": sim * 0.7 + row["importance"] * 0.3,
                })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

    def query(self, query: str, top_k: int = 5,
              tags: list[str] | None = None,
              min_importance: float = 0.0,
              memory_types: list[MemoryType] | None = None) -> list[dict]:
        """
        Semantic vector search across memory collections.
        True cosine similarity search via Ollama embeddings.
        """
        if not query or not query.strip():
            return []

        query_vec = self._embedder.embed(query)
        if not query_vec:
            # Fallback: keyword search
            return self._keyword_search(query, top_k, memory_types)

        types = memory_types or ["episodic", "semantic", "procedural", "causal"]
        all_results: list[dict] = []

        for mtype in types:
            results = self._find_similar(query_vec, mtype, threshold=0.1, limit=top_k * 2)
            all_results.extend(results)

        # Filter by importance
        if min_importance > 0:
            all_results = [r for r in all_results if r["importance"] >= min_importance]

        # Filter by tags
        if tags:
            tag_set = set(tags)
            all_results = [r for r in all_results if tag_set & set(r.get("tags", []))]

        all_results.sort(key=lambda x: x["score"], reverse=True)
        return all_results[:top_k]

    def _keyword_search(self, query: str, top_k: int = 5,
                        memory_types: list[str] | None = None) -> list[dict]:
        """Fallback keyword search when embeddings unavailable."""
        with self._conn() as conn:
            conditions = ["content LIKE ?"]
            params: list[Any] = [f"%{query}%"]
            if memory_types:
                placeholders = ",".join("?" * len(memory_types))
                conditions.append(f"memory_type IN ({placeholders})")
                params.extend(memory_types)

            sql = f"SELECT * FROM memories WHERE {' AND '.join(conditions)} ORDER BY importance DESC, created_at DESC LIMIT ?"
            params.append(top_k)
            rows = conn.execute(sql, params).fetchall()

        return [{
            "id": r["id"], "content": r["content"],
            "memory_type": r["memory_type"], "source": r["source"],
            "importance": r["importance"],
            "tags": json.loads(r["tags"] or "[]"),
            "created_at": r["created_at"],
            "score": r["importance"], "similarity": 0.0,
        } for r in rows]

    def query_episodic(self, query: str, top_k: int = 3, **kw) -> list[dict]:
        return self.query(query, top_k=top_k, memory_types=["episodic"], **kw)

    def query_semantic(self, query: str, top_k: int = 3, **kw) -> list[dict]:
        return self.query(query, top_k=top_k, memory_types=["semantic"], **kw)

    def query_procedural(self, query: str, top_k: int = 2, **kw) -> list[dict]:
        return self.query(query, top_k=top_k, memory_types=["procedural"], **kw)

    def query_causal(self, query: str, top_k: int = 2, **kw) -> list[dict]:
        return self.query(query, top_k=top_k, memory_types=["causal"], **kw)

    def get_recent(self, limit: int = 10,
                   memory_type: MemoryType | None = None) -> list[dict]:
        """Get most recent memories."""
        with self._conn() as conn:
            if memory_type:
                rows = conn.execute(
                    "SELECT * FROM memories WHERE memory_type = ? ORDER BY created_at DESC LIMIT ?",
                    (memory_type, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM memories ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()

        return [{
            "id": r["id"], "content": r["content"],
            "memory_type": r["memory_type"], "source": r["source"],
            "importance": r["importance"],
            "created_at": r["created_at"],
        } for r in rows]

    def delete(self, memory_id: str, memory_type: MemoryType | None = None) -> bool:
        """Delete a memory by ID."""
        with self._lock:
            with self._conn() as conn:
                if memory_type:
                    conn.execute("DELETE FROM memories WHERE id = ? AND memory_type = ?",
                                 (memory_id, memory_type))
                else:
                    conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
                return conn.total_changes > 0

    def count(self) -> dict[str, int]:
        """Get counts per type."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT memory_type, COUNT(*) as cnt FROM memories GROUP BY memory_type"
            ).fetchall()
        result = {t: 0 for t in ("episodic", "semantic", "procedural", "causal")}
        for r in rows:
            result[r["memory_type"]] = r["cnt"]
        return result

    def stats(self) -> dict:
        """Get memory statistics."""
        counts = self.count()
        return {
            "total": sum(counts.values()),
            "by_type": counts,
            "backend": "SQLite + Vector",
            "path": self._db_path,
        }


# ── Migration: Import old am_memory data ─────────────────────────────────────

def _migrate_from_old_db(store: MemoryStore) -> None:
    """One-time migration: read old am_memory rows into new vector store."""
    old_db = Path(__file__).parent.parent / "data" / "arcmind.db"
    if not old_db.exists():
        return

    # Check if already migrated
    if store._count_all() > 0:
        return

    try:
        conn = sqlite3.connect(str(old_db))
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT content, memory_type, source, importance, tags FROM am_memory").fetchall()
        conn.close()

        migrated = 0
        for r in rows:
            mtype = r["memory_type"] or "episodic"
            if mtype not in ("episodic", "semantic", "procedural", "causal"):
                mtype = "episodic"
            tags = json.loads(r["tags"]) if r["tags"] else []
            result = store.add(
                content=r["content"],
                source=r["source"] or "migrated",
                tags=tags,
                importance=float(r["importance"] or 0.5),
                memory_type=mtype,
                dedup=False,
            )
            if result:
                migrated += 1

        if migrated:
            logger.info("[MemoryStore] Migrated %d entries from old DB", migrated)
    except Exception as e:
        logger.warning("[MemoryStore] Migration failed (non-fatal): %s", e)


# ── Singleton ─────────────────────────────────────────────────────────────────
memory_store = MemoryStore()

try:
    _migrate_from_old_db(memory_store)
except Exception:
    pass
