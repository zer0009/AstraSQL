from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from src.config.settings import get_settings
from src.providers.llm.base import BaseLLMProvider


class OpenAIProvider(BaseLLMProvider):
    """LLM provider backed by OpenAI via langchain-openai."""

    def get_chat_model(
        self, *, temperature: float = 0.0, max_tokens: int = 4096
    ) -> BaseChatModel:
        settings = get_settings()
        return ChatOpenAI(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def get_embedding_model(self) -> Embeddings:
        settings = get_settings()
        return OpenAIEmbeddings(
            api_key=settings.openai_api_key,
            model=settings.openai_embedding_model,
        )
