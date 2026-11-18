"""ChunkingAgent — chunk each parsed document's text.

Wraps the chunking service. Flattens each ``ParsedDocument`` to text, chunks it,
and aggregates all chunks onto ``state.chunks``.
"""
from typing import Any, List

from src.core.config import settings
from src.modules.book_forge.ai.foundation.chunking.models import ChunkRequest
from src.modules.book_forge.ai.foundation.chunking.models.chunk_configuration import (
    ChunkConfiguration,
)
from src.modules.book_forge.ai.foundation.chunking.services import chunking_service
from src.modules.book_forge.ai.orchestration.agents.base_agent import BaseAgent
from src.modules.book_forge.ai.orchestration.workflow_state import (
    ProcessingWorkflowState,
)


def _chunk_configuration() -> ChunkConfiguration:
    """Build the chunk configuration from settings (tunable via .env)."""
    return ChunkConfiguration(
        chunk_size=settings.chunk_size,
        overlap=settings.chunk_overlap,
        min_chunk_size=settings.chunk_min_size,
        max_chunk_size=settings.chunk_max_size,
        merge_small_chunks=settings.chunk_merge_small,
    )


class ChunkingAgent(BaseAgent[ProcessingWorkflowState]):
    """Chunk the parsed documents into retrievable pieces."""

    name = "Chunking Agent"
    step = "chunking"

    def execute(self, state: ProcessingWorkflowState) -> None:
        if not state.parsed_documents:
            state.skip("chunking", "no parsed documents")
            return

        configuration = _chunk_configuration()

        chunks: List[Any] = []
        for parsed in state.parsed_documents:
            text = _document_text(parsed)
            if not text.strip():
                continue
            document_id = parsed.metadata.extra.get("document_id")
            result = chunking_service.chunk(
                ChunkRequest(
                    document=text,
                    strategy=settings.chunk_strategy,
                    configuration=configuration,
                    project_id=state.project_id,
                    document_id=document_id,
                )
            )
            chunks.extend(result.chunks)

        state.chunks = chunks
        state.add_message("assistant", f"Produced {len(chunks)} chunk(s).")


def _document_text(parsed: Any) -> str:
    """Flatten a ParsedDocument's paragraphs and section tree into one string."""
    parts: List[str] = [p.text for p in getattr(parsed, "paragraphs", []) or []]

    def walk(sections) -> None:
        for section in sections or []:
            if getattr(section, "title", None):
                parts.append(section.title)
            parts.extend(p.text for p in section.paragraphs)
            walk(section.subsections)

    walk(getattr(parsed, "sections", []))
    return "\n\n".join(parts)
