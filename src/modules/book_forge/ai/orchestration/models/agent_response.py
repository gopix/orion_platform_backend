"""AgentResponse — the result of running a single agent.

Bundles the agent's ``output`` with a success flag, any ``error``, the tools it
used, and timing — a self-contained record a workflow can collect per step. Data
model only — the agent/service fills these fields.
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AgentResponse(BaseModel):
    # Which agent produced this.
    agent: str
    success: bool = True
    # The agent's produced output.
    output: Optional[Any] = None
    # Populated when ``success`` is False.
    error: Optional[str] = None

    # Names of tools the agent invoked, for observability.
    tools_used: List[str] = Field(default_factory=list)
    execution_time_ms: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"from_attributes": True}
