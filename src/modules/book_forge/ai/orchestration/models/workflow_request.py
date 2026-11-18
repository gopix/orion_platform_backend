"""WorkflowRequest — input for running a multi-agent workflow.

Names the ``workflow`` to run, its ``input``, an optional starting ``context``,
and tuning ``parameters``. A workflow chains agents; each receives an
``AgentRequest`` derived from this. Data model only — no behaviour.
"""
from typing import Any, Dict, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from src.modules.book_forge.ai.orchestration.models.workflow_context import (
    WorkflowContext,
)


class WorkflowRequest(BaseModel):
    # Which workflow to run.
    workflow: str
    # The initial input for the workflow.
    input: Optional[Any] = None
    # Optional pre-seeded shared context.
    context: Optional[WorkflowContext] = None
    parameters: Dict[str, Any] = Field(default_factory=dict)

    request_id: str = Field(default_factory=lambda: uuid4().hex)
    project_id: Optional[int] = None
    document_id: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
