"""PublisherPolicy — enforce publisher content rules on generated output.

Example rule: every chapter must contain a "Learning Objectives" section. The
policy splits the output into chapters (by heading) and flags any chapter missing
the required phrase as a violation. Both the required phrase and the chapter
heading pattern are configurable.
"""
import re
from typing import List, Optional, Tuple

from src.modules.book_forge.ai.intelligence.guardrails.models import (
    GuardrailRequest,
    PolicyResult,
    Severity,
)
from src.modules.book_forge.ai.intelligence.guardrails.policies.base_policy import (
    BasePolicy,
)

# Markdown headings or "Chapter N" lines start a new chapter.
_DEFAULT_CHAPTER_RE = re.compile(
    r"^(?:#{1,6}\s+.*|chapter\s+\w+.*)$", re.IGNORECASE | re.MULTILINE
)


class PublisherPolicy(BasePolicy):
    """Enforce per-chapter publisher requirements on output."""

    name = "publisher"

    def __init__(
        self,
        *,
        required_phrase: str = "Learning Objectives",
        chapter_pattern: Optional[re.Pattern] = None,
    ) -> None:
        self._required_phrase = required_phrase
        self._chapter_re = chapter_pattern or _DEFAULT_CHAPTER_RE

    def evaluate(self, request: GuardrailRequest) -> PolicyResult:
        text = request.output or ""
        chapters = self._split_chapters(text)

        if not chapters:
            # Nothing chapter-like to check; treat as a non-blocking warning.
            return self._finalize(
                [self._warn("chapters", "No chapters found in output to check.")]
            )

        needle = self._required_phrase.lower()
        results = []
        for title, body in chapters:
            if needle in body.lower():
                results.append(self._ok("learning_objectives", f"'{title}' OK"))
            else:
                results.append(
                    self._fail(
                        "learning_objectives",
                        f"Chapter '{title}' is missing '{self._required_phrase}'.",
                        severity=Severity.MEDIUM,
                        details={"chapter": title},
                    )
                )
        return self._finalize(results)

    def _split_chapters(self, text: str) -> List[Tuple[str, str]]:
        """Split text into (heading, body) chapters by the heading pattern."""
        headings = list(self._chapter_re.finditer(text))
        chapters: List[Tuple[str, str]] = []
        for index, match in enumerate(headings):
            title = match.group(0).lstrip("# ").strip()
            start = match.end()
            end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
            chapters.append((title, text[start:end]))
        return chapters
