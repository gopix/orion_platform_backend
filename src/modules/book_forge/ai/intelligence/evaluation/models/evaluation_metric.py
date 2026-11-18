"""EvaluationMetric — one measured metric for an AI operation.

    Faithfulness   -> 0.94
    Chunk Coverage -> 0.89

A single named score (usually 0–1), optionally with a pass ``threshold`` and a
``weight`` for weighting into an overall score. Data model only — no behaviour.
"""
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, computed_field


class EvaluationMetric(BaseModel):
    # Metric name, e.g. "faithfulness", "chunk_coverage".
    name: str
    # The measured value (typically 0.0–1.0; higher is better).
    score: float
    # Pass threshold; when set, ``passed`` compares against it.
    threshold: Optional[float] = None
    # Relative weight when combining metrics into an overall score.
    weight: float = 1.0
    message: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"from_attributes": True}

    @computed_field  # included in model_dump() / JSON output
    @property
    def passed(self) -> bool:
        """True if no threshold is set, or the score meets it."""
        return self.threshold is None or self.score >= self.threshold
