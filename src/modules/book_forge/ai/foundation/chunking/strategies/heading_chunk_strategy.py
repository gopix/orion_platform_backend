"""HeadingChunkStrategy — split a document along its heading structure.

BookForge is a publishing platform, so documents are inherently structured:
chapters, sections, sub-sections. This strategy — the module default — splits on
those headings so each chunk maps to one logical unit of the document
(``Chapter 1`` -> chunk, ``Section 1.1`` -> chunk, ...). That preserves document
semantics far better than blind fixed-size windows.

Headings are detected as Markdown ATX headings (``#`` .. ``######``). Content
before the first heading becomes a preamble chunk. A breadcrumb of the enclosing
headings is recorded on ``Chunk.section`` so a chunk always knows where it sits
in the document tree.
"""
import math
import re
from typing import List, Optional

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

# A Markdown ATX heading: 1–6 leading '#', a space, then the title.
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


class _Section:
    """A heading and the body text that follows it, before any final splitting."""

    def __init__(
        self,
        heading: Optional[str],
        level: Optional[int],
        section_path: Optional[str],
    ) -> None:
        self.heading = heading
        self.level = level
        self.section_path = section_path
        self.lines: List[str] = []


class HeadingChunkStrategy(BaseChunkStrategy):
    """Chunk a document by its heading hierarchy (the default strategy)."""

    def chunk(self, request: ChunkRequest) -> ChunkResult:
        config = request.configuration
        warnings: List[str] = []

        document = request.document or ""
        if not document.strip():
            warnings.append("Document is empty; no chunks were produced.")
            return ChunkResult(chunks=[], statistics=ChunkStatistics(), warnings=warnings)

        sections = self._split_into_sections(document)

        chunks: List[Chunk] = []
        for section in sections:
            body = "\n".join(section.lines).strip()

            # Optionally prepend the heading line to the chunk's text.
            if section.heading and config.preserve_headings:
                heading_line = f"{'#' * (section.level or 1)} {section.heading}"
                text = f"{heading_line}\n\n{body}".strip() if body else heading_line
            else:
                text = body

            if not text:
                # A heading with no body still forms a locating chunk.
                if section.heading:
                    text = section.heading
                else:
                    continue

            # A single section may exceed the size ceiling; split it if asked.
            pieces = self._enforce_max_size(text, config, warnings)
            for piece in pieces:
                chunks.append(
                    self._build_chunk(
                        index=len(chunks),
                        heading=section.heading,
                        section_path=section.section_path,
                        level=section.level,
                        text=piece,
                        request=request,
                    )
                )

        chunks = self._merge_small_chunks(chunks, config, warnings)
        # Re-number after any merging so chunk_index stays contiguous.
        for i, chunk in enumerate(chunks):
            chunk.chunk_index = i

        return ChunkResult(
            chunks=chunks,
            statistics=self._build_statistics(chunks),
            warnings=warnings,
        )

    # -- section parsing ---------------------------------------------------

    def _split_into_sections(self, document: str) -> List[_Section]:
        """Walk the document line by line, starting a new section at each heading."""
        sections: List[_Section] = []
        # Stack of (level, title) for building the breadcrumb path.
        heading_stack: List[tuple] = []
        current = _Section(heading=None, level=None, section_path=None)

        for line in document.splitlines():
            match = _HEADING_RE.match(line)
            if match:
                # Flush whatever we accumulated under the previous heading.
                if current.heading is not None or current.lines:
                    sections.append(current)

                level = len(match.group(1))
                title = match.group(2).strip()

                # Maintain the breadcrumb: drop deeper/sibling levels, then push.
                while heading_stack and heading_stack[-1][0] >= level:
                    heading_stack.pop()
                heading_stack.append((level, title))
                section_path = " > ".join(t for _, t in heading_stack)

                current = _Section(heading=title, level=level, section_path=section_path)
            else:
                current.lines.append(line)

        if current.heading is not None or current.lines:
            sections.append(current)

        return sections

    # -- size handling -----------------------------------------------------

    def _enforce_max_size(
        self, text: str, config: ChunkConfiguration, warnings: List[str]
    ) -> List[str]:
        """Split an oversized section on paragraph boundaries, if a ceiling is set."""
        max_size = config.max_chunk_size
        if not max_size or self._estimate_tokens(text) <= max_size:
            return [text]

        paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
        pieces: List[str] = []
        buffer = ""
        for para in paragraphs:
            candidate = f"{buffer}\n\n{para}".strip() if buffer else para
            if buffer and self._estimate_tokens(candidate) > max_size:
                pieces.append(buffer)
                buffer = para
            else:
                buffer = candidate
        if buffer:
            pieces.append(buffer)

        if len(pieces) > 1:
            warnings.append(
                f"A section exceeded max_chunk_size ({max_size}) and was split "
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

    def _build_chunk(
        self,
        index: int,
        heading: Optional[str],
        section_path: Optional[str],
        level: Optional[int],
        text: str,
        request: ChunkRequest,
    ) -> Chunk:
        chunk = Chunk(
            chunk_index=index,
            text=text,
            heading=heading,
            section=section_path,
            document_id=request.document_id,
            project_id=request.project_id,
            metadata=ChunkMetadata(
                heading_level=level,
                language=request.language,
                source_type="heading",
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
