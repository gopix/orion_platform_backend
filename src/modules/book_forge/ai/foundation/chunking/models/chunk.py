"""Chunk — one logical chunk extracted from a document.

The core entity of the chunking module (analogous to PromptTemplate in the
Prompt Engine or LLMRequest in the LLM module). It carries the actual content
plus locating metadata. It is a data model only — no embed/split/save/summarize
behaviour lives here.
"""
from typing import Optional

from pydantic import BaseModel, Field

from src.modules.book_forge.ai.foundation.chunking.models.chunk_metadata import ChunkMetadata


class Chunk(BaseModel):
    id: Optional[int] = None
    # Ordinal position of this chunk within its document (0-based).
    chunk_index: int
    # The actual chunk content.
    text: str
    # Locating context within the source document.
    heading: Optional[str] = None
    section: Optional[str] = None
    page_number: Optional[int] = None
    # Ownership links.
    document_id: Optional[int] = None
    project_id: Optional[int] = None
    # Structured metadata (token counts, page info, source type, etc.).
    metadata: ChunkMetadata = Field(default_factory=ChunkMetadata)

    model_config = {"from_attributes": True}
