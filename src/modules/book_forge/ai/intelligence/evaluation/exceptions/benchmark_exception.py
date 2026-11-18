"""BenchmarkException — a benchmark run failed.

Raised when a benchmark can't run or complete (missing dataset, misconfigured
suite, an evaluation within the run failing). A distinct type so benchmark
failures are separable from single-metric failures.
"""
from src.modules.book_forge.ai.intelligence.evaluation.exceptions.evaluation_exception import (
    EvaluationException,
)


class BenchmarkException(EvaluationException):
    """Raised when a benchmark run fails."""

    default_error_code = "EVAL-003"
    default_message = "Benchmark failed"
