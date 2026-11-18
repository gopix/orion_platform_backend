"""Shared helpers for the evaluators (private).

Builders for metrics/results, plus small text utilities. Keeping these here lets
each evaluator focus on *what* it measures, not plumbing.
"""
import re
import time
from typing import Any, List, Optional

from src.modules.book_forge.ai.intelligence.evaluation.models import (
    AIModule,
    EvaluationMetric,
    EvaluationResult,
    ScoreCard,
)

_WORD_RE = re.compile(r"[a-z0-9]+")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_DEFAULT_THRESHOLD = 0.7


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def get(obj: Any, key: str, default: Any = None) -> Any:
    """Read ``key`` from a dict or an object with attributes."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def metric(
    name: str,
    score: float,
    *,
    threshold: Optional[float] = _DEFAULT_THRESHOLD,
    weight: float = 1.0,
    message: Optional[str] = None,
) -> EvaluationMetric:
    return EvaluationMetric(
        name=name,
        score=round(clamp(score), 4),
        threshold=threshold,
        weight=weight,
        message=message,
    )


def aggregate(metrics: List[EvaluationMetric]) -> float:
    """Weighted mean of metric scores (0–1)."""
    total_weight = sum(m.weight for m in metrics)
    if total_weight <= 0:
        return 0.0
    return round(sum(m.score * m.weight for m in metrics) / total_weight, 4)


def build_result(
    module: AIModule,
    metrics: List[EvaluationMetric],
    start: float,
    *,
    score_card: Optional[ScoreCard] = None,
    recommendations: Optional[List[str]] = None,
) -> EvaluationResult:
    overall = aggregate(metrics)
    return EvaluationResult(
        module=module,
        overall_score=overall,
        passed=all(m.passed for m in metrics),
        metrics=metrics,
        score_card=score_card,
        recommendations=recommendations or [],
        execution_time_ms=round((time.perf_counter() - start) * 1000, 3),
    )


# -- text helpers ----------------------------------------------------------

def words(text: str) -> List[str]:
    return _WORD_RE.findall((text or "").lower())


def normalize(text: str) -> str:
    return _NON_ALNUM.sub("", (text or "").lower())


def overlap(a: str, b: str) -> float:
    """Fraction of ``a``'s content words that also appear in ``b`` (grounding)."""
    a_words = words(a)
    if not a_words:
        return 1.0
    b_set = set(words(b))
    return round(sum(1 for w in a_words if w in b_set) / len(a_words), 4)
