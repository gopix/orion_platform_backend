"""InvalidVectorProviderException — the requested vector backend can't be resolved.

Raised by the factory when the configured vector-DB provider maps to no
implementation (an unknown name, or one not registered). A programming/
configuration error — the system cannot continue, so we raise rather than
returning ``None``. Parallel to ``InvalidChunkStrategyException`` /
``InvalidEmbeddingProviderException``.
"""
from typing import Any, Iterable, Optional

from src.modules.book_forge.ai.foundation.vector_store.exceptions.vector_store_exception import (
    VectorStoreException,
)


class InvalidVectorProviderException(VectorStoreException):
    """Raised when the requested vector database provider cannot be resolved."""

    default_error_code = "VDB-002"
    default_message = "Unsupported vector provider"

    def __init__(
        self,
        provider: Any,
        supported: Optional[Iterable[Any]] = None,
        *,
        cause: Optional[BaseException] = None,
    ) -> None:
        self.provider = provider
        self.supported = [str(s) for s in supported] if supported is not None else []

        message = f"Unsupported vector provider: {provider}."
        if self.supported:
            message += f" Supported: {', '.join(self.supported)}."

        super().__init__(
            message,
            details={"provider": provider, "supported": self.supported},
            cause=cause,
        )
