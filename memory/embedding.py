# -*- coding: utf-8 -*-
"""
ArcMind — Embedding Adapter
==============================
Plugin-style embedding for vector memory.
Supports: Ollama (bge-m3 / nomic-embed-text) / OpenAI / Null.

Performance:
  - 請求級 LRU 快取：同一文字不重複 embed
  - httpx timeout 從 30s 降到 15s（embed 不應太慢）
  - embed_one() 快捷方法：避免 list 包裝開銷
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Protocol, runtime_checkable

logger = logging.getLogger("arcmind.embedding")


@runtime_checkable
class EmbeddingAdapter(Protocol):
    @property
    def dim(self) -> int: ...
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class NullEmbedding:
    """No-op adapter when vector memory is disabled."""
    @property
    def dim(self) -> int:
        return 0
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[] for _ in texts]


# ── Request-Level Embedding Cache ─────────────────────────────────────────────

class _EmbeddingCache:
    """
    LRU 快取：避免同一請求鏈中重複 embed 相同文字。
    每 60 秒自動清除過期條目，最多保留 256 條。
    """
    def __init__(self, max_size: int = 256, ttl: float = 3600.0):
        self._cache: dict[str, tuple[list[float], float]] = {}
        self._lock = threading.Lock()
        self._max_size = max_size
        self._ttl = ttl

    def get(self, text: str) -> list[float] | None:
        with self._lock:
            entry = self._cache.get(text)
            if entry is None:
                return None
            vec, ts = entry
            if (time.monotonic() - ts) > self._ttl:
                del self._cache[text]
                return None
            return vec

    def put(self, text: str, vec: list[float]):
        with self._lock:
            if len(self._cache) >= self._max_size:
                # 清除最舊的 1/4
                items = sorted(self._cache.items(), key=lambda x: x[1][1])
                for k, _ in items[:self._max_size // 4]:
                    del self._cache[k]
            self._cache[text] = (vec, time.monotonic())

    def clear(self):
        with self._lock:
            self._cache.clear()


_embed_cache = _EmbeddingCache()


class OllamaEmbedding:
    """Local Ollama embedding via /api/embed with request-level caching."""

    def __init__(self, base_url: str = "http://localhost:11434",
                 model: str = "nomic-embed-text"):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._dim: int | None = None

    @property
    def dim(self) -> int:
        if self._dim is None:
            self._dim = 768
            try:
                vecs = self.embed(["dim_probe"])
                self._dim = len(vecs[0]) if vecs and vecs[0] else 768
            except Exception:
                self._dim = 768
        return self._dim

    def embed_one(self, text: str) -> list[float]:
        """
        單一文字 embedding 快捷方法（帶快取）。
        多數查詢場景只需 embed 一條意圖文字。
        """
        cached = _embed_cache.get(text)
        if cached:
            return cached

        import httpx
        try:
            resp = httpx.post(
                f"{self._base_url}/api/embed",
                json={"model": self._model, "input": text},
                timeout=15.0,  # embed 單條不應超過 15s
            )
            resp.raise_for_status()
            raw = resp.json(); vec = raw.get("embeddings", [raw.get("embedding", [])]); vec = vec[0] if vec and isinstance(vec[0], list) else vec
            if vec:
                _embed_cache.put(text, vec)
            return vec
        except Exception as e:
            logger.error("[OllamaEmbed] embed_one failed for text '%s...': %s", text[:50], e)
            return []

    def embed(self, texts: list[str]) -> list[list[float]]:
        """批量 embedding（帶快取：跳過已快取的，只 embed 新的）。"""
        import httpx
        results: list[list[float]] = [[] for _ in texts]
        to_embed: list[tuple[int, str]] = []  # (index, text)

        # 1. 從快取中取出已有的
        for i, text in enumerate(texts):
            cached = _embed_cache.get(text)
            if cached:
                results[i] = cached
            else:
                to_embed.append((i, text))

        if not to_embed:
            return results  # 全部命中快取

        cache_hit = len(texts) - len(to_embed)
        if cache_hit > 0:
            logger.debug("[OllamaEmbed] Cache hit: %d/%d texts", cache_hit, len(texts))

        # 2. 真正的批量 embed — 一次 API 呼叫送所有文字
        batch_texts = [t for _, t in to_embed]
        try:
            resp = httpx.post(
                f"{self._base_url}/api/embed",
                json={"model": self._model, "input": batch_texts},
                timeout=30.0,  # 批量可能稍慢，給 30s
            )
            resp.raise_for_status()
            raw = resp.json()
            vecs = raw.get("embeddings", [])
            for (idx, text), vec in zip(to_embed, vecs):
                if isinstance(vec, list) and vec:
                    results[idx] = vec
                    _embed_cache.put(text, vec)
        except Exception as e:
            logger.warning("[OllamaEmbed] batch embed failed, falling back to one-by-one: %s", e)
            # Fallback: 逐一呼叫（相容舊版 Ollama）
            for idx, text in to_embed:
                try:
                    resp = httpx.post(
                        f"{self._base_url}/api/embed",
                        json={"model": self._model, "input": text},
                        timeout=15.0,
                    )
                    resp.raise_for_status()
                    raw = resp.json()
                    vec = raw.get("embeddings", [raw.get("embedding", [])])
                    vec = vec[0] if vec and isinstance(vec[0], list) else vec
                    results[idx] = vec
                    if vec:
                        _embed_cache.put(text, vec)
                except Exception as e2:
                    logger.warning("[OllamaEmbed] single embed failed: %s", e2)

        # A4: 檢查空向量，記錄錯誤摘要
        empty_count = sum(1 for r in results if not r)
        if empty_count > 0:
            logger.error(
                "[OllamaEmbed] %d/%d texts returned empty embedding — "
                "these entries will NOT be searchable in ChromaDB",
                empty_count, len(texts),
            )

        return results


# ── Factory ──────────────────────────────────────────────────────────────────

_cached_adapter: EmbeddingAdapter | None = None


def get_adapter() -> EmbeddingAdapter:
    """Get the configured embedding adapter (singleton)."""
    global _cached_adapter
    if _cached_adapter is not None:
        return _cached_adapter

    try:
        import os
        if os.getenv("ENABLE_VECTOR_MEMORY", "true").lower() in ("true", "1", "yes"):
            base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
            # Strip /v1 suffix for Ollama native API
            base = base.replace("/v1", "")
            model = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
            _cached_adapter = OllamaEmbedding(base_url=base, model=model)
            logger.info("[Embedding] using Ollama: model=%s base=%s", model, base)
        else:
            _cached_adapter = NullEmbedding()
    except Exception as e:
        logger.warning("[Embedding] init failed, using Null: %s", e)
        _cached_adapter = NullEmbedding()

    return _cached_adapter


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    import math
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
