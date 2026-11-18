"""MetricCalculationException — computing a metric failed.

Raised when an evaluator/metric can't be computed (bad or missing inputs, a
division that can't be performed, an underlying error). Wraps the cause so
callers see an evaluation exception rather than a raw error.
"""
from src.modules.book_forge.ai.intelligence.evaluation.exceptions.evaluation_exception import (
    EvaluationException,
)


class MetricCalculationException(EvaluationException):
    """Raised when a metric cannot be calculated."""

    default_error_code = "EVAL-002"
    default_message = "Metric calculation failed"
