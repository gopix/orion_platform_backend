"""OutputLengthPolicy — enforce length bounds on generated output.

Checks the output against optional minimum/maximum character and token limits.
Too-short output (e.g. a truncated or refused generation) and too-long output are
both flagged. Token estimates reuse the shared ``TokenEstimator``.
"""
from typing import List, Optional

from src.modules.book_forge.ai.foundation.chunking.utils import TokenEstimator
from src.modules.book_forge.ai.intelligence.guardrails.models import (
    GuardrailRequest,
    PolicyResult,
    Severity,
    ValidationResult,
)
from src.modules.book_forge.ai.intelligence.guardrails.policies.base_policy import (
    BasePolicy,
)


class OutputLengthPolicy(BasePolicy):
    """Enforce character/token length bounds on output."""

    name = "output_length"

    def __init__(
        self,
        *,
        min_chars: Optional[int] = None,
        max_chars: Optional[int] = None,
        min_tokens: Optional[int] = None,
        max_tokens: Optional[int] = None,
    ) -> None:
        self._min_chars = min_chars
        self._max_chars = max_chars
        self._min_tokens = min_tokens
        self._max_tokens = max_tokens

    def evaluate(self, request: GuardrailRequest) -> PolicyResult:
        text = request.output or ""
        length = len(text)
        tokens = TokenEstimator.estimate(text)
        results: List[ValidationResult] = []

        results.extend(self._bounds("length_chars", length, self._min_chars, self._max_chars, "characters"))
        results.extend(self._bounds("length_tokens", tokens, self._min_tokens, self._max_tokens, "tokens"))

        if not results:
            results.append(self._ok("output_length"))
        return self._finalize(results)

    def _bounds(
        self,
        rule: str,
        value: int,
        minimum: Optional[int],
        maximum: Optional[int],
        unit: str,
    ) -> List[ValidationResult]:
        results: List[ValidationResult] = []
        if minimum is not None and value < minimum:
            results.append(
                self._fail(
                    rule,
                    f"Output too short: {value} {unit} < minimum {minimum}.",
                    severity=Severity.MEDIUM,
                    details={"value": value, "min": minimum, "unit": unit},
                )
            )
        if maximum is not None and value > maximum:
            results.append(
                self._fail(
                    rule,
                    f"Output too long: {value} {unit} > maximum {maximum}.",
                    severity=Severity.MEDIUM,
                    details={"value": value, "max": maximum, "unit": unit},
                )
            )
        return results
