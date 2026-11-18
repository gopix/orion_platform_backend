"""BaseWorkflowState — the state object threaded through a workflow.

LangGraph-style: each agent/node receives the state, updates it, and returns it.
This base holds the fields every phase shares (status, current step, history,
errors, messages) plus small mutation helpers, so concrete phase states only add
their own fields.
"""
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class WorkflowStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BaseWorkflowState(BaseModel):
    run_id: str = Field(default_factory=lambda: uuid4().hex)
    project_id: Optional[int] = None
    document_id: Optional[int] = None

    status: WorkflowStatus = WorkflowStatus.PENDING
    current_step: Optional[str] = None
    # Steps completed so far, in order.
    history: List[str] = Field(default_factory=list)
    # Accumulated errors (non-fatal or fatal).
    errors: List[str] = Field(default_factory=list)
    # Conversation/log messages: {"role": ..., "content": ...}.
    messages: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"from_attributes": True}

    # -- mutation helpers (state is meant to be updated in place) ----------

    def advance(self, step: str) -> "BaseWorkflowState":
        """Mark a step as the current one and record the previous in history."""
        if self.current_step and self.current_step not in self.history:
            self.history.append(self.current_step)
        self.current_step = step
        self.status = WorkflowStatus.RUNNING
        return self

    def add_message(self, role: str, content: Any) -> "BaseWorkflowState":
        self.messages.append({"role": role, "content": content})
        return self

    def fail(self, error: str) -> "BaseWorkflowState":
        self.errors.append(error)
        self.status = WorkflowStatus.FAILED
        return self

    def complete(self) -> "BaseWorkflowState":
        if self.current_step and self.current_step not in self.history:
            self.history.append(self.current_step)
        self.status = WorkflowStatus.COMPLETED
        return self
