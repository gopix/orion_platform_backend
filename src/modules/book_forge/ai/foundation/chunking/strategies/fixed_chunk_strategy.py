"""FixedChunkStrategy — fixed-size sliding windows with overlap.

The classic RAG strategy: ignore document structure and cut the text into
uniform windows of roughly ``chunk_size`` tokens, each overlapping the previous
by ``overlap`` tokens so context isn't lost at the seams. Useful when a document
has little or no usable structure (no headings, inconsistent paragraphs) and the
heading/paragraph strategies have nothing to grab onto.

Sizing uses the same ~4-characters-per-token estimate as the other strategies.
Windows break on word boundaries so a token is never cut in half.
"""
import math
from typing import List

from src.modules.book_forge.ai.foundation.chunking.models.chunk import Chunk
from src.modules.book_forge.ai.foundation.chunking.models.chunk_configuration import (
    ChunkConfiguration,
)
from src.modules.book_forge.ai.foundation.chunking.models.chunk_metadata import ChunkMetadata
from src.modules.book_forge.ai.foundation.chunking.models.chunk_request import ChunkRequest
from src.modules.book_forge.ai.foundation.chunking.models.chunk_result import (
    ChunkResult,
    ChunkStatistics,
)
from src.modules.book_forge.ai.foundation.chunking.strategies.base_chunk_strategy import (
    BaseChunkStrategy,
)

# Characters per estimated token (kept consistent across all strategies).
_CHARS_PER_TOKEN = 4


class FixedChunkStrategy(BaseChunkStrategy):
    """Chunk a document into fixed-size overlapping windows."""

    def chunk(self, request: ChunkRequest) -> ChunkResult:
        config = request.configuration
        warnings: List[str] = []

        document = request.document or ""
        if not document.strip():
            warnings.append("Document is empty; no chunks were produced.")
            return ChunkResult(chunks=[], statistics=ChunkStatistics(), warnings=warnings)

        target_chars = config.chunk_size * _CHARS_PER_TOKEN
        overlap_chars = self._resolve_overlap_chars(config, warnings)

        words = document.split()
        chunks: List[Chunk] = []
        start = 0
        n = len(words)
        while start < n:
            end = self._grow_window(words, start, target_chars)
            text = " ".join(words[start:end])
            chunks.append(self._build_chunk(len(chunks), text, request))

            if end >= n:
                break
            start = self._next_start(words, start, end, overlap_chars)

        chunks = self._merge_small_chunks(chunks, config, warnings)
        # Re-number after any merging so chunk_index stays contiguous.
        for i, chunk in enumerate(chunks):
            chunk.chunk_index = i

        return ChunkResult(
            chunks=chunks,
            statistics=self._build_statistics(chunks),
            warnings=warnings,
        )

    # -- windowing ---------------------------------------------------------

    def _resolve_overlap_chars(
        self, config: ChunkConfiguration, warnings: List[str]
    ) -> int:
        """Overlap in characters, clamped below chunk_size so windows advance."""
        if config.overlap >= config.chunk_size:
            warnings.append(
                f"overlap ({config.overlap}) >= chunk_size ({config.chunk_size}); "
                "clamped to chunk_size - 1 to guarantee forward progress."
            )
            return max(0, (config.chunk_size - 1) * _CHARS_PER_TOKEN)
        return config.overlap * _CHARS_PER_TOKEN

    def _grow_window(self, words: List[str], start: int, target_chars: int) -> int:
        """Return an exclusive end index: as many words as fit in target_chars.

        The first word is always included, even if it alone exceeds the target,
        so the window can never be empty.
        """
        char_len = 0
        end = start
        while end < len(words):
            addition = len(words[end]) + (1 if end > start else 0)
            if end > start and char_len + addition > target_chars:
                break
            char_len += addition
            end += 1
        return end

    def _next_start(
        self, words: List[str], start: int, end: int, overlap_chars: int
    ) -> int:
        """Step back from ``end`` to include ~overlap_chars of trailing words.

        Always returns at least ``start + 1`` so the window advances and the loop
        terminates.
        """
        next_start = end
        accumulated = 0
        while next_start > start + 1 and accumulated < overlap_chars:
            next_start -= 1
            accumulated += len(words[next_start]) + 1
        return next_start

    # -- small-chunk handling ---------------------------------------------

    def _merge_small_chunks(
        self, chunks: List[Chunk], config: ChunkConfiguration, warnings: List[str]
    ) -> List[Chunk]:
        """Fold chunks below ``min_chunk_size`` into a neighbour, if configured."""
        min_size = config.min_chunk_size
        if not (config.merge_small_chunks and min_size) or len(chunks) < 2:
            return chunks

        merged: List[Chunk] = []
        for chunk in chunks:
            too_small = self._estimate_tokens(chunk.text) < min_size
            if too_small and merged:
                prev = merged[-1]
                prev.text = f"{prev.text} {chunk.text}".strip()
                self._refresh_metadata(prev)
                warnings.append(
                    "Merged an undersized chunk into the preceding one "
                    f"(< min_chunk_size {min_size})."
                )
            else:
                merged.append(chunk)
        return merged

    # -- construction & stats ---------------------------------------------

    def _build_chunk(self, index: int, text: str, request: ChunkRequest) -> Chunk:
        chunk = Chunk(
            chunk_index=index,
            text=text,
            document_id=request.document_id,
            project_id=request.project_id,
            metadata=ChunkMetadata(
                language=request.language,
                source_type="fixed",
            ),
        )
        self._refresh_metadata(chunk)
        return chunk

    def _refresh_metadata(self, chunk: Chunk) -> None:
        """(Re)compute the size fields on a chunk's metadata from its text."""
        chunk.metadata.word_count = len(chunk.text.split())
        chunk.metadata.character_count = len(chunk.text)
        chunk.metadata.estimated_tokens = self._estimate_tokens(chunk.text)

    def _build_statistics(self, chunks: List[Chunk]) -> ChunkStatistics:
        if not chunks:
            return ChunkStatistics()

        tokens = [self._estimate_tokens(c.text) for c in chunks]
        total = sum(tokens)
        return ChunkStatistics(
            total_chunks=len(chunks),
            total_tokens=total,
            average_tokens=round(total / len(chunks), 2),
            largest_tokens=max(tokens),
            smallest_tokens=min(tokens),
        )

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Rough token estimate (~4 characters per token)."""
        return max(1, math.ceil(len(text) / _CHARS_PER_TOKEN))
