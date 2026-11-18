"""VectorStoreException — base exception for the vector database module.

    Exception
        │
        ▼
    VectorStoreException            (catch the whole family here)
        │
   ┌────┴────────────────────────┐
   ▼                             ▼
InvalidVectorProviderException     VectorSearchException

Same shape as the chunking/embeddings bases: every vector-store error derives
from this, so callers can catch everything with a single
``except VectorStoreException``. Raised directly for store/persist failures and
unexpected backend errors; subtypes cover provider resolution and search.
"""
from typing import Any, Dict, Optional


class VectorStoreException(Exception):
    """Base class for every error raised by the vector database module.

    Attributes
    ----------
    message: human-readable description.
    error_code: stable, greppable code (e.g. ``VDB-001``).
    details: optional structured context for logging/debugging.
    cause: the underlying exception this one wraps, if any.
    """

    #: Default code; subclasses override with their own.
    default_error_code: str = "VDB-001"
    #: Default message when none is supplied.
    default_message: str = "Vector store error"

    def __init__(
        self,
        message: Optional[str] = None,
        *,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        self.message = message or self.default_message
        self.error_code = error_code or self.default_error_code
        self.details = details
        self.cause = cause
        super().__init__(self.message)
        # Preserve the exception chain for tracebacks / ``raise ... from``.
        if cause is not None:
            self.__cause__ = cause

    def __str__(self) -> str:
        parts = [f"[{self.error_code}] {self.message}"]
        if self.details:
            rendered = ", ".join(f"{k}={v}" for k, v in self.details.items())
            parts.append(f"({rendered})")
        return " ".join(parts)
