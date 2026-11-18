"""ParagraphExtractor — split a document into paragraphs.

A paragraph is a run of text separated from its neighbours by one or more blank
lines. This utility does that one job and nothing else: no chunking decisions, no
sizing, no merging — it simply hands back the list of paragraphs so a strategy
can decide what to do with them. Stateless and pure: no I/O, no configuration.
"""
import re
from typing import List

# One or more blank lines separate paragraphs.
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")


class ParagraphExtractor:
    """Extract paragraphs (blank-line-separated blocks) from text."""

    @staticmethod
    def extract(text: str) -> List[str]:
        """Return the non-empty, stripped paragraphs of ``text`` in order."""
        if not text:
            return []
        return [p.strip() for p in _PARAGRAPH_SPLIT_RE.split(text) if p.strip()]
