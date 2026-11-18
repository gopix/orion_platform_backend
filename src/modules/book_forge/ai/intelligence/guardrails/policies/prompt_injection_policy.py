"""PromptInjectionPolicy — block prompt-injection / unsafe-instruction attempts.

Composes ``PromptValidator`` and keeps its injection and unsafe-instruction
checks, rolling them up into a single policy result.
"""
from typing import Optional

from src.modules.book_forge.ai.intelligence.guardrails.models import (
    GuardrailRequest,
    PolicyResult,
)
from src.modules.book_forge.ai.intelligence.guardrails.policies.base_policy import (
    BasePolicy,
)
from src.modules.book_forge.ai.intelligence.guardrails.validators import (
    PromptValidator,
)

_RELEVANT_RULES = {"prompt_injection", "unsafe_instructions"}


class PromptInjectionPolicy(BasePolicy):
    """Guard against prompt injection and unsafe instructions in the prompt."""

    name = "prompt_injection"

    def __init__(self, validator: Optional[PromptValidator] = None) -> None:
        self._validator = validator or PromptValidator()

    def evaluate(self, request: GuardrailRequest) -> PolicyResult:
        results = [
            r
            for r in self._validator.validate(request.prompt or "")
            if r.rule in _RELEVANT_RULES
        ]
        return self._finalize(results)
