"""OutputCleaner — tidy raw LLM output before it's used.

A processor: it repairs common LLM output noise — Markdown code fences, chatty
preambles ("Sure, here's..."), stray surrounding quotes, and messy whitespace
(via ``TextNormalizer``). Returns the cleaned text. Stateless and pure.
"""
import re

from src.modules.book_forge.ai.foundation.chunking.utils import TextNormalizer

# ```lang ... ``` fenced blocks — keep the inner content (may appear anywhere).
_FENCE_RE = re.compile(r"```[a-zA-Z0-9]*\s*\n?(.*?)\n?```", re.DOTALL)
# Chatty lead-ins at the very start.
_PREAMBLE_RE = re.compile(
    r"^\s*(sure|certainly|of course|here(?:'s| is| are)|absolutely)\b[^\n:]*:?\s*",
    re.IGNORECASE,
)


class OutputCleaner:
    """Strip fences, preambles, quotes, and whitespace from output."""

    def clean(self, output: str) -> str:
        """Return a cleaned copy of ``output``."""
        if not output:
            return ""
        text = output.strip()

        # Drop a chatty lead-in first, then lift content out of a code fence
        # wherever it appears.
        text = _PREAMBLE_RE.sub("", text)
        fenced = _FENCE_RE.search(text)
        if fenced:
            text = fenced.group(1)

        text = TextNormalizer.normalize(text)
        text = self._strip_wrapping_quotes(text)
        return text.strip()

    @staticmethod
    def _strip_wrapping_quotes(text: str) -> str:
        for quote in ('"""', "'''", '"', "'", "`"):
            if len(text) >= 2 * len(quote) and text.startswith(quote) and text.endswith(quote):
                return text[len(quote):-len(quote)].strip()
        return text
