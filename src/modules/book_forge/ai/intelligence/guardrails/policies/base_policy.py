"""BasePolicy — the contract every guardrail policy implements.

A policy encapsulates *one* rule set (PII, prompt injection, publisher rules, ...)
and evaluates a ``GuardrailRequest`` into a single ``PolicyResult``. Representing
policies as objects — rather than hardcoding checks in the service — lets them be
composed, enabled/disabled, and configured independently.

    GuardrailRequest  ->  <Policy>.evaluate()  ->  PolicyResult

Concrete policies implement ``evaluate``; the shared helpers here build individual
``ValidationResult`` objects and roll them up to the policy's status.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from src.modules.book_forge.ai.intelligence.guardrails.models import (
    GuardrailRequest,
    PolicyResult,
    Severity,
    ValidationResult,
    ValidationStatus,
)


class BasePolicy(ABC):
    """Common contract for all guardrail policies."""

    #: Policy name; each subclass overrides.
    name: str = "policy"

    @abstractmethod
    def evaluate(self, request: GuardrailRequest) -> PolicyResult:
        """Evaluate ``request`` and return this policy's result."""
        raise NotImplementedError

    # -- result builders ---------------------------------------------------

    @staticmethod
    def _ok(rule: str, message: Optional[str] = None) -> ValidationResult:
        return ValidationResult(rule=rule, status=ValidationStatus.PASS, message=message)

    @staticmethod
    def _fail(
        rule: str,
        message: str,
        *,
        severity: Severity = Severity.MEDIUM,
        details: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        return ValidationResult(
            rule=rule,
            status=ValidationStatus.FAIL,
            severity=severity,
            message=message,
            details=details or {},
        )

    @staticmethod
    def _warn(
        rule: str,
        message: str,
        *,
        severity: Severity = Severity.LOW,
        details: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        return ValidationResult(
            rule=rule,
            status=ValidationStatus.WARNING,
            severity=severity,
            message=message,
            details=details or {},
        )

    def _finalize(
        self, results: List[ValidationResult], *, message: Optional[str] = None
    ) -> PolicyResult:
        """Roll a list of check results up to a single policy status.

        FAIL wins over WARNING wins over PASS.
        """
        if any(r.status == ValidationStatus.FAIL for r in results):
            status = ValidationStatus.FAIL
        elif any(r.status == ValidationStatus.WARNING for r in results):
            status = ValidationStatus.WARNING
        else:
            status = ValidationStatus.PASS
        return PolicyResult(
            policy=self.name, status=status, message=message, results=results
        )
