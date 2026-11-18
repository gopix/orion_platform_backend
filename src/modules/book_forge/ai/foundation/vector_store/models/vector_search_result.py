"""VectorSearchResult — one match returned by a similarity search.

Pairs a matched chunk with its similarity score and metadata. A search returns a
ranked list of these; each is what RAG feeds back to the LLM as context. Data
model only — no behaviour.
"""
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class VectorSearchResult(BaseModel):
    # The matched chunk.
    chunk_id: Optional[int] = None
    chunk_index: Optional[int] = None
    text: Optional[str] = None

    # How close the match is (higher = more similar).
    score: float

    # Locating/context metadata stored alongside the vector.
    metadata: Dict[str, Any] = Field(default_factory=dict)
