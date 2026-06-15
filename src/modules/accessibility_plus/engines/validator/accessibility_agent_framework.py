from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any

from src.modules.accessibility_plus.models.validation_issue import ValidationIssue


class BaseAccessibilityValidatorAgent(ABC):
    agent_code: str 
    agent_name: str
    category: str

    supported_checks: set[str]

    severity_levels: set[str] = {
    "CRITICAL",
    "HIGH",
    "MEDIUM",
    "LOW"
}

    @abstractmethod
    def run_check(
        self,
        check_code: str,
        context: dict
    ) -> ValidationIssue:
        pass

    