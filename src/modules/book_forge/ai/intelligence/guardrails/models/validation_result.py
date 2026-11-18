"""ValidationResult — the outcome of one guardrail rule check.

    rule      -> "PII"
    status    -> PASS / FAIL / WARNING
    severity  -> how serious a failure is
    message   -> human-readable explanation

The atomic unit of guardrail output; policies and the overall response aggregate
these. Data model only — no behaviour.
"""
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, computed_field


class ValidationStatus(str, Enum):
    """Outcome of a single check (also reused for policy outcomes)."""

    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning"


class Severity(str, Enum):
    """How serious a failed/flagged check is."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ValidationResult(BaseModel):
    # The rule that was checked, e.g. "PII", "toxicity", "max_length".
    rule: str
    status: ValidationStatus
    severity: Severity = Severity.LOW
    message: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"from_attributes": True}

    @computed_field  # included in model_dump() / JSON output
    @property
    def passed(self) -> bool:
        return self.status == ValidationStatus.PASS
