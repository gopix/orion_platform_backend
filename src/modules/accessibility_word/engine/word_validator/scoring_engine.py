"""Step 10: accessibility metrics and score.

score = 100 x weight(passed) / weight(passed + failed)

Manual, NOT_TESTED, not-applicable and not-evaluated checks stay out of the score,
so missing evidence can neither raise nor lower it. Coverage shows how many automated
checks actually ran. The score never amounts to a conformance claim.
"""
from __future__ import annotations

from typing import Any

from src.modules.accessibility_word.engine.word_validator.rule_catalog import (
    RuleCatalog,
    load_catalog,
)
from src.modules.accessibility_word.models.audit_models import RuleEvaluation
from src.modules.accessibility_word.models.finding_models import CheckStatus, Severity


class WordAccessibilityScoringEngine:
    def __init__(self, catalog: RuleCatalog | None = None):
        self.catalog = catalog or load_catalog()

    def calculate(self, evaluation: RuleEvaluation) -> dict[str, Any]:
        weights = self.catalog.severity_weights
        checks = evaluation.checks

        def weight(*statuses: str) -> float:
            return sum(weights[c.severity] for c in checks if c.status in statuses)

        def count(*statuses: str) -> int:
            return sum(1 for c in checks if c.status in statuses)

        passed_weight = weight(CheckStatus.PASS)
        failed_weight = weight(CheckStatus.FAIL)
        missing_weight = weight(CheckStatus.NOT_EVALUATED)
        evaluated_weight = passed_weight + failed_weight

        score = round(100 * passed_weight / evaluated_weight, 1) if evaluated_weight else None
        automated_weight = evaluated_weight + missing_weight
        coverage = round(100 * evaluated_weight / automated_weight, 1) if automated_weight else 0.0
        manual_pending = count(*CheckStatus.MANUAL_PENDING)
        not_evaluated = count(CheckStatus.NOT_EVALUATED)

        if score is None:
            score_status = "unavailable"
        elif not_evaluated:
            score_status = "partial"
        else:
            score_status = "complete"

        failed_severities = {c.severity for c in checks if c.status == CheckStatus.FAIL}
        if failed_severities & {Severity.CRITICAL, Severity.HIGH}:
            risk_level = "HIGH"
        elif Severity.MEDIUM in failed_severities:
            risk_level = "MEDIUM"
        elif failed_severities:
            risk_level = "LOW"
        elif score is None:
            risk_level = "UNKNOWN"
        else:
            risk_level = "NONE_DETECTED"

        return {
            "score": score,
            "score_status": score_status,
            "scope": "automated_static_checks",
            "coverage_percent": coverage,
            "risk_level": risk_level,
            "conformance_established": False,
            "conformance_note": (
                "This score covers static DOCX checks only. It does not establish WCAG "
                "conformance or screen-reader compatibility."
            ),
            "summary": {
                "total_checks": count(CheckStatus.PASS, CheckStatus.FAIL, *CheckStatus.MANUAL_PENDING),
                "passed": count(CheckStatus.PASS),
                "failed": count(CheckStatus.FAIL),
                "manual_validation_pending": manual_pending,
                "not_applicable": count(CheckStatus.NOT_APPLICABLE),
                "not_evaluated": not_evaluated,
            },
        }
