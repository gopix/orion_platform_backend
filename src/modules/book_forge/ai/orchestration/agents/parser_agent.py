"""ParserAgent — parse each source document into a ``ParsedDocument``.

Wraps the parser service. Reads the document descriptors from the state, parses
each from disk, and writes the results to ``state.parsed_documents``. A single
document that fails to parse is recorded and skipped rather than failing the run.
"""
from pathlib import Path

from src.modules.book_forge.ai.intelligence.parsers.services import parser_service
from src.modules.book_forge.ai.orchestration.agents.base_agent import BaseAgent
from src.modules.book_forge.ai.orchestration.workflow_state import (
    ProcessingWorkflowState,
)


class ParserAgent(BaseAgent[ProcessingWorkflowState]):
    """Parse the project's documents into structured ``ParsedDocument`` objects."""

    name = "Parser Agent"
    step = "parser"

    def execute(self, state: ProcessingWorkflowState) -> None:
        parsed = []
        for descriptor in state.documents:
            path = Path(descriptor.get("file_path", ""))
            if not path.exists():
                state.add_message("system", f"Document file missing: {path}")
                continue
            try:
                document = parser_service.parse(
                    path.read_bytes(), filename=descriptor.get("filename")
                )
            except Exception as exc:  # noqa: BLE001 - one bad doc shouldn't fail all
                state.add_message(
                    "system", f"Failed to parse {descriptor.get('filename')}: {exc}"
                )
                continue
            # Stash the source document id so later stages can attribute output.
            document.metadata.extra["document_id"] = descriptor.get("id")
            parsed.append(document)

        state.parsed_documents = parsed
        state.add_message("assistant", f"Parsed {len(parsed)} document(s).")
