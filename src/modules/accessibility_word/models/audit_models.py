"""Analyzer output and rule-engine output."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.modules.accessibility_word.models.finding_models import (
    AnalyzerStatus,
    CheckResult,
    CheckStatus,
    Finding,
)


@dataclass
class AnalyzerResult:
    analyzer: str
    category: str
    status: str = AnalyzerStatus.COMPLETED
    checks: list[CheckResult] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    duration_ms: int = 0

    def _count(self, *statuses: str) -> int:
        return sum(1 for check in self.checks if check.status in statuses)

    @property
    def passed(self) -> int:
        return self._count(CheckStatus.PASS)

    @property
    def failed(self) -> int:
        return self._count(CheckStatus.FAIL)

    @property
    def manual_pending(self) -> int:
        return self._count(*CheckStatus.MANUAL_PENDING)

    @property
    def not_applicable(self) -> int:
        return self._count(CheckStatus.NOT_APPLICABLE)

    @property
    def not_evaluated(self) -> int:
        return self._count(CheckStatus.NOT_EVALUATED)

    @property
    def total_checks(self) -> int:
        """Checks with an outcome: passed + failed + manual_pending."""
        return self.passed + self.failed + self.manual_pending

    def to_dict(self) -> dict[str, Any]:
        return {
            "analyzer": self.analyzer,
            "category": self.category,
            "status": self.status,
            "total_checks": self.total_checks,
            "passed": self.passed,
            "failed": self.failed,
            "manual_pending": self.manual_pending,
            "not_applicable": self.not_applicable,
            "not_evaluated": self.not_evaluated,
            "errors": self.errors,
            "duration_ms": self.duration_ms,
            "checks": [check.to_dict() for check in self.checks],
            "findings": [finding.to_dict() for finding in self.findings],
        }


@dataclass
class RuleEvaluation:
    """Rule-engine output consumed by the scoring engine and report generator."""
    analyzer_results: list[AnalyzerResult]
    checks: list[CheckResult]
    findings: list[Finding]
