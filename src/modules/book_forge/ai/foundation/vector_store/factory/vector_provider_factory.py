"""Factory responsible for constructing vector database providers.

Owns the provider registry and builds a concrete provider from a name selector,
keeping provider *creation* out of the service — exactly like the LLM and
embeddings factories. Adding another backend later means registering it here; the
service is untouched.
"""
from typing import Dict, List, Type

from src.modules.book_forge.ai.foundation.vector_store.exceptions import (
    InvalidVectorProviderException,
)
from src.modules.book_forge.ai.foundation.vector_store.providers import (
    BaseVectorProvider,
    PineconeProvider,
)

# The default provider used when none is specified.
DEFAULT_PROVIDER = "pinecone"


class VectorProviderFactory:
    """Builds vector provider instances from a name selector."""

    _REGISTRY: Dict[str, Type[BaseVectorProvider]] = {
        "pinecone": PineconeProvider,
    }

    @classmethod
    def create(cls, provider: str) -> BaseVectorProvider:
        """Instantiate the provider registered under ``provider`` (case-insensitive)."""
        key = str(provider).lower()
        provider_cls = cls._REGISTRY.get(key)
        if provider_cls is None:
            raise InvalidVectorProviderException(provider, supported=cls.available())
        return provider_cls()

    @classmethod
    def register(cls, provider: str, provider_cls: Type[BaseVectorProvider]) -> None:
        """Register or override the implementation for a provider name."""
        cls._REGISTRY[str(provider).lower()] = provider_cls

    @classmethod
    def available(cls) -> List[str]:
        """Return the provider names this factory can build."""
        return list(cls._REGISTRY)
