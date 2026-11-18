"""InterviewState — state for the requirements-gathering (interview) phase.

The interview agent asks the user about the book and records their answers, so
later phases know the topic, audience, and goals.
"""
from typing import Any, Dict, List, Optional

from pydantic import Field

from src.modules.book_forge.ai.orchestration.workflow_state.base_workflow_state import (
    BaseWorkflowState,
)


class InterviewState(BaseWorkflowState):
    topic: Optional[str] = None
    audience: Optional[str] = None
    goals: Optional[str] = None

    # Questions asked and the answers gathered.
    questions: List[str] = Field(default_factory=list)
    answers: Dict[str, str] = Field(default_factory=dict)
    # Consolidated requirements handed to the blueprint phase.
    requirements: Dict[str, Any] = Field(default_factory=dict)
