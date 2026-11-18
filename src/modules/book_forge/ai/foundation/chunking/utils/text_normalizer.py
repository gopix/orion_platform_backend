"""TextNormalizer — clean raw document text into a canonical form.

Every strategy should operate on normalized text so that heading detection,
paragraph splitting, and token estimation behave predictably regardless of where
the document came from (pasted text, Windows files, PDF/OCR extraction, ...).

Normalization is intentionally structure-preserving: horizontal whitespace is
collapsed and junk characters are removed, but blank lines (paragraph breaks) and
single newlines (potential heading boundaries) are kept so downstream utilities
still see the document's shape. Stateless and pure: no I/O, no configuration.
"""
import re
import unicodedata

# Zero-width and other invisible characters that add nothing but break matching.
_INVISIBLE_CHARS = (
    "​"  # zero-width space
    "‌"  # zero-width non-joiner
    "‍"  # zero-width joiner
    "⁠"  # word joiner
    "﻿"  # BOM / zero-width no-break space
    "­"  # soft hyphen
)
_INVISIBLE_RE = re.compile(f"[{_INVISIBLE_CHARS}]")
# Unicode spaces (non-breaking, thin, etc.) that should read as a plain space.
_UNICODE_SPACE_RE = re.compile(r"[  -   　\t\f\v]")
# Runs of spaces to collapse (newlines deliberately excluded).
_MULTISPACE_RE = re.compile(r" {2,}")
# Three or more blank lines collapse to a single blank line (one paragraph break).
_MULTINEWLINE_RE = re.compile(r"\n{3,}")


class TextNormalizer:
    """Normalize unicode, line endings, invisible characters, and whitespace."""

    @staticmethod
    def normalize(text: str, *, unicode_form: str = "NFC") -> str:
        """Return a cleaned, canonical version of ``text``."""
        if not text:
            return ""
        text = TextNormalizer.normalize_unicode(text, form=unicode_form)
        text = TextNormalizer.normalize_line_endings(text)
        text = TextNormalizer.remove_invisible(text)
        text = TextNormalizer.normalize_whitespace(text)
        return text.strip()

    @staticmethod
    def normalize_unicode(text: str, *, form: str = "NFC") -> str:
        """Apply Unicode normalization (NFC by default)."""
        return unicodedata.normalize(form, text)

    @staticmethod
    def normalize_line_endings(text: str) -> str:
        """Convert Windows/Mac line endings to Unix ``\\n``."""
        return text.replace("\r\n", "\n").replace("\r", "\n")

    @staticmethod
    def remove_invisible(text: str) -> str:
        """Strip zero-width and other invisible characters."""
        return _INVISIBLE_RE.sub("", text)

    @staticmethod
    def normalize_whitespace(text: str) -> str:
        """Collapse horizontal whitespace while preserving line structure.

        Tabs and unicode spaces become plain spaces, runs of spaces collapse to
        one, trailing spaces are trimmed per line, and 3+ blank lines collapse to
        a single paragraph break.
        """
        text = _UNICODE_SPACE_RE.sub(" ", text)
        text = _MULTISPACE_RE.sub(" ", text)
        # Trim trailing spaces on each line.
        text = "\n".join(line.rstrip() for line in text.split("\n"))
        text = _MULTINEWLINE_RE.sub("\n\n", text)
        return text
