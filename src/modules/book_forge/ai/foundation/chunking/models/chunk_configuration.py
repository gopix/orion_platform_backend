"""ChunkConfiguration — all tuning parameters for a chunking operation.

Kept separate from ``ChunkRequest`` (Single Responsibility): the request stays
focused on *what* to chunk, while this holds *how* to chunk. New tuning options
are added here without changing the request. Data model only — no behaviour.
"""
from typing import Optional

from pydantic import BaseModel, Field


class ChunkConfiguration(BaseModel):
    # Target chunk size and overlap (units are strategy-defined, e.g. tokens).
    chunk_size: int = Field(512, ge=1)
    overlap: int = Field(50, ge=0)

    # Optional hard bounds on chunk size.
    min_chunk_size: Optional[int] = Field(None, ge=1)
    max_chunk_size: Optional[int] = Field(None, ge=1)

    # Structural preservation preferences.
    preserve_headings: bool = True
    preserve_tables: bool = True
    preserve_lists: bool = True

    # Merge chunks that fall below ``min_chunk_size`` into their neighbour.
    merge_small_chunks: bool = True
