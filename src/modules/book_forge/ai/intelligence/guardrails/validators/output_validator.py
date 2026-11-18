"""OutputValidator — validate LLM output before it's used or 
shown.

Checks: toxic content, required sections present, publisher rules (banned terms),
and basic formatting. Returns one ``ValidationResult`` per rule. Toxic/banned
term lists are a heuristic baseline; a moderation model can strengthen this later
behind the same interface. Stateless and pure.
"""
import re
from typing import List, Optional

from src.modules.book_forge.ai.intelligence.guardrails.models import (
    Severity,
    ValidationResult,
)
from src.modules.book_forge.ai.intelligence.guardrails.validators._common import (
    fail,
    ok,
)

# Minimal, non-exhaustive default indicators; override via constructor.
_DEFAULT_TOXIC_TERMS = {"hate", "kill", "violence", "abuse"}


class OutputValidator:
    """Validate generated output for safety, completeness, and formatting."""

    def __init__(
        self,
        *,
        toxic_terms: Optional[set] = None,
        banned_terms: Optional[set] = None,
        max_length: Optional[int] = None,
    ) -> None:
        self._toxic = {t.lower() for t in (toxic_terms or _DEFAULT_TOXIC_TERMS)}
        self._banned = {t.lower() for t in (banned_terms or set())}
        self._max_length = max_length

    def validate(
        self, output: str, *, required_sections: Optional[List[str]] = None
    ) -> List[ValidationResult]:
        text = output or ""
        results = [
            self._check_toxic(text),
            self._check_publisher_rules(text),
            self._check_formatting(text),
        ]
        if required_sections is not None:
            results.append(self._check_sections(text, required_sections))
        return results

    @staticmethod
    def _contains_word(text: str, term: str) -> bool:
        """Whole-word match, so 'kill' does not match 'skills' nor 'hate'
        'phosphate'."""
        return re.search(rf"\b{re.escape(term)}\b", text) is not None

    def _check_toxic(self, text: str) -> ValidationResult:
        lowered = text.lower()
        hits = sorted(term for term in self._toxic if self._contains_word(lowered, term))
        if hits:
            return fail(
                "toxic_content",
                "Output contains potentially toxic terms.",
                severity=Severity.HIGH,
                details={"terms": hits},
            )
        return ok("toxic_content")

    def _check_sections(
        self, text: str, required_sections: List[str]
    ) -> ValidationResult:
        lowered = text.lower()
        missing = [s for s in required_sections if s.lower() not in lowered]
        if missing:
            return fail(
                "missing_sections",
                f"Output is missing required sections: {missing}.",
                details={"missing": missing},
            )
        return ok("missing_sections")

    def _check_publisher_rules(self, text: str) -> ValidationResult:
        if not self._banned:
            return ok("publisher_rules")
        lowered = text.lower()
        hits = sorted(term for term in self._banned if self._contains_word(lowered, term))
        if hits:
            return fail(
                "publisher_rules",
                "Output violates publisher rules (banned terms).",
                severity=Severity.MEDIUM,
                details={"terms": hits},
            )
        return ok("publisher_rules")

    def _check_formatting(self, text: str) -> ValidationResult:
        if not text.strip():
            return fail("formatting", "Output is empty.", severity=Severity.HIGH)
        if self._max_length is not None and len(text) > self._max_length:
            return fail(
                "formatting",
                f"Output exceeds max length ({len(text)} > {self._max_length}).",
                details={"length": len(text), "max_length": self._max_length},
            )
        return ok("formatting")
