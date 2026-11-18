"""EntityExtractor — find named entities in text.

Finds concrete, nameable things: Newton, India, OpenAI, WCAG. This baseline uses
a proper-noun / acronym heuristic (capitalised words, CamelCase, all-caps
acronyms), which is fast and dependency-free. LLM assistance can later replace or
augment ``extract`` for higher-accuracy NER and entity typing behind the same
interface.
"""
import re
from typing import List

from src.modules.book_forge.ai.intelligence.knowledge_graph.extractors._common import (
    STOPWORDS,
    slugify,
)
from src.modules.book_forge.ai.intelligence.knowledge_graph.models import Entity

# Capitalised words / CamelCase / acronyms, allowing multi-word proper nouns.
_PROPER_NOUN_RE = re.compile(r"\b([A-Z][a-zA-Z]*(?:\s+[A-Z][a-zA-Z]*)*)\b")


class EntityExtractor:
    """Extract named entities from text (heuristic baseline)."""

    def extract(self, text: str) -> List[Entity]:
        """Return the unique entities found in ``text``, in order of appearance."""
        found: dict = {}  # label -> Entity (preserves order, dedupes)
        for match in _PROPER_NOUN_RE.finditer(text or ""):
            label = match.group(1).strip()
            if self._is_noise(label):
                continue
            found.setdefault(label, Entity(id=slugify(label), label=label))
        return list(found.values())

    @staticmethod
    def _is_noise(label: str) -> bool:
        """Filter out sentence-initial function words wrongly capitalised."""
        if not label:
            return True
        # A single short capitalised word that's a common stopword (e.g. "The").
        if " " not in label and label.lower() in STOPWORDS:
            return True
        return False
