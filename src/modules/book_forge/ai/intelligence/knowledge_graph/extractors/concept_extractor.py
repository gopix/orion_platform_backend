"""ConceptExtractor — find abstract concepts in text.

Finds ideas rather than named things: force, gravity, machine learning,
accessibility. This baseline treats significant lowercase content words as
concept candidates (proper nouns are left to ``EntityExtractor``), which is a
rough but useful default. LLM assistance can later provide far better concept
detection (including multi-word and capitalised concepts) behind the same
interface.
"""
import re
from typing import List, Optional

from src.modules.book_forge.ai.intelligence.knowledge_graph.extractors._common import (
    STOPWORDS,
)
from src.modules.book_forge.ai.intelligence.knowledge_graph.models import Concept

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z\-]+")
_MIN_LENGTH = 4


class ConceptExtractor:
    """Extract abstract concepts from text (heuristic baseline)."""

    def __init__(self, *, min_length: int = _MIN_LENGTH) -> None:
        self._min_length = min_length

    def extract(self, text: str, *, domain: Optional[str] = None) -> List[Concept]:
        """Return the unique concepts found in ``text``, in order of appearance.

        ``domain`` (e.g. "physics") is attached to each concept when given.
        """
        found: dict = {}  # lowercase term -> Concept
        for token in _WORD_RE.findall(text or ""):
            # Proper nouns are entities, not concepts.
            if token[0].isupper():
                continue
            term = token.lower()
            if len(term) < self._min_length or term in STOPWORDS:
                continue
            found.setdefault(term, Concept(id=term, label=term, domain=domain))
        return list(found.values())
