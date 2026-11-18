"""Abstract interface every vector database provider implements.

A provider exposes only *business operations* (create an index, upsert vectors,
query, delete) and maps our models to/from a specific vector DB. No vendor SDK
objects ever leak past this boundary — callers speak in ``VectorStoreRequest`` /
``VectorSearchRequest`` and receive ``VectorStoreResponse`` /
``VectorSearchResult``.

    EmbeddingResponse -> VectorStoreRequest -> <Provider> -> Vector DB

Concrete providers (Pinecone today; others later) implement the abstract methods;
the shared helpers here build stable vector ids and consistent metadata payloads
so every provider does it the same way.
"""
from abc import ABC, abstractmethod
from typing import List, Optional

from src.modules.book_forge.ai.foundation.embeddings.models.embedding_vector import (
    EmbeddingVector,
)
from src.modules.book_forge.ai.foundation.vector_store.models import (
    VectorSearchRequest,
    VectorSearchResult,
    VectorStoreRequest,
    VectorStoreResponse,
)
from src.modules.book_forge.ai.foundation.vector_store.utils import MetadataBuilder


class BaseVectorProvider(ABC):
    """Common contract for all vector database providers."""

    @abstractmethod
    def create_index(
        self, name: str, dimension: int, *, metric: str = "cosine"
    ) -> None:
        """Create an index/collection with the given dimensionality and metric."""
        raise NotImplementedError

    @abstractmethod
    def index_exists(self, name: str) -> bool:
        """Return whether an index/collection already exists."""
        raise NotImplementedError

    @abstractmethod
    def upsert_vectors(self, request: VectorStoreRequest) -> VectorStoreResponse:
        """Store (insert or update) the request's vectors."""
        raise NotImplementedError

    @abstractmethod
    def query_vectors(
        self, request: VectorSearchRequest
    ) -> List[VectorSearchResult]:
        """Return the nearest neighbours of the request's query vector."""
        raise NotImplementedError

    @abstractmethod
    def delete_vectors(
        self, ids: List[str], *, namespace: Optional[str] = None
    ) -> None:
        """Delete specific vectors by id."""
        raise NotImplementedError

    @abstractmethod
    def delete_namespace(self, namespace: str) -> None:
        """Delete every vector in a namespace/collection."""
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Shared helpers                                                     #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _vector_id(request: VectorStoreRequest, vector: EmbeddingVector) -> str:
        """Build a stable, collision-free id: ``<project>:<document>:<chunk>``.

        The document comes from the vector itself (falling back to the request),
        because a project-wide upsert batches many documents and ``chunk_index``
        restarts at 0 for each — so the document component is what keeps ids
        unique across documents. Falls back to the chunk index when the chunk has
        no database id yet.
        """
        document_id = (
            vector.document_id if vector.document_id is not None else request.document_id
        )
        chunk_ref = vector.chunk_id if vector.chunk_id is not None else vector.chunk_index
        return f"{request.project_id}:{document_id}:{chunk_ref}"

    @staticmethod
    def _metadata_for(request: VectorStoreRequest, vector: EmbeddingVector) -> dict:
        """Build the consistent metadata payload stored with a vector.

        Carries the vector's document id and source text so the stored record is
        self-describing (attributable and retrievable), not just an embedding.
        """
        document_id = (
            vector.document_id if vector.document_id is not None else request.document_id
        )
        extra = {"text": vector.text} if vector.text else None
        return MetadataBuilder.from_vector(
            vector,
            project_id=request.project_id,
            document_id=document_id,
            extra=extra,
        )
