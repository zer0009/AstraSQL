from __future__ import annotations

import time
from typing import Any

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from src.config.settings import get_settings
from src.observability.usage import get_active_tracker, make_usage_callbacks
from src.providers.llm.base import BaseLLMProvider


def _is_reasoning_model(model: str) -> bool:
    name = (model or "").strip().lower()
    return name.startswith("gpt-5") or "luna" in name or "terra" in name or "sol" in name


class _TrackingEmbeddings(Embeddings):
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


class OpenAIProvider(BaseLLMProvider):
    """LLM provider backed by OpenAI via langchain-openai."""

    def get_chat_model(
        self,
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        model: str | None = None,
    ) -> BaseChatModel:
        settings = get_settings()
        resolved = (model or "").strip() or settings.openai_model
        kwargs: dict[str, Any] = {
            "api_key": settings.openai_api_key,
            "model": resolved,
            "max_tokens": max_tokens,
        }
        callbacks = make_usage_callbacks()
        if callbacks:
            kwargs["callbacks"] = callbacks

        if _is_reasoning_model(resolved):
            # GPT-5 family: prefer max_completion_tokens alias (already on
            # max_tokens) and omit temperature unless explicitly allowed.
            # Reasoning effort from settings when set.
            effort = (settings.llm_reasoning_effort or "").strip().lower()
            if effort:
                kwargs["reasoning_effort"] = effort
        else:
            kwargs["temperature"] = temperature

        return ChatOpenAI(**kwargs)

    def get_embedding_model(self) -> Embeddings:
        settings = get_settings()
        inner = OpenAIEmbeddings(
            api_key=settings.openai_api_key,
            model=settings.openai_embedding_model,
        )
        if get_active_tracker() is None:
            return inner
        return _TrackingEmbeddings(inner, settings.openai_embedding_model)
