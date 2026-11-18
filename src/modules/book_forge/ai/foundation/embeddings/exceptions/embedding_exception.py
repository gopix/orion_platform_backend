"""EmbeddingException — base exception for the entire embeddings module.

    Exception
        │
        ▼
    EmbeddingException              (catch the whole family here)
        │
   ┌────┴────────────────────────┐
   ▼                             ▼
InvalidEmbeddingProviderException   EmbeddingValidationException

Exactly parallel to the chunking module's ``ChunkingException``. Callers can catch
everything with a single ``except EmbeddingException`` and only reach for a
subtype when they care about the difference. Typical direct uses: an unexpected
provider/API failure or an internal processing error.
"""
from typing import Any, Dict, Optional


class EmbeddingException(Exception):
    """Base class for every error raised by the embeddings module.

    Attributes
    ----------
    message: human-readable description.
    error_code: stable, greppable code (e.g. ``EMB-001``).
    details: optional structured context for logging/debugging.
    cause: the underlying exception this one wraps, if any.
    """

    #: Default code; subclasses override with their own.
    default_error_code: str = "EMB-001"
    #: Default message when none is supplied.
    default_message: str = "Unknown embedding error"

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
