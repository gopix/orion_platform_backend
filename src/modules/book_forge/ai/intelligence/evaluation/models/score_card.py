"""ScoreCard — a high-level summary of quality across standard dimensions.

Rolls many individual metrics up into a handful of headline scores so results are
comparable across modules and over time::

    Accuracy      0.92
    Safety        0.99
    Consistency   0.88
    Completeness  0.90
    ------------------
    Overall       0.92

Each dimension is 0–1. Data model only — the evaluator fills it.
"""
from typing import List, Optional

from pydantic import BaseModel, computed_field


class ScoreCard(BaseModel):
    accuracy: Optional[float] = None
    safety: Optional[float] = None
    consistency: Optional[float] = None
    completeness: Optional[float] = None
    # Headline score; if unset, ``mean_dimension`` gives the average of the rest.
    overall: Optional[float] = None

    model_config = {"from_attributes": True}

    @computed_field  # included in model_dump() / JSON output
    @property
    def mean_dimension(self) -> Optional[float]:
        """Average of the provided dimension scores (ignoring ``overall``)."""
        values: List[float] = [
            v
            for v in (self.accuracy, self.safety, self.consistency, self.completeness)
            if v is not None
        ]
        return round(sum(values) / len(values), 4) if values else None
