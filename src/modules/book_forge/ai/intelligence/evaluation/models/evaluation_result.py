"""EvaluationResult — the outcome of evaluating one AI operation.

Bundles the individual metrics with an overall score, a pass/fail verdict, an
optional score card, actionable recommendations, and how long evaluation took —
so every AI improvement becomes measurable rather than subjective. Data model
only — the evaluator fills these fields.
"""
from typing import List, Optional

from pydantic import BaseModel, Field, computed_field

from src.modules.book_forge.ai.intelligence.evaluation.models.evaluation_metric import (
    EvaluationMetric,
)
from src.modules.book_forge.ai.intelligence.evaluation.models.evaluation_request import (
    AIModule,
)
from src.modules.book_forge.ai.intelligence.evaluation.models.score_card import (
    ScoreCard,
)


class EvaluationResult(BaseModel):
    module: Optional[AIModule] = None
    # Aggregate score across metrics (typically 0.0–1.0).
    overall_score: float = 0.0
    passed: bool = False

    metrics: List[EvaluationMetric] = Field(default_factory=list)
    score_card: Optional[ScoreCard] = None
    recommendations: List[str] = Field(default_factory=list)
    execution_time_ms: Optional[float] = None

    model_config = {"from_attributes": True}

    @computed_field  # included in model_dump() / JSON output
    @property
    def metric_count(self) -> int:
        return len(self.metrics)
