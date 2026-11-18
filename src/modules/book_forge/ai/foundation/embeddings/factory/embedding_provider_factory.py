"""Factory responsible for constructing embedding providers.

Owns the provider registry and builds a concrete provider from a name selector.
Mirrors the LLM module's ``LLMProviderFactory``: it keeps provider *creation* out
of the service, so ``EmbeddingService`` never grows an ``if provider == ...``
ladder and never imports a concrete provider. Adding VoyageAI/Ollama later means
registering them here — the service is untouched.
"""
from typing import Dict, List, Type

from src.modules.book_forge.ai.foundation.embeddings.exceptions import (
    InvalidEmbeddingProviderException,
)
from src.modules.book_forge.ai.foundation.embeddings.providers import (
    BaseEmbeddingProvider,
    OpenAIEmbeddingProvider,
)

# The default provider used when a request/service specifies none.
DEFAULT_PROVIDER = "openai"


class EmbeddingProviderFactory:
    """Builds embedding provider instances from a name selector."""

    _REGISTRY: Dict[str, Type[BaseEmbeddingProvider]] = {
        "openai": OpenAIEmbeddingProvider,
    }

    @classmethod
    def create(cls, provider: str) -> BaseEmbeddingProvider:
        """Instantiate the provider registered under ``provider`` (case-insensitive)."""
        key = str(provider).lower()
        provider_cls = cls._REGISTRY.get(key)
        if provider_cls is None:
            raise InvalidEmbeddingProviderException(
                provider, supported=cls.available()
            )
        return provider_cls()

    @classmethod
    def register(
        cls, provider: str, provider_cls: Type[BaseEmbeddingProvider]
    ) -> None:
        """Register or override the implementation for a provider name."""
        cls._REGISTRY[str(provider).lower()] = provider_cls

    @classmethod
    def available(cls) -> List[str]:
        """Return the provider names this factory can build."""
        return list(cls._REGISTRY)
