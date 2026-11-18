"""VectorSearchRequest — everything needed for a similarity search.

The backbone of RAG retrieval: a query vector plus how many neighbours to return,
optional metadata filters (e.g. project/document/heading), and an optional
similarity threshold below which matches are discarded. Data model only — no
behaviour.
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class VectorSearchRequest(BaseModel):
    # The embedding to search for nearest neighbours of.
    query_vector: List[float]
    # Number of nearest neighbours to return.
    top_k: int = Field(5, ge=1)
    # Metadata equality filters applied before/with the search.
    filters: Dict[str, Any] = Field(default_factory=dict)
    # Minimum similarity score; matches below this are dropped when set.
    threshold: Optional[float] = None

    # Optional collection/namespace to search; resolved by the store layer if unset.
    collection: Optional[str] = None
