"""GuardrailResponse — the aggregated result of guardrail validation.

Guardrails don't just reject — they can *repair*. So the response reports whether
the content is ``allowed``, the ``violations`` and ``warnings`` found, and any
``modified_prompt`` / ``modified_output`` the guardrails produced (e.g. PII
redacted). Data model only — the service fills these fields.
"""
from typing import List, Optional

from pydantic import BaseModel, Field, computed_field

from src.modules.book_forge.ai.intelligence.guardrails.models.policy_result import (
    PolicyResult,
)
from src.modules.book_forge.ai.intelligence.guardrails.models.risk_result import (
    RiskResult,
)
from src.modules.book_forge.ai.intelligence.guardrails.models.validation_result import (
    ValidationResult,
)


class GuardrailResponse(BaseModel):
    # Whether the content is permitted to proceed.
    allowed: bool = True
    # Failed checks (blocking) and non-blocking flags.
    violations: List[ValidationResult] = Field(default_factory=list)
    warnings: List[ValidationResult] = Field(default_factory=list)
    # Repaired content, when guardrails modified rather than rejected.
    modified_prompt: Optional[str] = None
    modified_output: Optional[str] = None
    # Per-policy roll-ups.
    policy_results: List[PolicyResult] = Field(default_factory=list)
    # Aggregated overall risk decision (computed by the RiskCalculator).
    risk: Optional[RiskResult] = None

    model_config = {"from_attributes": True}

    @computed_field  # included in model_dump() / JSON output
    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0

    @computed_field
    @property
    def was_modified(self) -> bool:
        return self.modified_prompt is not None or self.modified_output is not None
