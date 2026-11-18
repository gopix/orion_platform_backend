"""ValidationException — the guardrail request itself is invalid.

Raised when the input to guardrails is malformed (e.g. neither prompt nor output
provided). Distinct from a policy violation: the request is wrong, not the
content.
"""
from typing import Any, Dict, Optional

from src.modules.book_forge.ai.intelligence.guardrails.exceptions.guardrail_exception import (
    GuardrailException,
)


class ValidationException(GuardrailException):
    """Raised when a ``GuardrailRequest`` is invalid."""

    default_error_code = "GR-003"
    default_message = "Invalid guardrail request"

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
