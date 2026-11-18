"""PromptValidator — guard the prompt itself before sending it to the LLM.

Checks: prompt-injection attempts, unsafe instructions, malformed structure, and
token limits. Returns one ``ValidationResult`` per rule. The pattern lists are a
heuristic baseline; an LLM/classifier can strengthen detection later behind the
same interface. Stateless and pure.
"""
import re
from typing import List

from src.modules.book_forge.ai.foundation.chunking.utils import TokenEstimator
from src.modules.book_forge.ai.intelligence.guardrails.models import (
    Severity,
    ValidationResult,
)
from src.modules.book_forge.ai.intelligence.guardrails.validators._common import (
    fail,
    ok,
    warn,
)

_INJECTION_PATTERNS = [
    r"ignore (all |the )?(previous|above|prior) (instructions|prompt)",
    r"disregard (the |all )?(previous|above)",
    r"forget (everything|all previous)",
    r"you are now",
    r"pretend (to be|you are)",
    r"developer mode",
    r"jailbreak",
    r"reveal (your |the )?(system )?prompt",
    r"print your instructions",
]
_UNSAFE_PATTERNS = [
    r"\brm\s+-rf\b",
    r"\bdrop\s+table\b",
    r"delete all",
    r"exfiltrate",
    r"disable (the )?(safety|guardrails)",
]


class PromptValidator:
    """Validate a prompt for safety and limits."""

    def __init__(self, *, max_tokens: int = 8000) -> None:
        self._max_tokens = max_tokens

    def validate(self, prompt: str) -> List[ValidationResult]:
        text = prompt or ""
        return [
            self._check_injection(text),
            self._check_unsafe(text),
            self._check_malformed(text),
            self._check_tokens(text),
        ]

    def _check_injection(self, text: str) -> ValidationResult:
        hits = [p for p in _INJECTION_PATTERNS if re.search(p, text, re.IGNORECASE)]
        if hits:
            return fail(
                "prompt_injection",
                "Possible prompt-injection phrasing detected.",
                severity=Severity.HIGH,
                details={"patterns": hits},
            )
        return ok("prompt_injection")

    def _check_unsafe(self, text: str) -> ValidationResult:
        hits = [p for p in _UNSAFE_PATTERNS if re.search(p, text, re.IGNORECASE)]
        if hits:
            return fail(
                "unsafe_instructions",
                "Unsafe instruction pattern detected.",
                severity=Severity.CRITICAL,
                details={"patterns": hits},
            )
        return ok("unsafe_instructions")

    def _check_malformed(self, text: str) -> ValidationResult:
        if not text.strip():
            return fail("malformed_prompt", "Prompt is empty.", severity=Severity.HIGH)
        if text.count("{") != text.count("}") or text.count("[") != text.count("]"):
            return warn("malformed_prompt", "Unbalanced brackets in prompt.")
        return ok("malformed_prompt")

    def _check_tokens(self, text: str) -> ValidationResult:
        tokens = TokenEstimator.estimate(text)
        if tokens > self._max_tokens:
            return fail(
                "token_limit",
                f"Prompt exceeds token limit ({tokens} > {self._max_tokens}).",
                details={"estimated_tokens": tokens, "max_tokens": self._max_tokens},
            )
        return ok("token_limit")
