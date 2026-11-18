"""ChunkRequest — everything required to perform a chunking operation.

Rather than passing loose arguments (document, strategy, size, overlap, ...), a
single request object is passed around. New parameters a strategy may need later
go into ``configuration`` (or as new optional fields) without changing the API.
Data model only — no behaviour.
"""
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from src.modules.book_forge.ai.foundation.chunking.models.chunk_configuration import (
    ChunkConfiguration,
)


class ChunkStrategy(str, Enum):
    """How a document should be split into chunks."""

    FIXED = "fixed"          # fixed-size windows
    PARAGRAPH = "paragraph"  # one chunk per paragraph
    RECURSIVE = "recursive"  # recursive character/paragraph splitting
    SENTENCE = "sentence"    # sentence-boundary splitting
    HEADING = "heading"      # split on document headings/sections
    SEMANTIC = "semantic"    # embedding/semantic-similarity splitting

    @classmethod
    def coerce(cls, value) -> "ChunkStrategy":
        """Return a ``ChunkStrategy`` from an enum member or a string.

        Raises ``ValueError`` with the list of valid options on a bad value.
        """
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).lower())
        except ValueError:
            available = ", ".join(member.value for member in cls)
            raise ValueError(
                f"Unknown chunk strategy '{value}'. Available strategies: {available}."
            )


class ChunkRequest(BaseModel):
    # The document content to be chunked.
    document: str
    # Which strategy to apply. Heading-based is the default: BookForge documents
    # are structured (chapters/sections), so splitting on headings best preserves
    # their semantics.
    strategy: ChunkStrategy = ChunkStrategy.HEADING
    # Tuning parameters (size, overlap, preservation flags, ...).
    configuration: ChunkConfiguration = Field(default_factory=ChunkConfiguration)

    # Optional context — room to grow without changing the signature.
    language: Optional[str] = None
    project_id: Optional[int] = None
    document_id: Optional[int] = None
