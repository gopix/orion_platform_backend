"""Chunking strategies — one interchangeable implementation per approach.

Every strategy implements :class:`BaseChunkStrategy` and answers exactly one
question: where does the next chunk begin and end? Construction is handled by the
``ChunkStrategyFactory``, so callers never import concrete strategies directly.
"""
from src.modules.book_forge.ai.foundation.chunking.strategies.base_chunk_strategy import (
    BaseChunkStrategy,
)
from src.modules.book_forge.ai.foundation.chunking.strategies.fixed_chunk_strategy import (
    FixedChunkStrategy,
)
from src.modules.book_forge.ai.foundation.chunking.strategies.heading_chunk_strategy import (
    HeadingChunkStrategy,
)
from src.modules.book_forge.ai.foundation.chunking.strategies.paragraph_chunk_strategy import (
    ParagraphChunkStrategy,
)
from src.modules.book_forge.ai.foundation.chunking.strategies.semantic_chunk_strategy import (
    SemanticChunkStrategy,
)

__all__ = [
    "BaseChunkStrategy",
    "FixedChunkStrategy",
    "HeadingChunkStrategy",
    "ParagraphChunkStrategy",
    "SemanticChunkStrategy",
]
