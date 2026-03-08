# -*- coding: utf-8 -*-
"""
ArcMind — Embedding Adapter
==============================
移植自 ARCHILLX v1.1 embedding_adapter.py。
Plugin-style embedding for vector memory.
Supports: Ollama (nomic-embed-text) / OpenAI / Null.
"""
from __future__ import annotations

import logging
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


class OllamaEmbedding:
    """Local Ollama embedding via /api/embeddings."""

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

    def embed(self, texts: list[str]) -> list[list[float]]:
        import httpx
        results: list[list[float]] = []
        for text in texts:
            try:
                resp = httpx.post(
                    f"{self._base_url}/api/embeddings",
                    json={"model": self._model, "prompt": text},
                    timeout=30.0,
                )
                resp.raise_for_status()
                vec = resp.json().get("embedding", [])
                results.append(vec)
            except Exception as e:
                logger.warning("[OllamaEmbed] failed: %s", e)
                results.append([])
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
