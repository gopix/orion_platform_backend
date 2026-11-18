"""Chunking orchestration service.

The single entry point the rest of the application uses to chunk a document.
Callers depend on ``ChunkingService`` (or the shared ``chunking_service``
singleton) and never touch a strategy directly.

Deliberately, this service does **not** know *how* chunking happens. Its job is
orchestration only:

    receive request -> validate -> get strategy from factory -> execute
    -> calculate statistics -> return result

Where the chunk boundaries fall is entirely the strategy's business; the service
just runs the selected strategy and aggregates the outcome. Adding a new strategy
never changes this class.
"""
import time
from typing import Optional

from src.core.logger import get_logger
from src.modules.book_forge.ai.foundation.chunking.exceptions import ChunkValidationException
from src.modules.book_forge.ai.foundation.chunking.factory import ChunkStrategyFactory
from src.modules.book_forge.ai.foundation.chunking.models import ChunkRequest, ChunkResult
from src.modules.book_forge.ai.foundation.chunking.utils import ChunkStatisticsCalculator

logger = get_logger(__name__)


class ChunkingService:
    """Orchestrates a chunking request across interchangeable strategies.

    Strategy *creation* is delegated to ``ChunkStrategyFactory`` and the actual
    splitting to the strategy itself. This class only validates the request,
    selects and runs the strategy, computes statistics over the produced chunks,
    and returns a ``ChunkResult``.
    """

    def chunk(self, request: ChunkRequest) -> ChunkResult:
        """Chunk ``request.document`` using the strategy named on the request."""
        self._validate(request)
        strategy = ChunkStrategyFactory.get_strategy(request.strategy)

        start = time.perf_counter()
        result: Optional[ChunkResult] = None
        error: Optional[BaseException] = None
        try:
            result = strategy.chunk(request)
            # Statistics are not computed here — delegated to the dedicated
            # calculator so this service stays orchestration-only and every
            # result is summarised the same way regardless of strategy.
            result.statistics = ChunkStatisticsCalculator.calculate(result.chunks)
            return result
        except BaseException as exc:  # noqa: BLE001 - re-raised after logging
            error = exc
            raise
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            self._log_call(request, result, duration_ms, error)

    # -- validation --------------------------------------------------------

    def _validate(self, request: ChunkRequest) -> None:
        """Validate the *request itself* (not the strategy).

        Strategy resolution — and the ``InvalidChunkStrategyException`` it may
        raise — is the factory's job. Here we only reject requests whose data
        makes chunking impossible, raising ``ChunkValidationException``.
        """
        if not isinstance(request, ChunkRequest):
            raise ChunkValidationException(
                f"Expected a ChunkRequest, got {type(request).__name__}.",
                field="request",
            )
        if not request.document or not request.document.strip():
            raise ChunkValidationException(
                "Document is empty; nothing to chunk.", field="document"
            )

        self._validate_configuration(request)

    def _validate_configuration(self, request: ChunkRequest) -> None:
        """Reject impossible tuning parameters."""
        config = request.configuration

        if config.chunk_size < 1:
            raise ChunkValidationException(
                f"chunk_size must be >= 1, got {config.chunk_size}.",
                field="chunk_size",
            )
        if config.overlap >= config.chunk_size:
            raise ChunkValidationException(
                f"overlap ({config.overlap}) must be smaller than chunk_size "
                f"({config.chunk_size}).",
                field="overlap",
            )
        if (
            config.min_chunk_size is not None
            and config.max_chunk_size is not None
            and config.min_chunk_size > config.max_chunk_size
        ):
            raise ChunkValidationException(
                f"min_chunk_size ({config.min_chunk_size}) cannot exceed "
                f"max_chunk_size ({config.max_chunk_size}).",
                field="min_chunk_size",
            )

    # -- logging -----------------------------------------------------------

    def _log_call(
        self,
        request: ChunkRequest,
        result: Optional[ChunkResult],
        duration_ms: float,
        error: Optional[BaseException],
    ) -> None:
        """Emit one structured log line per chunking call."""
        success = error is None
        stats = result.statistics if result is not None else None
        chunk_count = stats.total_chunks if stats is not None else 0
        total_tokens = stats.total_tokens if stats is not None else None
        warning_count = len(result.warnings) if result is not None else 0

        log = logger.info if success else logger.error
        log(
            "Chunking call | strategy=%s | project_id=%s document_id=%s | "
            "chunks=%s total_tokens=%s warnings=%s | duration_ms=%.1f | "
            "success=%s%s",
            request.strategy.value,
            request.project_id,
            request.document_id,
            chunk_count,
            total_tokens if total_tokens is not None else "n/a",
            warning_count,
            duration_ms,
            success,
            f" | error={type(error).__name__}: {error}" if error else "",
        )


# Shared singleton — import this from other modules.
chunking_service = ChunkingService()
