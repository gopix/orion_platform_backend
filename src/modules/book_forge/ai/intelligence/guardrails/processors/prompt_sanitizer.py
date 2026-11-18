"""PromptSanitizer — repair a prompt so it's safe to send.

A processor, not a validator: instead of flagging problems it *fixes* them —
normalising whitespace/encoding (via ``TextNormalizer``), neutralising known
injection phrases, and trimming to a maximum length. Returns the cleaned prompt.
Stateless and pure.
"""
import re
from typing import Optional

from src.modules.book_forge.ai.foundation.chunking.utils import TextNormalizer

_INJECTION_PATTERNS = [
    re.compile(r"ignore (all |the )?(previous|above|prior) (instructions|prompt)", re.I),
    re.compile(r"disregard (the |all )?(previous|above)", re.I),
    re.compile(r"forget (everything|all previous)", re.I),
    re.compile(r"reveal (your |the )?(system )?prompt", re.I),
    re.compile(r"developer mode", re.I),
    re.compile(r"jailbreak", re.I),
]
_REDACTION = "[filtered]"


class PromptSanitizer:
    """Clean and neutralise a prompt before use."""

    def __init__(self, *, max_chars: Optional[int] = None) -> None:
        self._max_chars = max_chars

    def sanitize(self, prompt: str) -> str:
        """Return a sanitised copy of ``prompt``."""
        if not prompt:
            return ""
        text = TextNormalizer.normalize(prompt)
        for pattern in _INJECTION_PATTERNS:
            text = pattern.sub(_REDACTION, text)
        text = text.strip()
        if self._max_chars is not None and len(text) > self._max_chars:
            text = text[: self._max_chars].rstrip()
        return text
