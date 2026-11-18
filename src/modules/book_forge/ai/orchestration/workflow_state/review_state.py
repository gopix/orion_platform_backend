"""ReviewState — state for the quality-review phase.

The review agent inspects generated content and records issues, a score, and
whether it's approved or needs revisions before export.
"""
from typing import Any, Dict, List, Optional

from pydantic import Field

from src.modules.book_forge.ai.orchestration.workflow_state.base_workflow_state import (
    BaseWorkflowState,
)


class ReviewState(BaseWorkflowState):
    # The content under review (or a reference to it).
    draft: Optional[str] = None

    approved: bool = False
    score: Optional[float] = None
    # Problems found: [{"severity", "message", "location"}, ...].
    issues: List[Dict[str, Any]] = Field(default_factory=list)
    revisions_requested: List[str] = Field(default_factory=list)
