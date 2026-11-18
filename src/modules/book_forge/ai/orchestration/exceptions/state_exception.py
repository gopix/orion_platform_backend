"""StateException — the workflow state is invalid or in a bad transition.

Raised when the state a workflow/agent receives is missing required data, is the
wrong type, or an illegal state transition is attempted. Distinct from an agent's
runtime failure.
"""
from typing import Any, Dict, Optional

from src.modules.book_forge.ai.orchestration.exceptions.workflow_exception import (
    WorkflowException,
)


class StateException(WorkflowException):
    """Raised when a workflow state is invalid."""

    default_error_code = "WF-003"
    default_message = "Invalid workflow state"

    def __init__(
        self,
        message: Optional[str] = None,
        *,
        field: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        merged: Dict[str, Any] = dict(details or {})
        if field is not None:
            merged.setdefault("field", field)
        super().__init__(message, details=merged or None, cause=cause)
