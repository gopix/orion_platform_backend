"""ChunkValidationException — the incoming request is invalid.

Raised by the service when the strategy is valid and the service works, but the
*request* is wrong: an empty document, ``chunk_size <= 0``, ``overlap >=
chunk_size``, and so on. This is a different problem from an unresolvable
strategy, so it gets its own type — callers can tell "you asked for something
impossible" apart from "that strategy doesn't exist".
"""
from typing import Any, Dict, Optional

from src.modules.book_forge.ai.foundation.chunking.exceptions.chunking_exception import (
    ChunkingException,
)


class ChunkValidationException(ChunkingException):
    """Raised when a ``ChunkRequest`` (or its configuration) is invalid."""

    default_error_code = "CHUNK-003"
    default_message = "Invalid chunk request"

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
