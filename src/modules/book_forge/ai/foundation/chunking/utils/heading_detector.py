"""HeadingDetector — decide whether a line of text is a heading.

One of the most reused utilities: heading-aware chunking, table-of-contents
extraction, and outline building all need the same question answered — *is this
line a heading, and at what level?*

Today it recognises Markdown ATX headings (``#`` .. ``######``) precisely, and
offers a conservative heuristic for unmarked headings (short, title-like lines
with no terminal punctuation) that plain-text and OCR documents produce. The
design leaves room to add DOCX style names, PDF outline levels, or OCR cues later
behind the same interface. Stateless and pure: no I/O, no configuration.
"""
import re
from typing import NamedTuple, Optional

# Markdown ATX heading: 1–6 leading '#', a space, a title, optional closing '#'s.
_ATX_RE = re.compile(r"^(#{1,6})\s+(\S.*?)\s*#*\s*$")
# A line ending in sentence/clause punctuation is prose, not a heading.
_TERMINAL_PUNCT = (".", ",", ";", ":", "!", "?")
# Heuristic bounds for an unmarked heading.
_MAX_HEADING_WORDS = 12
_MAX_HEADING_CHARS = 80


class Heading(NamedTuple):
    """A detected heading. ``level`` is ``None`` when it can't be determined."""

    level: Optional[int]
    text: str
    source: str  # "markdown" | "heuristic"


class HeadingDetector:
    """Detect document headings from a single line of text."""

    @staticmethod
    def detect(line: str, *, allow_heuristic: bool = False) -> Optional[Heading]:
        """Return a :class:`Heading` if ``line`` is one, else ``None``.

        Markdown headings are always recognised. Unmarked (structureless)
        headings are only considered when ``allow_heuristic`` is true.
        """
        markdown = HeadingDetector._detect_markdown(line)
        if markdown is not None:
            return markdown
        if allow_heuristic and HeadingDetector._looks_like_heading(line):
            return Heading(level=None, text=line.strip(), source="heuristic")
        return None

    @staticmethod
    def is_heading(line: str, *, allow_heuristic: bool = False) -> bool:
        """True if ``line`` is a heading."""
        return HeadingDetector.detect(line, allow_heuristic=allow_heuristic) is not None

    @staticmethod
    def heading_level(line: str) -> Optional[int]:
        """Return the Markdown heading level (1–6), or ``None`` if not ATX."""
        markdown = HeadingDetector._detect_markdown(line)
        return markdown.level if markdown is not None else None

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _detect_markdown(line: str) -> Optional[Heading]:
        match = _ATX_RE.match(line.rstrip())
        if not match:
            return None
        return Heading(
            level=len(match.group(1)),
            text=match.group(2).strip(),
            source="markdown",
        )

    @staticmethod
    def _looks_like_heading(line: str) -> bool:
        """Conservative guess for an unmarked heading line."""
        stripped = line.strip()
        if not stripped:
            return False
        if stripped.endswith(_TERMINAL_PUNCT):
            return False
        if len(stripped) > _MAX_HEADING_CHARS:
            return False
        if len(stripped.split()) > _MAX_HEADING_WORDS:
            return False
        return True
