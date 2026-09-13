from abc import ABC, abstractmethod

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel


class BaseLLMProvider(ABC):
    @abstractmethod
    def get_chat_model(
        self,
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        model: str | None = None,
    ) -> BaseChatModel: ...

    @abstractmethod
    def get_embedding_model(self) -> Embeddings: ...
