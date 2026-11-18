"""RiskCalculator — combine many check results into one risk decision.

Individual validators/policies only know their own PASS/FAIL/WARNING. This
centralises the overall judgement so services never hand-roll ``if violations:``
logic — as the number of validators grows (input, prompt, output, publisher, PII,
copyright, hallucination, ...) risk aggregation stays in one place.

    results  ->  RiskCalculator  ->  RiskResult (score, level, ALLOW/REVIEW/BLOCK)

Each failing check contributes risk based on its ``Severity``; contributions are
combined so more failures raise the score without a hard cap distortion. A
CRITICAL failure, or a score at/above the block threshold, blocks. Stateless and
pure.
"""
from typing import Dict, Iterable, List, Optional

from src.modules.book_forge.ai.intelligence.guardrails.models import (
    RiskDecision,
    RiskLevel,
    RiskResult,
    Severity,
    ValidationResult,
    ValidationStatus,
)

# Risk points per severity for a failed check.
_SEVERITY_POINTS = {
    Severity.LOW: 15,
    Severity.MEDIUM: 40,
    Severity.HIGH: 75,
    Severity.CRITICAL: 100,
}
# Warnings count for a fraction of their severity.
_WARNING_FACTOR = 0.35


class RiskCalculator:
    """Aggregate validation results into an overall ``RiskResult``."""

    def __init__(
        self,
        *,
        block_threshold: int = 70,
        review_threshold: int = 40,
        weights: Optional[Dict[str, float]] = None,
    ) -> None:
        self._block_threshold = block_threshold
        self._review_threshold = review_threshold
        # Optional per-rule multipliers (e.g. down-weight noisy rules).
        self._weights = weights or {}

    def calculate(self, results: List[ValidationResult]) -> RiskResult:
        """Return the aggregated ``RiskResult`` for ``results``."""
        risk_by_rule: Dict[str, int] = {}
        for result in results:
            contribution = self._contribution(result)
            if contribution or result.rule not in risk_by_rule:
                risk_by_rule[result.rule] = max(
                    risk_by_rule.get(result.rule, 0), contribution
                )

        overall = self._combine(risk_by_rule.values())
        decision = self._decide(overall, results)
        return RiskResult(
            overall_risk=overall,
            level=self._level(overall),
            decision=decision,
            risk_by_rule=risk_by_rule,
        )

    # -- internals ---------------------------------------------------------

    def _contribution(self, result: ValidationResult) -> int:
        if result.status == ValidationStatus.PASS:
            return 0
        points = _SEVERITY_POINTS.get(result.severity, _SEVERITY_POINTS[Severity.MEDIUM])
        points *= self._weights.get(result.rule, 1.0)
        if result.status == ValidationStatus.WARNING:
            points *= _WARNING_FACTOR
        return int(round(min(100, points)))

    @staticmethod
    def _combine(values: Iterable[int]) -> int:
        """Combine risks via probabilistic OR so many failures accumulate <=100."""
        product = 1.0
        for value in values:
            product *= 1 - min(100, max(0, value)) / 100
        return int(round((1 - product) * 100))

    def _decide(self, overall: int, results: List[ValidationResult]) -> RiskDecision:
        has_critical = any(
            r.status == ValidationStatus.FAIL and r.severity == Severity.CRITICAL
            for r in results
        )
        if has_critical or overall >= self._block_threshold:
            return RiskDecision.BLOCK
        if overall >= self._review_threshold:
            return RiskDecision.REVIEW
        return RiskDecision.ALLOW

    @staticmethod
    def _level(overall: int) -> RiskLevel:
        if overall >= 90:
            return RiskLevel.CRITICAL
        if overall >= 70:
            return RiskLevel.HIGH
        if overall >= 40:
            return RiskLevel.MEDIUM
        if overall > 0:
            return RiskLevel.LOW
        return RiskLevel.NONE
