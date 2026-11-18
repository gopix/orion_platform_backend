"""Standard result contract shared by every analyzer."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class Severity:
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    ORDER = (CRITICAL, HIGH, MEDIUM, LOW)


class CheckStatus:
    PASS = "PASS"
    FAIL = "FAIL"
    MANUAL_REVIEW = "MANUAL_REVIEW"     # a person must judge this
    NOT_TESTED = "NOT_TESTED"           # needs evidence that does not exist yet
    NOT_APPLICABLE = "NOT_APPLICABLE"   # the document has nothing to check
    NOT_EVALUATED = "NOT_EVALUATED"     # the check itself crashed; no verdict
    MANUAL_PENDING = (MANUAL_REVIEW, NOT_TESTED)


class AnalyzerStatus:
    COMPLETED = "completed"
    PARTIAL = "partial"     # some checks crashed, the others are still valid
    FAILED = "failed"       # no check produced a verdict


@dataclass
class Finding:
    """One occurrence of a problem, or one item waiting for manual validation."""
    rule_id: str
    severity: str
    status: str
    issue: str
    location: str
    recommendation: str
    wcag: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "status": self.status,
            "issue": self.issue,
            "location": self.location,
            "recommendation": self.recommendation,
            "wcag": self.wcag,
        }


@dataclass
class CheckResult:
    """The verdict for one rule. One rule is one check, however many occurrences it has."""
    rule_id: str
    title: str
    severity: str
    status: str
    affected_count: int = 0
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "title": self.title,
            "severity": self.severity,
            "status": self.status,
            "affected_count": self.affected_count,
            "detail": self.detail,
        }
