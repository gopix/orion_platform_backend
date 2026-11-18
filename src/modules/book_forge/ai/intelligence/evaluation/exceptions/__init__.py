"""Evaluation exception types.

    EvaluationException  (base)
      ├── MetricCalculationException   (a metric could not be computed)
      └── BenchmarkException            (a benchmark run failed)
"""
from src.modules.book_forge.ai.intelligence.evaluation.exceptions.benchmark_exception import (
    BenchmarkException,
)
from src.modules.book_forge.ai.intelligence.evaluation.exceptions.evaluation_exception import (
    EvaluationException,
)
from src.modules.book_forge.ai.intelligence.evaluation.exceptions.metric_calculation_exception import (
    MetricCalculationException,
)

__all__ = [
    "EvaluationException",
    "MetricCalculationException",
    "BenchmarkException",
]
