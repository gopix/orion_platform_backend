"""ExportAgent — finalise and 'export' the approved blueprint.

Business responsibility: produce the export artifact metadata (output path,
format, rough size) for the approved book, and mark the workflow complete.
Operates on ``ExportState``; reads the blueprint from
``state.metadata['blueprint']``.

Note: this baseline records where the artifact *would* land and its estimated
size; actual rendering (pptx/docx/pdf) is a later step.
"""
import re

from src.modules.book_forge.ai.orchestration.agents.base_agent import BaseAgent
from src.modules.book_forge.ai.orchestration.workflow_state import ExportState

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_PAGES_PER_CHAPTER = 20
_BYTES_PER_PAGE = 2048


class ExportAgent(BaseAgent[ExportState]):
    """Export the finished book and complete the workflow."""

    name = "Export Agent"
    step = "export"

    def execute(self, state: ExportState) -> None:
        blueprint = state.metadata.get("blueprint") or {}
        title = blueprint.get("title", "book") if isinstance(blueprint, dict) else "book"
        chapters = blueprint.get("chapters", []) if isinstance(blueprint, dict) else []

        slug = _SLUG_RE.sub("-", title.lower()).strip("-") or "book"
        state.output_path = f"exports/{slug}.{state.export_format}"
        state.page_count = max(1, len(chapters) * _PAGES_PER_CHAPTER)
        state.file_size_bytes = state.page_count * _BYTES_PER_PAGE
        state.exported = True
        state.add_message(
            "assistant", f"Exported '{title}' to {state.output_path}."
        )
        # Export is the terminal phase — mark the workflow complete.
        state.complete()
