"""Embedding wrappers shared across LLM providers."""

from __future__ import annotations

import time

from langchain_core.embeddings import Embeddings

from src.observability.usage import get_active_tracker


class TrackingEmbeddings(Embeddings):
    """Wrap embeddings to record token usage when a UsageTracker is active."""

    def __init__(self, inner: Embeddings, model: str) -> None:
        self._inner = inner
        self._model = model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        started = time.perf_counter()
        result = self._inner.embed_documents(texts)
        self._record(texts, started)
        return result

    def embed_query(self, text: str) -> list[float]:
        started = time.perf_counter()
        result = self._inner.embed_query(text)
        self._record([text], started)
        return result

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        started = time.perf_counter()
        if hasattr(self._inner, "aembed_documents"):
            result = await self._inner.aembed_documents(texts)
        else:
            result = self._inner.embed_documents(texts)
        self._record(texts, started)
        return result

    async def aembed_query(self, text: str) -> list[float]:
        started = time.perf_counter()
        if hasattr(self._inner, "aembed_query"):
            result = await self._inner.aembed_query(text)
        else:
            result = self._inner.embed_query(text)
        self._record([text], started)
        return result

    def _record(self, texts: list[str], started: float) -> None:
        tracker = get_active_tracker()
        if tracker is None:
            return
        # Rough estimate: ~4 chars/token when the API does not return usage.
        chars = sum(len(t or "") for t in texts)
        tokens = max(1, chars // 4)
        latency_ms = int((time.perf_counter() - started) * 1000)
        tracker.record_embedding(
            model=self._model,
            tokens=tokens,
            latency_ms=latency_ms,
            estimated=True,
            label="embedding",
        )
