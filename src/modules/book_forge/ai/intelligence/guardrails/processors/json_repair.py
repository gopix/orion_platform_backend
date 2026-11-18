"""JsonRepair — recover valid JSON from messy LLM output, no re-prompt needed.

    LLM  ->  invalid JSON  ->  repair  ->  application

The most valuable processor: LLMs frequently return JSON wrapped in Markdown
fences, prefixed with prose, or with Python-isms (single quotes, ``True``/``None``,
trailing commas). This tries a series of increasingly aggressive fixes and parses
with both ``json`` and ``ast.literal_eval`` — turning near-JSON into real data
without another (slow, costly) LLM round-trip. Stateless and pure.
"""
import ast
import json
import re
from typing import Any, Optional

_FENCE_RE = re.compile(r"```[a-zA-Z0-9]*\s*(.*?)```", re.DOTALL)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


class JsonRepair:
    """Repair and parse messy JSON-ish text."""

    def try_repair(self, text: str) -> Optional[Any]:
        """Return the parsed object from ``text``, or ``None`` if unrecoverable."""
        if text is None:
            return None
        for candidate in self._candidates(text):
            parsed = self._parse(candidate)
            if parsed is not None:
                return parsed
        return None

    def repair(self, text: str) -> str:
        """Return valid JSON for ``text``; raises ``ValueError`` if unrecoverable."""
        parsed = self.try_repair(text)
        if parsed is None:
            raise ValueError("Could not repair text into valid JSON.")
        return json.dumps(parsed)

    def repair_or_default(self, text: str, default: Any = None) -> Any:
        """Return the parsed object, or ``default`` if unrecoverable."""
        parsed = self.try_repair(text)
        return default if parsed is None else parsed

    # -- internals ---------------------------------------------------------

    def _candidates(self, text: str):
        """Yield progressively more-repaired variants of ``text``."""
        raw = text.strip()
        yield raw

        # Content inside a Markdown code fence.
        fence = _FENCE_RE.search(raw)
        inner = fence.group(1).strip() if fence else raw
        if inner != raw:
            yield inner

        # The substring from the first bracket to its matching last bracket.
        extracted = self._extract_bracketed(inner)
        if extracted and extracted != inner:
            yield extracted

        base = extracted or inner
        # Remove trailing commas (invalid in JSON, common in LLM output).
        no_trailing = _TRAILING_COMMA_RE.sub(r"\1", base)
        if no_trailing != base:
            yield no_trailing

    @staticmethod
    def _extract_bracketed(text: str) -> Optional[str]:
        starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
        ends = [i for i in (text.rfind("}"), text.rfind("]")) if i != -1]
        if not starts or not ends:
            return None
        start, end = min(starts), max(ends)
        return text[start : end + 1] if end > start else None

    @staticmethod
    def _parse(candidate: str) -> Optional[Any]:
        if not candidate:
            return None
        # Strict JSON first (handles lowercase true/false/null).
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            pass
        # Python literal next (single quotes, True/False/None, trailing commas).
        try:
            return ast.literal_eval(candidate)
        except (ValueError, SyntaxError):
            return None
