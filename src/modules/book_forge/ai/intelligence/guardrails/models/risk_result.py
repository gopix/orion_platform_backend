"""RiskResult — the overall risk decision aggregated from many checks.

Individual validators/policies only report their own PASS/FAIL/WARNING; they know
nothing about overall risk. ``RiskCalculator`` combines them into this single
object so the application has *one* decision to act on::

    overall_risk -> 87
    level        -> HIGH
    decision     -> BLOCK

Data model only — the calculator fills it.
"""
from enum import Enum
from typing import Dict

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskDecision(str, Enum):
    ALLOW = "allow"
    REVIEW = "review"
    BLOCK = "block"


class RiskResult(BaseModel):
    # Overall risk score, 0–100.
    overall_risk: int = 0
    level: RiskLevel = RiskLevel.NONE
    decision: RiskDecision = RiskDecision.ALLOW
    # Per-rule risk contributions.
    risk_by_rule: Dict[str, int] = Field(default_factory=dict)

    model_config = {"from_attributes": True}
