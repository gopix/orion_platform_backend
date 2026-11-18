"""EmbeddingVector — one embedded chunk, the core entity of this module.

Pairs a chunk with the dense vector produced for it::

    Chunk #12  ->  [0.23, -0.14, 0.91, ...]

``dimension`` is derived from the embedding itself so it can never drift out of
sync with the vector's actual length. ``metadata`` carries pass-through context
(e.g. the chunk's heading/section) useful when the vector is later stored in a
vector database. Data model only — no behaviour.
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, computed_field


class EmbeddingVector(BaseModel):
    # Link back to the source chunk (``Chunk.id`` / ordinal position).
    chunk_id: Optional[int] = None
    chunk_index: Optional[int] = None
    # Link back to the source document, so the vector can be attributed and its
    # id kept unique across documents (chunk_index alone resets per document).
    document_id: Optional[int] = None

    # The chunk's source text, carried through so the stored vector is
    # self-describing (retrievable content, not just an opaque embedding).
    text: Optional[str] = None

    # The dense embedding produced for the chunk.
    embedding: List[float]

    # Free-form context carried alongside the vector (heading, section, ...).
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"from_attributes": True}

    @computed_field  # included in model_dump() / JSON output
    @property
    def dimension(self) -> int:
        """The vector's dimensionality, always consistent with ``embedding``."""
        return len(self.embedding)
