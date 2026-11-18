"""ExportState — state for the final export phase.

The export agent renders the approved book into a target format and records where
the artifact landed.
"""
from typing import Optional

from src.modules.book_forge.ai.orchestration.workflow_state.base_workflow_state import (
    BaseWorkflowState,
)


class ExportState(BaseWorkflowState):
    # Target format: "pdf", "docx", "epub", ...
    export_format: str = "pdf"
    output_path: Optional[str] = None
    exported: bool = False
    page_count: Optional[int] = None
    file_size_bytes: Optional[int] = None
