from src.providers.llm.base import BaseLLMProvider
from src.providers.llm.openai import OpenAIProvider

_REGISTRY: dict[str, type[BaseLLMProvider]] = {
    "openai": OpenAIProvider,
}


def register_llm_provider(name: str, cls: type[BaseLLMProvider]) -> None:
    _REGISTRY[name] = cls


def get_llm_provider(name: str | None = None) -> BaseLLMProvider:
    from src.config.settings import get_settings

    key = name or get_settings().llm_provider
    if key not in _REGISTRY:
        raise ValueError(f"Unknown LLM provider: {key}. Available: {list(_REGISTRY)}")
    return _REGISTRY[key]()


def list_llm_providers() -> list[str]:
    return list(_REGISTRY.keys())
