"""VectorStoreRequest — input for storing embedded vectors.

Carries only what the vector store actually needs: the vectors themselves plus
where they belong (project/document, and optionally a target collection). It
deliberately holds a ``List[EmbeddingVector]`` rather than the full
``EmbeddingResponse`` — the store doesn't care about latency, usage, token
counts, or pricing, so keeping those out keeps the modules decoupled. Data model
only — no behaviour.
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from src.modules.book_forge.ai.foundation.embeddings.models.embedding_vector import (
    EmbeddingVector,
)


class VectorStoreRequest(BaseModel):
    # Ownership — which project/document these vectors belong to.
    project_id: Optional[int] = None
    document_id: Optional[int] = None

    # The vectors to store (just the vectors, not the whole EmbeddingResponse).
    vectors: List[EmbeddingVector]

    # Optional target collection/namespace; resolved by the store layer if unset.
    collection: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # When True, clear the target namespace before upserting so a re-run fully
    # replaces the previous batch. This prevents orphaned vectors when the number
    # of chunks changes between runs (e.g. after tuning chunking settings).
    replace: bool = False
