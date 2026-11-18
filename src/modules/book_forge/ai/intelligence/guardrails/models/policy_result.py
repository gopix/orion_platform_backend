"""PolicyResult — the outcome of a policy (a group of related rule checks).

A policy bundles several ``ValidationResult`` checks under one name (e.g. a
"safety" policy running PII + toxicity rules) and rolls them up to a single
PASS / FAIL / WARNING. Data model only — no behaviour.
"""
from typing import List, Optional

from pydantic import BaseModel, Field

from src.modules.book_forge.ai.intelligence.guardrails.models.validation_result import (
    ValidationResult,
    ValidationStatus,
)


class PolicyResult(BaseModel):
    # The policy name, e.g. "safety", "compliance".
    policy: str
    status: ValidationStatus
    message: Optional[str] = None
    # The individual rule results that make up this policy's outcome.
    results: List[ValidationResult] = Field(default_factory=list)

    model_config = {"from_attributes": True}
