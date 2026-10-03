"""Prove LLM provider registry abstraction with a fake provider."""

from __future__ import annotations

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel

from src.providers.llm.base import BaseLLMProvider
from src.providers.llm.registry import (
    get_llm_provider,
    list_llm_providers,
    register_llm_provider,
)


class _FakeChat(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise NotImplementedError

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        raise NotImplementedError


class _FakeEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [0.0]


class FakeLLMProvider(BaseLLMProvider):
    @property
    def default_model(self) -> str:
        return "fake-model"

    def get_chat_model(
        self,
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        model: str | None = None,
    ) -> BaseChatModel:
        return _FakeChat()

    def get_embedding_model(self) -> Embeddings:
        return _FakeEmbeddings()


def test_register_and_get_fake_llm_provider():
    name = "fake_test_provider"
    register_llm_provider(name, FakeLLMProvider)
    assert name in list_llm_providers()
    provider = get_llm_provider(name)
    assert isinstance(provider, FakeLLMProvider)
    assert provider.default_model == "fake-model"
    assert isinstance(provider.get_embedding_model(), _FakeEmbeddings)
