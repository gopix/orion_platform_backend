"""ParagraphChunkStrategy — one chunk per paragraph.

The simplest structural strategy: paragraphs (runs of text separated by blank
lines) each become a chunk. There is no heading hierarchy to track — this suits
reports, manuals, and plain prose documents where the paragraph is the natural
unit of meaning.

``max_chunk_size`` splits an oversized paragraph on sentence boundaries, and
``merge_small_chunks`` folds tiny paragraphs into their predecessor, keeping the
output usable without changing the paragraph-first idea.
"""
import math
import re
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

# One or more blank lines separate paragraphs.
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")
# Sentence boundary: end punctuation followed by whitespace.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


class ParagraphChunkStrategy(BaseChunkStrategy):
    """Chunk a document one paragraph at a time."""

    def chunk(self, request: ChunkRequest) -> ChunkResult:
        config = request.configuration
        warnings: List[str] = []

        document = request.document or ""
        if not document.strip():
            warnings.append("Document is empty; no chunks were produced.")
            return ChunkResult(chunks=[], statistics=ChunkStatistics(), warnings=warnings)

        paragraphs = [
            p.strip() for p in _PARAGRAPH_SPLIT_RE.split(document) if p.strip()
        ]

        chunks: List[Chunk] = []
        for paragraph in paragraphs:
            for piece in self._enforce_max_size(paragraph, config, warnings):
                chunks.append(self._build_chunk(len(chunks), piece, request))

        chunks = self._merge_small_chunks(chunks, config, warnings)
        # Re-number after any merging so chunk_index stays contiguous.
        for i, chunk in enumerate(chunks):
            chunk.chunk_index = i

        return ChunkResult(
            chunks=chunks,
            statistics=self._build_statistics(chunks),
            warnings=warnings,
        )

    # -- size handling -----------------------------------------------------

    def _enforce_max_size(
        self, text: str, config: ChunkConfiguration, warnings: List[str]
    ) -> List[str]:
        """Split an oversized paragraph on sentence boundaries, if a ceiling is set."""
        max_size = config.max_chunk_size
        if not max_size or self._estimate_tokens(text) <= max_size:
            return [text]

        sentences = [s for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
        pieces: List[str] = []
        buffer = ""
        for sentence in sentences:
            candidate = f"{buffer} {sentence}".strip() if buffer else sentence
            if buffer and self._estimate_tokens(candidate) > max_size:
                pieces.append(buffer)
                buffer = sentence
            else:
                buffer = candidate
        if buffer:
            pieces.append(buffer)

        if len(pieces) > 1:
            warnings.append(
                f"A paragraph exceeded max_chunk_size ({max_size}) and was split "
                f"into {len(pieces)} chunks."
            )
        return pieces

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
                prev.text = f"{prev.text}\n\n{chunk.text}".strip()
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
                source_type="paragraph",
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
        return max(1, math.ceil(len(text) / 4))
