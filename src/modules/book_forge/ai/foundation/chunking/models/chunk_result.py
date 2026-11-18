"""ChunkResult — the output of the Chunking Engine.

Instead of returning a bare list of chunks, the engine returns a ``ChunkResult``
that bundles the chunks with statistics and warnings, leaving room to grow
without changing callers. Data model only — the engine computes and fills these
fields; the model itself contains no logic.
"""
from typing import List, Optional

from pydantic import BaseModel, Field

from src.modules.book_forge.ai.foundation.chunking.models.chunk import Chunk


class ChunkStatistics(BaseModel):
    total_chunks: int = 0
    total_tokens: Optional[int] = None
    average_tokens: Optional[float] = None
    largest_tokens: Optional[int] = None
    smallest_tokens: Optional[int] = None
    average_characters: Optional[float] = None
    average_words: Optional[float] = None


class ChunkResult(BaseModel):
    chunks: List[Chunk] = Field(default_factory=list)
    statistics: ChunkStatistics = Field(default_factory=ChunkStatistics)
    warnings: List[str] = Field(default_factory=list)
