"""AgentRequest — input for running a single agent.

A common orchestration model (not a business model): it names the ``agent`` to
run, the ``input`` (task/instruction) for it, the shared ``context`` it runs
within, and free-form ``parameters``/``metadata``. Data model only — no behaviour.
"""
from typing import Any, Dict, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from src.modules.book_forge.ai.orchestration.models.workflow_context import (
    WorkflowContext,
)


class AgentRequest(BaseModel):
    # Which agent to run.
    agent: str
    # The task/instruction/input for the agent.
    input: Optional[Any] = None
    # Shared workflow state the agent may read/write.
    context: Optional[WorkflowContext] = None
    # Per-run tuning (temperature, tool allowlist, max steps, ...).
    parameters: Dict[str, Any] = Field(default_factory=dict)

    request_id: str = Field(default_factory=lambda: uuid4().hex)
    metadata: Dict[str, Any] = Field(default_factory=dict)
