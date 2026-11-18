"""EmbeddingRequest — everything required to generate embeddings.

Notably, this consumes ``Chunk`` objects, not raw strings: the chunking module
has already decided *what* to embed and carries the locating metadata, so the
embeddings layer just receives those chunks. New parameters go into
``configuration``-style fields or ``metadata`` without changing the signature.
Data model only — no behaviour.

``provider`` is a selector string (e.g. "openai") resolved to a concrete provider
by the embeddings factory/service later, mirroring how the LLM layer selects a
provider.
"""
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from src.modules.book_forge.ai.foundation.chunking.models.chunk import Chunk


class EmbeddingRequest(BaseModel):
    # The chunks to embed (output of the chunking layer).
    chunks: List[Chunk]
    # Which embedding model to use.
    model: str
    # Which provider to route to; resolved by the service/factory.
    provider: Optional[str] = None

    # --- Traceability / ownership --- #
    request_id: str = Field(default_factory=lambda: uuid4().hex)
    project_id: Optional[int] = None
    document_id: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
