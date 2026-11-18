"""InputValidator — validate raw user input before anything else runs.

Checks: empty prompt, oversized prompt, bad encoding (control/replacement
characters), and unsupported attached files. Returns one ``ValidationResult`` per
rule. Stateless and pure.
"""
from typing import List, Optional

from src.modules.book_forge.ai.intelligence.guardrails.models import (
    Severity,
    ValidationResult,
)
from src.modules.book_forge.ai.intelligence.guardrails.validators._common import (
    fail,
    ok,
)

# Control characters that shouldn't appear in text (excludes tab/newline/return).
_CONTROL_CHARS = set(range(0, 32)) - {9, 10, 13}
_DEFAULT_ALLOWED_FILES = {"pdf", "docx", "txt", "md", "epub"}


class InputValidator:
    """Validate raw input (prompt + attached files)."""

    def __init__(
        self,
        *,
        max_chars: int = 100_000,
        allowed_file_types: Optional[set] = None,
    ) -> None:
        self._max_chars = max_chars
        self._allowed = {
            t.lower() for t in (allowed_file_types or _DEFAULT_ALLOWED_FILES)
        }

    def validate(
        self, prompt: str, *, files: Optional[List[str]] = None
    ) -> List[ValidationResult]:
        results = [
            self._check_empty(prompt),
            self._check_size(prompt),
            self._check_encoding(prompt),
        ]
        if files is not None:
            results.append(self._check_files(files))
        return results

    def _check_empty(self, prompt: str) -> ValidationResult:
        if not prompt or not prompt.strip():
            return fail("empty_prompt", "Prompt is empty.", severity=Severity.HIGH)
        return ok("empty_prompt")

    def _check_size(self, prompt: str) -> ValidationResult:
        length = len(prompt or "")
        if length > self._max_chars:
            return fail(
                "prompt_size",
                f"Prompt is too large ({length} > {self._max_chars} chars).",
                details={"length": length, "max_chars": self._max_chars},
            )
        return ok("prompt_size")

    def _check_encoding(self, prompt: str) -> ValidationResult:
        text = prompt or ""
        if "�" in text or any(ord(ch) in _CONTROL_CHARS for ch in text):
            return fail(
                "encoding",
                "Prompt contains invalid or control characters.",
                severity=Severity.HIGH,
            )
        return ok("encoding")

    def _check_files(self, files: List[str]) -> ValidationResult:
        unsupported = [f for f in files if self._ext(f) not in self._allowed]
        if unsupported:
            return fail(
                "unsupported_files",
                f"Unsupported file types: {unsupported}.",
                details={"unsupported": unsupported, "allowed": sorted(self._allowed)},
            )
        return ok("unsupported_files")

    @staticmethod
    def _ext(filename: str) -> str:
        return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
