from __future__ import annotations

from typing import Any

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from src.config.settings import get_settings
from src.observability.usage import get_active_tracker, make_usage_callbacks
from src.providers.llm.base import BaseLLMProvider
from src.providers.llm.embeddings import TrackingEmbeddings


def _is_reasoning_model(model: str) -> bool:
    name = (model or "").strip().lower()
    return name.startswith("gpt-5") or "luna" in name or "terra" in name or "sol" in name


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
    ) -> BaseChatModel:
        settings = get_settings()
        resolved = (model or "").strip() or self.default_model
        kwargs: dict[str, Any] = {
            "api_key": settings.llm_api_key,
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
        # langchain-openai stubs expect SecretStr | None; str is accepted at runtime.
        inner = OpenAIEmbeddings(
            api_key=settings.llm_api_key or None,  # type: ignore[arg-type]
            model=settings.embedding_model,
        )
        if get_active_tracker() is None:
            return inner
        return TrackingEmbeddings(inner, settings.embedding_model)
