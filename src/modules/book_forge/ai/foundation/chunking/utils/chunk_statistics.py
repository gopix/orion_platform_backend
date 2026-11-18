"""ChunkStatisticsCalculator — derive summary statistics from a set of chunks.

Statistics are a cross-cutting concern, not a service or strategy one. Pulling
the calculation here keeps ``ChunkingService`` clean (it just calls this) and
lets every strategy's output be summarised the same way.

It reports: total chunks, total/average tokens, largest and smallest chunk (by
tokens), and average characters and words per chunk. Token counts are read from
each chunk's metadata when present and fall back to ``TokenEstimator`` otherwise,
so the numbers are always populated. Stateless and pure: no I/O, no
configuration.
"""
from typing import List

from src.modules.book_forge.ai.foundation.chunking.models.chunk import Chunk
from src.modules.book_forge.ai.foundation.chunking.models.chunk_result import ChunkStatistics
from src.modules.book_forge.ai.foundation.chunking.utils.token_estimator import TokenEstimator


class ChunkStatisticsCalculator:
    """Compute a :class:`ChunkStatistics` from a list of chunks."""

    @staticmethod
    def calculate(chunks: List[Chunk]) -> ChunkStatistics:
        """Return statistics over ``chunks`` (empty input -> zeroed stats)."""
        if not chunks:
            return ChunkStatistics()

        tokens = [ChunkStatisticsCalculator._tokens_of(c) for c in chunks]
        characters = [ChunkStatisticsCalculator._characters_of(c) for c in chunks]
        words = [ChunkStatisticsCalculator._words_of(c) for c in chunks]

        count = len(chunks)
        total_tokens = sum(tokens)
        return ChunkStatistics(
            total_chunks=count,
            total_tokens=total_tokens,
            average_tokens=round(total_tokens / count, 2),
            largest_tokens=max(tokens),
            smallest_tokens=min(tokens),
            average_characters=round(sum(characters) / count, 2),
            average_words=round(sum(words) / count, 2),
        )

    # -- per-chunk accessors (metadata first, computed fallback) -----------

    @staticmethod
    def _tokens_of(chunk: Chunk) -> int:
        if chunk.metadata.estimated_tokens is not None:
            return chunk.metadata.estimated_tokens
        return TokenEstimator.estimate(chunk.text)

    @staticmethod
    def _characters_of(chunk: Chunk) -> int:
        if chunk.metadata.character_count is not None:
            return chunk.metadata.character_count
        return len(chunk.text)

    @staticmethod
    def _words_of(chunk: Chunk) -> int:
        if chunk.metadata.word_count is not None:
            return chunk.metadata.word_count
        return len(chunk.text.split())
