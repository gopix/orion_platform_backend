"""PolicyViolationException — content was blocked by a guardrail policy.

Raised (in strict mode) when one or more policies fail — e.g. PII detected, a
prompt-injection attempt, a publisher rule broken. Carries the failing checks so
callers can report exactly what went wrong.
"""
from typing import Any, Dict, List, Optional

from src.modules.book_forge.ai.intelligence.guardrails.exceptions.guardrail_exception import (
    GuardrailException,
)


class PolicyViolationException(GuardrailException):
    """Raised when a request/response violates one or more policies."""

    default_error_code = "GR-002"
    default_message = "Guardrail policy violation"

    def __init__(
        self,
        message: Optional[str] = None,
        *,
        violations: Optional[List[Any]] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        self.violations = violations or []
        merged: Dict[str, Any] = dict(details or {})
        merged.setdefault("violation_count", len(self.violations))
        super().__init__(message, details=merged, cause=cause)
