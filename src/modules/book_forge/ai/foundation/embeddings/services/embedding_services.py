"""Embedding orchestration service.

The single entry point the rest of the application uses to embed chunks. Callers
depend on ``EmbeddingService`` (or the shared ``embedding_service`` singleton) and
never instantiate a provider directly.

Same shape as ``LLMService``:

    EmbeddingRequest -> validate -> provider factory -> provider -> EmbeddingResponse

The service owns orchestration only — validation, provider selection and caching,
usage enrichment, statistics, and logging. It does not know *how* a provider
talks to its API.
"""
import time
from typing import Dict, Optional

from src.core.config import settings
from src.core.logger import get_logger
from src.modules.book_forge.ai.foundation.embeddings.exceptions import (
    EmbeddingValidationException,
)
from src.modules.book_forge.ai.foundation.embeddings.factory import (
    DEFAULT_PROVIDER,
    EmbeddingProviderFactory,
)
from src.modules.book_forge.ai.foundation.embeddings.models import (
    EmbeddingRequest,
    EmbeddingResponse,
)
from src.modules.book_forge.ai.foundation.embeddings.providers import BaseEmbeddingProvider
from src.modules.book_forge.ai.foundation.embeddings.utils import EmbeddingStatisticsCalculator

logger = get_logger(__name__)


class EmbeddingService:
    """Orchestrates embedding requests across configurable providers.

    Provider *creation* is delegated to ``EmbeddingProviderFactory``; this class
    handles orchestration: request validation, default provider selection,
    instance caching, usage enrichment, statistics, and logging.
    """

    def __init__(self, default_provider: Optional[str] = None) -> None:
        self._default_provider: str = (
            default_provider
            or getattr(settings, "embedding_provider", None)
            or DEFAULT_PROVIDER
        )
        # Cache of instantiated providers, keyed by name.
        self._instances: Dict[str, BaseEmbeddingProvider] = {}

    def _resolve_key(self, provider: Optional[str]) -> str:
        return (provider or self._default_provider).lower()

    def get_provider(self, provider: Optional[str] = None) -> BaseEmbeddingProvider:
        """Resolve the provider, building it via the factory on first use."""
        key = self._resolve_key(provider)
        if key not in self._instances:
            logger.info("Instantiating embedding provider '%s'", key)
            self._instances[key] = EmbeddingProviderFactory.create(key)
        return self._instances[key]

    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """Validate, route to the selected provider, and return the response."""
        self._validate(request)
        key = self._resolve_key(request.provider)
        provider = self.get_provider(key)

        start = time.perf_counter()
        response: Optional[EmbeddingResponse] = None
        error: Optional[BaseException] = None
        try:
            response = provider.generate_embeddings(request)
            duration_ms = (time.perf_counter() - start) * 1000
            # Enrich usage first (sets latency), then delegate statistics to the
            # dedicated calculator — neither provider nor service computes them.
            self._enrich_usage(response, key, request.model, duration_ms)
            response.statistics = EmbeddingStatisticsCalculator.calculate(
                response.vectors, response.usage
            )
            return response
        except BaseException as exc:  # noqa: BLE001 - re-raised after logging
            error = exc
            raise
        finally:
            total_ms = (time.perf_counter() - start) * 1000
            self._log_call(request, response, key, total_ms, error)

    # -- validation --------------------------------------------------------

    def _validate(self, request: EmbeddingRequest) -> None:
        """Reject requests that can't be embedded."""
        if not isinstance(request, EmbeddingRequest):
            raise EmbeddingValidationException(
                f"Expected an EmbeddingRequest, got {type(request).__name__}.",
                field="request",
            )
        if not request.chunks:
            raise EmbeddingValidationException(
                "No chunks to embed.", field="chunks"
            )
        if not request.model or not request.model.strip():
            raise EmbeddingValidationException(
                "An embedding model must be specified.", field="model"
            )

    # -- enrichment --------------------------------------------------------

    def _enrich_usage(
        self,
        response: EmbeddingResponse,
        provider: str,
        model: str,
        duration_ms: float,
    ) -> None:
        """Fill in the observability fields on ``response.usage`` in place."""
        usage = response.usage
        usage.provider = usage.provider or provider
        usage.model = usage.model or model
        usage.latency_ms = duration_ms

    # -- logging -----------------------------------------------------------

    def _log_call(
        self,
        request: EmbeddingRequest,
        response: Optional[EmbeddingResponse],
        provider: str,
        duration_ms: float,
        error: Optional[BaseException],
    ) -> None:
        """Emit one structured log line per embedding call."""
        success = error is None
        vector_count = len(response.vectors) if response is not None else 0
        total_tokens = (
            response.usage.total_tokens if response is not None else None
        )

        log = logger.info if success else logger.error
        log(
            "Embedding call | provider=%s model=%s | request_id=%s project_id=%s "
            "document_id=%s | chunks=%s vectors=%s tokens=%s | duration_ms=%.1f | "
            "success=%s%s",
            provider,
            request.model,
            request.request_id,
            request.project_id,
            request.document_id,
            len(request.chunks),
            vector_count,
            total_tokens if total_tokens is not None else "n/a",
            duration_ms,
            success,
            f" | error={type(error).__name__}: {error}" if error else "",
        )


# Shared singleton — import this from other modules.
embedding_service = EmbeddingService()
