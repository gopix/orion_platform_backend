"""InvalidEmbeddingProviderException — the requested provider cannot be resolved.

Raised by the factory when ``request.provider`` maps to no implementation (an
unknown name, or one not registered). This is a programming/configuration error —
if the provider doesn't exist the system cannot continue, so we raise rather than
silently returning ``None``. The message lists the supported providers to make
debugging easy. Parallel to the chunking module's
``InvalidChunkStrategyException``.
"""
from typing import Any, Iterable, Optional

from src.modules.book_forge.ai.foundation.embeddings.exceptions.embedding_exception import (
    EmbeddingException,
)


class InvalidEmbeddingProviderException(EmbeddingException):
    """Raised when the requested embedding provider cannot be resolved."""

    default_error_code = "EMB-002"
    default_message = "Unsupported embedding provider"

    def __init__(
        self,
        provider: Any,
        supported: Optional[Iterable[Any]] = None,
        *,
        cause: Optional[BaseException] = None,
    ) -> None:
        self.provider = provider
        self.supported = [str(s) for s in supported] if supported is not None else []

        message = f"Unsupported embedding provider: {provider}."
        if self.supported:
            message += f" Supported: {', '.join(self.supported)}."

        super().__init__(
            message,
            details={"provider": provider, "supported": self.supported},
            cause=cause,
        )
