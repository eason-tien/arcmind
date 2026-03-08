# -*- coding: utf-8 -*-
"""
ArcMind — SOP Vector Cache (Module B)
=======================================
將成功完成的任務 SOP 向量化存入快取，
下次遇到類似任務時自動檢索歷史 SOP 作為參考。

存儲：SQLite (data/sop_cache.db)
向量：OllamaEmbedding (nomic-embed-text)
搜索：Cosine Similarity > threshold
"""
from __future__ import annotations

import json
import logging
import sqlite3
import struct
import threading
import time
from pathlib import Path

logger = logging.getLogger("arcmind.memory.sop")

_DB_PATH = str(Path(__file__).parent.parent / "data" / "sop_cache.db")

_INIT_SQL = """
CREATE TABLE IF NOT EXISTS sop_entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt      TEXT NOT NULL,
    sop_content TEXT NOT NULL,
    embedding   BLOB,
    created_at  REAL NOT NULL,
    tags        TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_sop_created ON sop_entries(created_at);
"""


# ── Vector helpers ──────────────────────────────────────────────────────────

def _vec_to_bytes(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _bytes_to_vec(data: bytes) -> list[float]:
    n = len(data) // 4
    return list(struct.unpack(f"{n}f", data))


def _cosine_sim(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    import math
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ── SOP Manager ─────────────────────────────────────────────────────────────

class SOPManager:
    """SOP 向量快取：存儲/搜索成功的任務拆解步驟。"""

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or _DB_PATH
        self._lock = threading.Lock()
        self._embedder = None  # lazy init
        self._init_db()

    def _init_db(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.executescript(_INIT_SQL)

    def _get_embedder(self):
        if self._embedder is None:
            try:
                from memory.embedding import get_adapter
                self._embedder = get_adapter()
            except Exception as e:
                logger.warning("[SOPManager] Embedder init failed: %s", e)
                self._embedder = None
        return self._embedder

    def _embed(self, text: str) -> list[float]:
        embedder = self._get_embedder()
        if not embedder:
            return []
        try:
            vecs = embedder.embed([text[:512]])  # truncate for embedding
            return vecs[0] if vecs else []
        except Exception as e:
            logger.warning("[SOPManager] Embed failed: %s", e)
            return []

    # ── Save ──

    def save_successful_sop(self, task_prompt: str, sop_content: str,
                            tags: str = "") -> None:
        """
        保存成功的 SOP 到向量快取。
        此函數應在 daemon thread 中呼叫（fire-and-forget）。
        """
        if not task_prompt or not sop_content:
            return

        try:
            vec = self._embed(task_prompt)
            vec_bytes = _vec_to_bytes(vec) if vec else None

            with self._lock:
                with sqlite3.connect(self._db_path) as conn:
                    conn.execute(
                        "INSERT INTO sop_entries (prompt, sop_content, embedding, created_at, tags) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (task_prompt[:500], sop_content[:4000],
                         vec_bytes, time.time(), tags),
                    )

            logger.info("[SOPManager] Saved SOP: prompt='%s...' (%d chars)",
                        task_prompt[:60], len(sop_content))

        except Exception as e:
            logger.warning("[SOPManager] Save failed: %s", e)

    # ── Search ──

    def search_similar_sop(self, current_prompt: str,
                           threshold: float = 0.85,
                           limit: int = 1) -> str:
        """
        搜索相似的歷史 SOP。
        同步操作（SQLite read + cosine），延遲 < 5ms。
        
        Returns:
            如果找到相似度 > threshold 的 SOP，返回 <History_SOP> XML tag。
            否則返回空字串。
        """
        if not current_prompt:
            return ""

        query_vec = self._embed(current_prompt)
        if not query_vec:
            return ""

        try:
            with self._lock:
                with sqlite3.connect(self._db_path) as conn:
                    rows = conn.execute(
                        "SELECT prompt, sop_content, embedding FROM sop_entries "
                        "WHERE embedding IS NOT NULL "
                        "ORDER BY created_at DESC LIMIT 200"
                    ).fetchall()

            if not rows:
                return ""

            # Cosine similarity search
            best_score = 0.0
            best_sop = ""
            best_prompt = ""

            for prompt_text, sop_content, emb_bytes in rows:
                if not emb_bytes:
                    continue
                stored_vec = _bytes_to_vec(emb_bytes)
                score = _cosine_sim(query_vec, stored_vec)
                if score > best_score:
                    best_score = score
                    best_sop = sop_content
                    best_prompt = prompt_text

            if best_score >= threshold:
                logger.info("[SOPManager] Found similar SOP (score=%.3f): '%s...'",
                            best_score, best_prompt[:60])
                return (
                    f"<History_SOP similarity=\"{best_score:.2f}\">\n"
                    f"原始任務: {best_prompt}\n"
                    f"SOP 步驟:\n{best_sop}\n"
                    f"</History_SOP>"
                )

            return ""

        except Exception as e:
            logger.warning("[SOPManager] Search failed: %s", e)
            return ""

    # ── Stats ──

    def count(self) -> int:
        try:
            with sqlite3.connect(self._db_path) as conn:
                return conn.execute("SELECT COUNT(*) FROM sop_entries").fetchone()[0]
        except Exception:
            return 0


# ── Fire-and-forget helper ──

def _fire_and_forget_save(prompt: str, sop: str) -> None:
    """Non-blocking SOP save via daemon thread."""
    t = threading.Thread(
        target=sop_manager.save_successful_sop,
        args=(prompt, sop),
        daemon=True,
        name="sop-save",
    )
    t.start()


# ── Singleton ──
sop_manager = SOPManager()
