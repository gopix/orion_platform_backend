"""AgentExecutionException — an agent failed while executing.

Raised when a workflow agent errors during ``execute`` (a downstream service
failed, an LLM call raised, ...). Carries the agent name so the failing step is
obvious.
"""
from typing import Any, Dict, Optional

from src.modules.book_forge.ai.orchestration.exceptions.workflow_exception import (
    WorkflowException,
)


class AgentExecutionException(WorkflowException):
    """Raised when an agent fails to execute."""

    default_error_code = "WF-002"
    default_message = "Agent execution failed"

    def __init__(
        self,
        message: Optional[str] = None,
        *,
        agent: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        self.agent = agent
        merged: Dict[str, Any] = dict(details or {})
        if agent is not None:
            merged.setdefault("agent", agent)
        super().__init__(message, details=merged or None, cause=cause)
