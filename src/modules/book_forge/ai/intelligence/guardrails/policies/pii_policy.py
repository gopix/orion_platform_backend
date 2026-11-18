"""PIIPolicy — flag personally identifiable information in prompt/output.

Detects emails, phone numbers, US SSNs, and credit-card-like numbers via regex.
Any hit is a HIGH-severity violation. Heuristic baseline — a dedicated PII model
can strengthen detection later behind the same interface.
"""
import re
from typing import Dict, List

from src.modules.book_forge.ai.intelligence.guardrails.models import (
    GuardrailRequest,
    PolicyResult,
    Severity,
)
from src.modules.book_forge.ai.intelligence.guardrails.policies.base_policy import (
    BasePolicy,
)

_PII_PATTERNS = {
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    "phone": re.compile(r"\b\+?\d[\d\s().-]{7,}\d\b"),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "credit_card": re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
}


class PIIPolicy(BasePolicy):
    """Detect PII in the request's prompt and output."""

    name = "pii"

    def evaluate(self, request: GuardrailRequest) -> PolicyResult:
        text = "\n".join(t for t in (request.prompt, request.output) if t)
        found: Dict[str, int] = {}
        for label, pattern in _PII_PATTERNS.items():
            matches = pattern.findall(text)
            if matches:
                found[label] = len(matches)

        if found:
            result = self._fail(
                "PII",
                f"Detected potential PII: {', '.join(sorted(found))}.",
                severity=Severity.HIGH,
                details={"found": found},
            )
        else:
            result = self._ok("PII")
        return self._finalize([result])
