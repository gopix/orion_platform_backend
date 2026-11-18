"""Evaluation orchestration service.

One orchestrator for measuring any AI operation:

    EvaluationRequest -> validate -> evaluator (by module) -> metrics
    -> score card -> EvaluationResult

The service owns orchestration only: it validates the request, dispatches to the
evaluator for the request's ``module``, ensures a ``ScoreCard`` summarising the
metrics, and returns the result. It never computes metrics itself — evaluators do.
Evaluators are injectable, so adding a new module's evaluator needs no change here
beyond registering it.
"""
import time
from typing import Dict, List, Optional

from src.core.logger import get_logger
from src.modules.book_forge.ai.intelligence.evaluation.evaluators import (
    ChunkEvaluator,
    GraphEvaluator,
    PromptEvaluator,
    ResponseEvaluator,
    RetrievalEvaluator,
)
from src.modules.book_forge.ai.intelligence.evaluation.exceptions import (
    EvaluationException,
    MetricCalculationException,
)
from src.modules.book_forge.ai.intelligence.evaluation.models import (
    AIModule,
    EvaluationRequest,
    EvaluationResult,
    ScoreCard,
)
from src.modules.book_forge.ai.intelligence.evaluation.validators import (
    EvaluationValidator,
)

logger = get_logger(__name__)

# Metric names grouped into the score card's headline dimensions.
_DIMENSION_KEYWORDS = {
    "accuracy": {
        "faithfulness", "top_k_relevance", "relationship_quality",
        "average_size", "token_efficiency",
    },
    "completeness": {
        "completeness", "missing_chunks", "heading_preservation",
        "entity_count", "prompt_completeness", "variable_usage",
    },
    "consistency": {
        "consistency", "duplicate_chunks", "duplicate_nodes",
        "semantic_boundaries",
    },
}


class EvaluationService:
    """Evaluate any AI operation by dispatching to the right evaluator."""

    def __init__(
        self,
        *,
        evaluators: Optional[Dict[AIModule, object]] = None,
        validator: Optional[EvaluationValidator] = None,
    ) -> None:
        if evaluators is not None:
            self._evaluators = evaluators
        else:
            retrieval = RetrievalEvaluator()
            self._evaluators = {
                AIModule.PROMPT: PromptEvaluator(),
                AIModule.CHUNKING: ChunkEvaluator(),
                AIModule.RETRIEVAL: retrieval,
                AIModule.VECTOR_STORE: retrieval,
                AIModule.LLM: ResponseEvaluator(),
                AIModule.KNOWLEDGE_GRAPH: GraphEvaluator(),
            }
        self._validator = validator or EvaluationValidator()

    def evaluate(self, request: EvaluationRequest) -> EvaluationResult:
        """Validate, dispatch to the module's evaluator, and return the result."""
        self._validator.validate(request, supported_modules=set(self._evaluators))
        evaluator = self._get_evaluator(request.module)

        start = time.perf_counter()
        result: Optional[EvaluationResult] = None
        error: Optional[BaseException] = None
        try:
            result = evaluator.evaluate(request)
            self._ensure_score_card(result)
            return result
        except EvaluationException as exc:
            error = exc
            raise
        except Exception as exc:  # noqa: BLE001 - translated to a domain error
            error = exc
            raise MetricCalculationException(
                f"Evaluation of module '{request.module.value}' failed: {exc}",
                details={"module": request.module.value},
                cause=exc,
            )
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            self._log(request, result, duration_ms, error)

    def evaluate_all(self, requests: List[EvaluationRequest]) -> List[EvaluationResult]:
        """Evaluate a batch of requests."""
        return [self.evaluate(request) for request in requests]

    # -- dispatch ----------------------------------------------------------

    def _get_evaluator(self, module: AIModule):
        evaluator = self._evaluators.get(module)
        if evaluator is None:
            available = ", ".join(m.value for m in self._evaluators)
            raise EvaluationException(
                f"No evaluator registered for module '{module.value}'. "
                f"Available: {available}.",
                details={"module": module.value},
            )
        return evaluator

    # -- score card --------------------------------------------------------

    def _ensure_score_card(self, result: EvaluationResult) -> None:
        """Guarantee the result carries a score card summarising its metrics."""
        dimensions = self._dimension_scores(result)
        if result.score_card is None:
            result.score_card = ScoreCard(
                accuracy=dimensions["accuracy"],
                consistency=dimensions["consistency"],
                completeness=dimensions["completeness"],
                overall=result.overall_score,
            )
        elif result.score_card.overall is None:
            result.score_card.overall = result.overall_score

    @staticmethod
    def _dimension_scores(result: EvaluationResult) -> Dict[str, Optional[float]]:
        buckets: Dict[str, List[float]] = {dim: [] for dim in _DIMENSION_KEYWORDS}
        for m in result.metrics:
            for dimension, names in _DIMENSION_KEYWORDS.items():
                if m.name in names:
                    buckets[dimension].append(m.score)
        return {
            dimension: round(sum(v) / len(v), 4) if v else None
            for dimension, v in buckets.items()
        }

    def _log(
        self,
        request: EvaluationRequest,
        result: Optional[EvaluationResult],
        duration_ms: float,
        error: Optional[BaseException],
    ) -> None:
        success = error is None
        log = logger.info if success else logger.error
        log(
            "Evaluation | module=%s request_id=%s | overall=%s passed=%s metrics=%s | "
            "duration_ms=%.1f | success=%s%s",
            request.module.value,
            request.request_id,
            result.overall_score if result else "n/a",
            result.passed if result else "n/a",
            result.metric_count if result else 0,
            duration_ms,
            success,
            f" | error={type(error).__name__}: {error}" if error else "",
        )


# Shared singleton — import this from other modules.
evaluation_service = EvaluationService()
