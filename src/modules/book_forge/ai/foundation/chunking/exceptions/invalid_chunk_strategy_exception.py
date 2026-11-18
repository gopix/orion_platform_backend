"""InvalidChunkStrategyException — the requested strategy cannot be resolved.

Raised by the factory when ``request.strategy`` maps to no implementation (an
unknown value like ``"AI_MAGIC"``, or a declared-but-unimplemented member). This
is a programming/configuration error — if the strategy doesn't exist the system
cannot continue, so we raise rather than silently returning ``None``. The message
lists the supported strategies to make debugging easy.
"""
from typing import Any, Iterable, Optional

from src.modules.book_forge.ai.foundation.chunking.exceptions.chunking_exception import (
    ChunkingException,
)


class InvalidChunkStrategyException(ChunkingException):
    """Raised when the requested chunking strategy cannot be resolved."""

    default_error_code = "CHUNK-002"
    default_message = "Unsupported chunk strategy"

    def __init__(
        self,
        strategy: Any,
        supported: Optional[Iterable[Any]] = None,
        *,
        cause: Optional[BaseException] = None,
    ) -> None:
        self.strategy = strategy
        self.supported = [str(s) for s in supported] if supported is not None else []

        message = f"Unsupported chunk strategy: {strategy}."
        if self.supported:
            message += f" Supported: {', '.join(self.supported)}."

        super().__init__(
            message,
            details={"strategy": strategy, "supported": self.supported},
            cause=cause,
        )
