"""EmbeddingValidationException — the incoming request is invalid.

Raised by the service when the provider is valid and the service works, but the
*request* is wrong: no chunks to embed, a missing model, and so on. A different
problem from an unresolvable provider, hence a distinct type. Parallel to the
chunking module's ``ChunkValidationException``.
"""
from typing import Any, Dict, Optional

from src.modules.book_forge.ai.foundation.embeddings.exceptions.embedding_exception import (
    EmbeddingException,
)


class EmbeddingValidationException(EmbeddingException):
    """Raised when an ``EmbeddingRequest`` is invalid."""

    default_error_code = "EMB-003"
    default_message = "Invalid embedding request"

    def __init__(
        self,
        message: Optional[str] = None,
        *,
        field: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        # Fold a convenient ``field`` argument into details.
        merged: Dict[str, Any] = dict(details or {})
        if field is not None:
            merged.setdefault("field", field)
        super().__init__(
            message,
            details=merged or None,
            cause=cause,
        )
