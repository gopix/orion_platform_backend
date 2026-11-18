"""Shared helpers for the guardrail validators (private).

Small builders for ``ValidationResult`` so each validator reads clearly.
"""
from typing import Any, Dict, Optional

from src.modules.book_forge.ai.intelligence.guardrails.models import (
    Severity,
    ValidationResult,
    ValidationStatus,
)


def ok(rule: str, message: Optional[str] = None) -> ValidationResult:
    return ValidationResult(rule=rule, status=ValidationStatus.PASS, message=message)


def fail(
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


def warn(
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
