"""Factory responsible for constructing LLM providers.

Owns the provider registry and knows how to build a concrete provider from an
``LLMProvider`` selector. This keeps provider *creation* separate from the
*orchestration* concerns (default selection, caching, logging) handled by
``LLMService``.
"""
from typing import Dict, List, Type, Union

from src.modules.book_forge.ai.foundation.llm.providers import (
    AnthropicProvider,
    BaseLLMProvider,
    GeminiProvider,
    LLMProvider,
    OllamaProvider,
    OpenAIProvider,
)


class LLMProviderFactory:
    """Builds provider instances from an ``LLMProvider`` selector."""

    _REGISTRY: Dict[LLMProvider, Type[BaseLLMProvider]] = {
        LLMProvider.ANTHROPIC: AnthropicProvider,
        LLMProvider.OPENAI: OpenAIProvider,
        LLMProvider.GEMINI: GeminiProvider,
        LLMProvider.OLLAMA: OllamaProvider,
    }

    @classmethod
    def create(cls, provider: Union[LLMProvider, str]) -> BaseLLMProvider:
        """Instantiate the provider for ``provider`` (enum or string)."""
        key = LLMProvider.coerce(provider)
        provider_cls = cls._REGISTRY.get(key)
        if provider_cls is None:
            available = ", ".join(member.value for member in cls._REGISTRY)
            raise ValueError(
                f"No implementation registered for provider '{key.value}'. "
                f"Available: {available}."
            )
        return provider_cls()

    @classmethod
    def register(
        cls, provider: Union[LLMProvider, str], provider_cls: Type[BaseLLMProvider]
    ) -> None:
        """Register or override the implementation for a provider."""
        cls._REGISTRY[LLMProvider.coerce(provider)] = provider_cls

    @classmethod
    def available(cls) -> List[LLMProvider]:
        """Return the providers this factory can build."""
        return list(cls._REGISTRY)
