"""Base class that gives every analyzer the same result shape and error isolation."""
from __future__ import annotations

import inspect
import logging
import time
from dataclasses import dataclass

from src.modules.accessibility_word.engine.word_validator.rule_catalog import (
    RuleCatalog,
    load_catalog,
)
from src.modules.accessibility_word.models.audit_models import AnalyzerResult
from src.modules.accessibility_word.models.document_context import DocumentContext
from src.modules.accessibility_word.models.finding_models import (
    AnalyzerStatus,
    CheckResult,
    CheckStatus,
    Finding,
)

logger = logging.getLogger(__name__)


@dataclass
class Item:
    """One occurrence reported by a check."""
    issue: str
    location: str
    recommendation: str | None = None


class Recorder:
    """Collects verdicts during a run. Severity and advice always come from the catalog."""

    def __init__(self, catalog: RuleCatalog):
        self._catalog = catalog
        self._max_items = int(catalog.threshold("max_findings_per_rule"))
        self.checks: dict[str, CheckResult] = {}
        self.findings: list[Finding] = []

    def record(self, rule_id: str, status: str, items: list[Item] | None = None,
               detail: str | None = None) -> None:
        rule = self._catalog.get(rule_id)
        items = items or []
        self.checks[rule_id] = CheckResult(
            rule_id=rule_id, title=rule.title, severity=rule.severity,
            status=status, affected_count=len(items), detail=detail,
        )
        # Occurrences are capped to keep responses bounded; affected_count stays exact.
        for item in items[:self._max_items]:
            self.findings.append(Finding(
                rule_id=rule_id, severity=rule.severity, status=status,
                issue=item.issue, location=item.location,
                recommendation=item.recommendation or rule.recommendation,
                wcag=list(rule.wcag),
            ))

    def evaluate(self, rule_id: str, violations: list[Item], detail: str | None = None) -> None:
        """PASS when there are no violations, otherwise FAIL."""
        self.record(rule_id, CheckStatus.FAIL if violations else CheckStatus.PASS,
                    violations, detail)

    def manual(self, rule_id: str, items: list[Item], detail: str | None = None) -> None:
        self.record(rule_id, CheckStatus.MANUAL_REVIEW, items, detail)

    def not_applicable(self, rule_id: str, reason: str) -> None:
        self.record(rule_id, CheckStatus.NOT_APPLICABLE, detail=reason)


class BaseAnalyzer:
    """Subclasses add one check_* method per rule. Each check is isolated from the others."""

    name = "BaseAnalyzer"
    category = "UNCATEGORIZED"
    required_parts: tuple[str, ...] = ()

    def __init__(self, catalog: RuleCatalog | None = None):
        self.catalog = catalog or load_catalog()

    def _checks(self):
        members = inspect.getmembers(self, predicate=inspect.ismethod)
        return [method for name, method in members if name.startswith("check_")]

    def analyze(self, context: DocumentContext) -> AnalyzerResult:
        started = time.perf_counter()
        recorder = Recorder(self.catalog)
        errors: list[str] = []

        unavailable = [p for p in self.required_parts if p in context.failed_parts]
        if unavailable:
            errors.append(f"Required document part could not be parsed: {', '.join(unavailable)}")
        else:
            for check in self._checks():
                try:
                    check(context, recorder)
                except Exception as exc:
                    logger.exception("%s.%s failed", self.name, check.__name__)
                    errors.append(f"{check.__name__}: {type(exc).__name__}: {exc}")

        # A rule without a verdict is reported as NOT_EVALUATED, never as passed.
        for rule in self.catalog.for_analyzer(self.name):
            if rule.rule_id not in recorder.checks:
                recorder.record(rule.rule_id, CheckStatus.NOT_EVALUATED,
                                detail="The check did not complete.")

        checks = list(recorder.checks.values())
        evaluated = [c for c in checks if c.status != CheckStatus.NOT_EVALUATED]
        if not errors and len(evaluated) == len(checks):
            status = AnalyzerStatus.COMPLETED
        elif evaluated:
            status = AnalyzerStatus.PARTIAL
        else:
            status = AnalyzerStatus.FAILED

        return AnalyzerResult(
            analyzer=self.name, category=self.category, status=status,
            checks=sorted(checks, key=lambda c: c.rule_id), findings=recorder.findings,
            errors=errors, duration_ms=int((time.perf_counter() - started) * 1000),
        )
