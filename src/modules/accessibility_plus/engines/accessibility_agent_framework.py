from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any


class BaseAccessibilityAgent(ABC):
    agent_code: str = "BASE_AGENT"
    supported_checks: set[str] = set()

    def __init__(self, agent_code: str | None = None):
        if agent_code:
            self.agent_code = agent_code

    @abstractmethod
    def run_check(self, check_code: str, context: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    