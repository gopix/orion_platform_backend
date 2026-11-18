"""Pinecone implementation of the vector provider interface.

Talks to Pinecone and maps our models to/from its SDK — nothing else. Pinecone
SDK objects never leak past this class: callers get ``VectorStoreResponse`` and
``VectorSearchResult``. Vendor errors are translated into ``VectorStoreException``
/ ``VectorSearchException``.

A provider instance is bound to one index (``index_name``); ``collection`` on a
request maps to a Pinecone *namespace* within that index.
"""
import time
from typing import Any, List, Optional

from src.core.config import settings
from src.modules.book_forge.ai.foundation.vector_store.exceptions import (
    VectorSearchException,
    VectorStoreException,
)
from src.modules.book_forge.ai.foundation.vector_store.models import (
    VectorSearchRequest,
    VectorSearchResult,
    VectorStoreRequest,
    VectorStoreResponse,
)
from src.modules.book_forge.ai.foundation.vector_store.providers.base_vector_provider import (
    BaseVectorProvider,
)

DEFAULT_INDEX = "bookforge"
DEFAULT_BATCH_SIZE = 100


class PineconeProvider(BaseVectorProvider):
    """Vector provider backed by Pinecone."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        index_name: Optional[str] = None,
        cloud: str = "aws",
        region: str = "us-east-1",
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._api_key = (
            api_key
            or getattr(settings, "pinecone_api_key", None)
        )
        self._index_name = (
            index_name or getattr(settings, "pinecone_index", None) or DEFAULT_INDEX
        )
        self._cloud = cloud
        self._region = region
        self._batch_size = max(1, batch_size)
        self._client = None

    # -- client / index ----------------------------------------------------

    def _get_client(self):
        if self._client is None:
            try:
                from pinecone import Pinecone
            except ImportError as exc:  # pragma: no cover - depends on env
                raise VectorStoreException(
                    "The 'pinecone' package is not installed.",
                    details={"provider": "pinecone"},
                    cause=exc,
                )
            if not self._api_key:
                raise VectorStoreException(
                    "PINECONE_API_KEY is not configured.",
                    details={"provider": "pinecone"},
                )
            self._client = Pinecone(api_key=self._api_key)
        return self._client

    def _get_index(self, name: Optional[str] = None):
        return self._get_client().Index(name or self._index_name)

    # -- index management --------------------------------------------------

    def create_index(
        self, name: str, dimension: int, *, metric: str = "cosine"
    ) -> None:
        client = self._get_client()
        try:
            from pinecone import ServerlessSpec

            client.create_index(
                name=name,
                dimension=dimension,
                metric=metric,
                spec=ServerlessSpec(cloud=self._cloud, region=self._region),
            )
        except Exception as exc:  # noqa: BLE001 - translated to a domain error
            raise VectorStoreException(
                f"Failed to create index '{name}': {exc}",
                details={"provider": "pinecone", "index": name},
                cause=exc,
            )

    def _wait_until_ready(self, name: str, *, timeout: float = 60.0) -> None:
        """Block until a just-created index reports ready (or timeout)."""
        client = self._get_client()
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            try:
                if client.describe_index(name).status.get("ready"):
                    return
            except Exception:  # noqa: BLE001 - index may not be queryable yet
                pass
            time.sleep(1.0)

    def index_exists(self, name: str) -> bool:
        client = self._get_client()
        try:
            indexes = client.list_indexes()
            names = indexes.names() if hasattr(indexes, "names") else list(indexes)
            return name in names
        except Exception as exc:  # noqa: BLE001 - translated to a domain error
            raise VectorStoreException(
                f"Failed to list indexes: {exc}",
                details={"provider": "pinecone"},
                cause=exc,
            )

    # -- write operations --------------------------------------------------

    def upsert_vectors(self, request: VectorStoreRequest) -> VectorStoreResponse:
        namespace = request.collection
        start = time.perf_counter()

        if not request.vectors:
            return VectorStoreResponse(
                success=True, stored_count=0, collection=namespace, latency_ms=0.0
            )

        items = [
            {
                "id": self._vector_id(request, vector),
                "values": vector.embedding,
                "metadata": self._metadata_for(request, vector),
            }
            for vector in request.vectors
        ]

        # Self-provision the index on first use so a fresh environment (or a new
        # index name) doesn't 404 on upsert. Dimension is taken from the vectors.
        if not self.index_exists(self._index_name):
            self.create_index(self._index_name, dimension=len(request.vectors[0].embedding))
            self._wait_until_ready(self._index_name)

        # Replace mode: clear the namespace first so a re-run fully supersedes the
        # previous batch (no orphans left behind when the chunk count changes).
        # The index is guaranteed to exist by now; a missing namespace is a no-op.
        if getattr(request, "replace", False):
            try:
                self.delete_namespace(namespace)
            except Exception:  # noqa: BLE001 - namespace may not exist yet
                pass

        index = self._get_index()
        try:
            for batch in self._batched(items, self._batch_size):
                index.upsert(vectors=batch, namespace=namespace)
        except Exception as exc:  # noqa: BLE001 - translated to a domain error
            raise VectorStoreException(
                f"Failed to upsert vectors: {exc}",
                details={"provider": "pinecone", "collection": namespace},
                cause=exc,
            )

        latency_ms = (time.perf_counter() - start) * 1000
        return VectorStoreResponse(
            success=True,
            stored_count=len(items),
            collection=namespace,
            latency_ms=round(latency_ms, 2),
        )

    def delete_vectors(
        self, ids: List[str], *, namespace: Optional[str] = None
    ) -> None:
        if not ids:
            return
        index = self._get_index()
        try:
            index.delete(ids=ids, namespace=namespace)
        except Exception as exc:  # noqa: BLE001 - translated to a domain error
            raise VectorStoreException(
                f"Failed to delete vectors: {exc}",
                details={"provider": "pinecone", "collection": namespace},
                cause=exc,
            )

    def delete_namespace(self, namespace: str) -> None:
        index = self._get_index()
        try:
            index.delete(delete_all=True, namespace=namespace)
        except Exception as exc:  # noqa: BLE001 - translated to a domain error
            raise VectorStoreException(
                f"Failed to delete namespace '{namespace}': {exc}",
                details={"provider": "pinecone", "collection": namespace},
                cause=exc,
            )

    # -- read operations ---------------------------------------------------

    def query_vectors(
        self, request: VectorSearchRequest
    ) -> List[VectorSearchResult]:
        index = self._get_index()
        try:
            raw = index.query(
                vector=request.query_vector,
                top_k=request.top_k,
                namespace=request.collection,
                filter=request.filters or None,
                include_metadata=True,
            )
        except Exception as exc:  # noqa: BLE001 - translated to a domain error
            raise VectorSearchException(
                f"Vector search failed: {exc}",
                details={"provider": "pinecone", "collection": request.collection},
                cause=exc,
            )

        matches = self._get(raw, "matches", []) or []
        results: List[VectorSearchResult] = []
        for match in matches:
            score = self._get(match, "score", 0.0)
            if request.threshold is not None and score < request.threshold:
                continue
            metadata = self._get(match, "metadata", {}) or {}
            results.append(
                VectorSearchResult(
                    chunk_id=metadata.get("chunk_id"),
                    text=metadata.get("text"),
                    score=score,
                    metadata=dict(metadata),
                )
            )
        return results

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _batched(items: List[Any], size: int):
        for start in range(0, len(items), size):
            yield items[start : start + size]

    @staticmethod
    def _get(obj: Any, key: str, default: Any = None) -> Any:
        """Access ``key`` whether ``obj`` is a dict or an SDK response object."""
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)
