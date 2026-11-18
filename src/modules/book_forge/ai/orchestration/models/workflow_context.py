"""WorkflowContext — shared state passed between agents/steps in a workflow.

The "blackboard" a workflow carries as it runs: a mutable ``data`` bag that agents
read from and write to, a ``history`` of executed steps, and ownership ids. Unlike
the other (pure-data) models, this one exposes small convenience helpers because
its whole purpose is to be read and updated as the workflow progresses.
"""
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class WorkflowContext(BaseModel):
    run_id: str = Field(default_factory=lambda: uuid4().hex)
    # Shared key/value state accumulated across steps.
    data: Dict[str, Any] = Field(default_factory=dict)
    # Names of the steps executed so far, in order.
    history: List[str] = Field(default_factory=list)

    # Ownership.
    project_id: Optional[int] = None
    document_id: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"from_attributes": True}

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> "WorkflowContext":
        self.data[key] = value
        return self

    def update(self, values: Dict[str, Any]) -> "WorkflowContext":
        self.data.update(values)
        return self

    def record_step(self, step: str) -> "WorkflowContext":
        self.history.append(step)
        return self
