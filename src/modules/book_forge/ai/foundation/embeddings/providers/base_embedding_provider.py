"""Abstract interface every embedding provider implements.

A provider knows how to talk to one specific embedding API — nothing else. It
converts an ``EmbeddingRequest`` into a vendor API call and maps the raw result
back into an ``EmbeddingResponse``. It does NOT validate requests, select
providers, compute statistics, normalize vectors, or touch a vector database.

    EmbeddingService
            │
            ▼
    BaseEmbeddingProvider   (this contract)
            │
            ▼
    OpenAIEmbeddingProvider

The shared helpers here are pure plumbing (pulling text out of chunks, assembling
vectors) so concrete providers only implement the vendor call itself.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List

from src.modules.book_forge.ai.foundation.embeddings.models import (
    EmbeddingRequest,
    EmbeddingResponse,
    EmbeddingVector,
)


class BaseEmbeddingProvider(ABC):
    """Common contract for all embedding providers."""

    @abstractmethod
    def generate_embeddings(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """Embed every chunk in ``request`` and return an ``EmbeddingResponse``."""
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Shared helpers                                                     #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _extract_texts(request: EmbeddingRequest) -> List[str]:
        """Pull the raw text out of each chunk, preserving order."""
        return [chunk.text for chunk in request.chunks]

    @staticmethod
    def _build_vectors(
        request: EmbeddingRequest, embeddings: List[List[float]]
    ) -> List[EmbeddingVector]:
        """Pair each chunk with its embedding, carrying locating metadata.

        Assumes ``embeddings`` is aligned 1:1 and in the same order as
        ``request.chunks`` (the provider's responsibility to guarantee).
        """
        vectors: List[EmbeddingVector] = []
        for chunk, embedding in zip(request.chunks, embeddings):
            vectors.append(
                EmbeddingVector(
                    chunk_id=chunk.id,
                    chunk_index=chunk.chunk_index,
                    document_id=chunk.document_id,
                    text=chunk.text,
                    embedding=embedding,
                    metadata=BaseEmbeddingProvider._vector_metadata(chunk),
                )
            )
        return vectors

    @staticmethod
    def _vector_metadata(chunk: Any) -> Dict[str, Any]:
        """Locating context copied from the chunk, useful for the vector DB later."""
        metadata: Dict[str, Any] = {}
        if chunk.heading is not None:
            metadata["heading"] = chunk.heading
        if chunk.section is not None:
            metadata["section"] = chunk.section
        if chunk.page_number is not None:
            metadata["page_number"] = chunk.page_number
        return metadata
