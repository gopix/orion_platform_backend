"""ChunkMetadata — metadata about a chunk, kept separate from the Chunk itself.

Metadata tends to grow over time. Keeping it in its own model means new fields
(e.g. reading_time, embedding_model, chunk_strategy) can be added here without
touching ``Chunk``. Data model only — no behaviour.
"""
from typing import Optional

from pydantic import BaseModel


class ChunkMetadata(BaseModel):
    page_number: Optional[int] = None
    heading_level: Optional[int] = None
    language: Optional[str] = None
    word_count: Optional[int] = None
    character_count: Optional[int] = None
    estimated_tokens: Optional[int] = None
    document_type: Optional[str] = None
    source_type: Optional[str] = None
    confidence: Optional[float] = None

    model_config = {"from_attributes": True}
