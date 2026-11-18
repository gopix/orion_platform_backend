"""WorkflowResult — the outcome of running a workflow.

Bundles the final ``output`` with a success flag, the per-step ``AgentResponse``
list, the final shared ``context``, timing, and any error — so a workflow run is a
single, inspectable object. Data model only — the service fills these fields.
"""
from typing import Any, List, Optional

from pydantic import BaseModel, Field, computed_field

from src.modules.book_forge.ai.orchestration.models.agent_response import (
    AgentResponse,
)
from src.modules.book_forge.ai.orchestration.models.workflow_context import (
    WorkflowContext,
)


class WorkflowResult(BaseModel):
    workflow: str
    success: bool = False
    # The workflow's final output.
    output: Optional[Any] = None
    # Each agent/step's response, in execution order.
    step_results: List[AgentResponse] = Field(default_factory=list)
    # The shared context as it stood at the end of the run.
    context: Optional[WorkflowContext] = None
    execution_time_ms: Optional[float] = None
    error: Optional[str] = None

    model_config = {"from_attributes": True}

    @computed_field  # included in model_dump() / JSON output
    @property
    def step_count(self) -> int:
        return len(self.step_results)
