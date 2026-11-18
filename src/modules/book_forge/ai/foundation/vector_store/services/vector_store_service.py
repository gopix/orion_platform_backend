"""Vector store orchestration service.

The single entry point the rest of the application uses to store and search
vectors. Callers depend on ``VectorStoreService`` (or the shared
``vector_store_service`` singleton) and never instantiate a provider directly.

Same shape as every other module's service:

    request -> validate -> provider (via factory) -> store/search/delete
    -> return response

The service owns orchestration only — validation, provider selection and
caching, and logging. It does not know *how* a provider talks to its backend.
"""
import time
from typing import Dict, List, Optional

from src.core.config import settings
from src.core.logger import get_logger
from src.modules.book_forge.ai.foundation.vector_store.exceptions import (
    VectorSearchException,
    VectorStoreException,
)
from src.modules.book_forge.ai.foundation.vector_store.factory import (
    DEFAULT_PROVIDER,
    VectorProviderFactory,
)
from src.modules.book_forge.ai.foundation.vector_store.models import (
    VectorSearchRequest,
    VectorSearchResult,
    VectorStoreRequest,
    VectorStoreResponse,
)
from src.modules.book_forge.ai.foundation.vector_store.providers import BaseVectorProvider

logger = get_logger(__name__)


class VectorStoreService:
    """Orchestrates store/search/delete across configurable vector providers.

    Provider *creation* is delegated to ``VectorProviderFactory``; this class
    validates requests, selects and caches providers, logs, and returns the
    provider's response.
    """

    def __init__(self, default_provider: Optional[str] = None) -> None:
        self._default_provider: str = (
            default_provider
            or getattr(settings, "vector_provider", None)
            or DEFAULT_PROVIDER
        )
        self._instances: Dict[str, BaseVectorProvider] = {}

    def _resolve_key(self, provider: Optional[str]) -> str:
        return (provider or self._default_provider).lower()

    def get_provider(self, provider: Optional[str] = None) -> BaseVectorProvider:
        """Resolve the provider, building it via the factory on first use."""
        key = self._resolve_key(provider)
        if key not in self._instances:
            logger.info("Instantiating vector provider '%s'", key)
            self._instances[key] = VectorProviderFactory.create(key)
        return self._instances[key]

    # -- operations --------------------------------------------------------

    def store(
        self, request: VectorStoreRequest, provider: Optional[str] = None
    ) -> VectorStoreResponse:
        """Validate and upsert the request's vectors via the selected provider."""
        self._validate_store(request)
        key = self._resolve_key(provider)
        client = self.get_provider(key)

        start = time.perf_counter()
        response: Optional[VectorStoreResponse] = None
        error: Optional[BaseException] = None
        try:
            response = client.upsert_vectors(request)
            return response
        except BaseException as exc:  # noqa: BLE001 - re-raised after logging
            error = exc
            raise
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            self._log(
                "store", key, duration_ms, error,
                extra=f"vectors={len(request.vectors)} collection={request.collection}",
            )

    def search(
        self, request: VectorSearchRequest, provider: Optional[str] = None
    ) -> List[VectorSearchResult]:
        """Validate and run a similarity search via the selected provider."""
        self._validate_search(request)
        key = self._resolve_key(provider)
        client = self.get_provider(key)

        start = time.perf_counter()
        results: Optional[List[VectorSearchResult]] = None
        error: Optional[BaseException] = None
        try:
            results = client.query_vectors(request)
            return results
        except BaseException as exc:  # noqa: BLE001 - re-raised after logging
            error = exc
            raise
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            found = len(results) if results is not None else 0
            self._log(
                "search", key, duration_ms, error,
                extra=f"top_k={request.top_k} results={found} collection={request.collection}",
            )

    def delete(
        self,
        ids: List[str],
        *,
        namespace: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> None:
        """Delete specific vectors by id via the selected provider."""
        if not ids:
            raise VectorStoreException("No vector ids provided to delete.")
        key = self._resolve_key(provider)
        client = self.get_provider(key)

        start = time.perf_counter()
        error: Optional[BaseException] = None
        try:
            client.delete_vectors(ids, namespace=namespace)
        except BaseException as exc:  # noqa: BLE001 - re-raised after logging
            error = exc
            raise
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            self._log(
                "delete", key, duration_ms, error,
                extra=f"ids={len(ids)} namespace={namespace}",
            )

    def delete_namespace(
        self, namespace: str, provider: Optional[str] = None
    ) -> None:
        """Delete every vector in a namespace/collection."""
        if not namespace:
            raise VectorStoreException("A namespace must be provided to delete.")
        key = self._resolve_key(provider)
        client = self.get_provider(key)

        start = time.perf_counter()
        error: Optional[BaseException] = None
        try:
            client.delete_namespace(namespace)
        except BaseException as exc:  # noqa: BLE001 - re-raised after logging
            error = exc
            raise
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            self._log(
                "delete_namespace", key, duration_ms, error,
                extra=f"namespace={namespace}",
            )

    # -- validation --------------------------------------------------------

    def _validate_store(self, request: VectorStoreRequest) -> None:
        if not isinstance(request, VectorStoreRequest):
            raise VectorStoreException(
                f"Expected a VectorStoreRequest, got {type(request).__name__}."
            )
        if not request.vectors:
            raise VectorStoreException("No vectors to store.")

    def _validate_search(self, request: VectorSearchRequest) -> None:
        if not isinstance(request, VectorSearchRequest):
            raise VectorSearchException(
                f"Expected a VectorSearchRequest, got {type(request).__name__}."
            )
        if not request.query_vector:
            raise VectorSearchException("query_vector must not be empty.")

    # -- logging -----------------------------------------------------------

    def _log(
        self,
        operation: str,
        provider: str,
        duration_ms: float,
        error: Optional[BaseException],
        *,
        extra: str = "",
    ) -> None:
        """Emit one structured log line per vector store operation."""
        success = error is None
        log = logger.info if success else logger.error
        log(
            "VectorStore %s | provider=%s | %s | duration_ms=%.1f | success=%s%s",
            operation,
            provider,
            extra,
            duration_ms,
            success,
            f" | error={type(error).__name__}: {error}" if error else "",
        )


# Shared singleton — import this from other modules.
vector_store_service = VectorStoreService()
