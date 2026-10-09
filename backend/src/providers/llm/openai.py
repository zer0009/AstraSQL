from __future__ import annotations

from threading import Lock
from typing import Any

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from src.config.settings import get_settings
from src.observability.usage import get_active_tracker, make_usage_callbacks
from src.providers.llm.base import BaseLLMProvider
from src.providers.llm.embeddings import TrackingEmbeddings

# Process-level chat client cache keyed by (model, max_tokens, effort, temperature).
_CHAT_CACHE: dict[tuple[Any, ...], BaseChatModel] = {}
_CHAT_LOCK = Lock()


def _is_reasoning_model(model: str) -> bool:
    name = (model or "").strip().lower()
    return (
        name.startswith("gpt-5")
        or "luna" in name
        or "terra" in name
        or "sol" in name
    )


class OpenAIProvider(BaseLLMProvider):
    """LLM provider backed by OpenAI via langchain-openai."""

    @property
    def default_model(self) -> str:
        return get_settings().llm_model

    def get_chat_model(
        self,
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> BaseChatModel:
        settings = get_settings()
        resolved = (model or "").strip() or self.default_model
        effort = (
            (reasoning_effort if reasoning_effort is not None else "")
            or (settings.llm_reasoning_effort or "")
        ).strip().lower()
        # Older configs / docs used "minimal"; current models accept none|low|…|xhigh.
        if effort in {"minimal", "off"}:
            effort = "none"
        if effort in {"", "default"}:
            effort = ""

        cache_key = (
            resolved,
            int(max_tokens),
            effort,
            float(temperature) if not _is_reasoning_model(resolved) else 0.0,
            # Callbacks depend on active tracker — do not cache when tracking.
            get_active_tracker() is not None,
        )
        if get_active_tracker() is None:
            with _CHAT_LOCK:
                cached = _CHAT_CACHE.get(cache_key)
                if cached is not None:
                    return cached

        kwargs: dict[str, Any] = {
            "api_key": settings.llm_api_key,
            "model": resolved,
            "max_tokens": max_tokens,
        }
        callbacks = make_usage_callbacks()
        if callbacks:
            kwargs["callbacks"] = callbacks

        if _is_reasoning_model(resolved):
            # GPT-5 family: omit temperature; apply reasoning effort when set.
            # Pass "none" explicitly so cheap stages do not inherit a higher default.
            if effort:
                kwargs["reasoning_effort"] = effort
        else:
            kwargs["temperature"] = temperature

        chat = ChatOpenAI(**kwargs)
        if get_active_tracker() is None:
            with _CHAT_LOCK:
                _CHAT_CACHE[cache_key] = chat
        return chat

    def get_embedding_model(self) -> Embeddings:
        settings = get_settings()
        # langchain-openai stubs expect SecretStr | None; str is accepted at runtime.
        inner = OpenAIEmbeddings(
            api_key=settings.llm_api_key or None,  # type: ignore[arg-type]
            model=settings.embedding_model,
        )
        if get_active_tracker() is None:
            return inner
        return TrackingEmbeddings(inner, settings.embedding_model)


def clear_chat_cache() -> None:
    """Drop cached ChatOpenAI instances (tests)."""
    with _CHAT_LOCK:
        _CHAT_CACHE.clear()
