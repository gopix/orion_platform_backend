"""RelationshipExtractor — find relationships between nodes.

    Newton  --DISCOVERED-->  Gravity

This is the step where LLM assistance is most valuable. The baseline here is a
sentence-level co-occurrence heuristic: within each sentence, consecutive known
nodes are linked, and the connecting phrase is mapped to a ``RelationshipType``
(or the linking verb is used, e.g. "discovered" -> DISCOVERED). An LLM can later
replace ``extract`` for accurate relationship extraction behind the same
interface.
"""
import re
from typing import List, Optional

from src.modules.book_forge.ai.foundation.chunking.utils import SentenceExtractor
from src.modules.book_forge.ai.intelligence.knowledge_graph.extractors._common import (
    STOPWORDS,
)
from src.modules.book_forge.ai.intelligence.knowledge_graph.extractors.entity_extractor import (
    EntityExtractor,
)
from src.modules.book_forge.ai.intelligence.knowledge_graph.models import (
    GraphEdge,
    RelationshipType,
)

# Connecting phrases mapped to canonical relationship types.
_PHRASE_MAP = [
    ("is a", RelationshipType.IS_A),
    ("is an", RelationshipType.IS_A),
    ("are", RelationshipType.IS_A),
    ("part of", RelationshipType.PART_OF),
    ("depends on", RelationshipType.DEPENDS_ON),
    ("written by", RelationshipType.WRITTEN_BY),
    ("authored by", RelationshipType.WRITTEN_BY),
    ("explains", RelationshipType.EXPLAINS),
    ("causes", RelationshipType.CAUSES),
    ("caused", RelationshipType.CAUSES),
]
_VERB_RE = re.compile(r"[a-z]+")


class RelationshipExtractor:
    """Extract relationships between nodes from text (heuristic baseline)."""

    def __init__(self, entity_extractor: Optional[EntityExtractor] = None) -> None:
        self._entity_extractor = entity_extractor or EntityExtractor()

    def extract(
        self, text: str, *, node_labels: Optional[List[str]] = None
    ) -> List[GraphEdge]:
        """Return relationships found in ``text``.

        ``node_labels`` are the node names to relate; if omitted, entities are
        extracted from the text first.
        """
        labels = node_labels or [e.label for e in self._entity_extractor.extract(text)]
        if len(labels) < 2:
            return []

        edges: List[GraphEdge] = []
        seen: set = set()
        for sentence in SentenceExtractor.extract(text or ""):
            present = self._ordered_present(sentence, labels)
            for i in range(len(present) - 1):
                source, target = present[i], present[i + 1]
                rel = self._infer(sentence, source, target)
                signature = (source, target, rel)
                if signature in seen:
                    continue
                seen.add(signature)
                edges.append(
                    GraphEdge(source=source, target=target, relationship_type=rel)
                )
        return edges

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _ordered_present(sentence: str, labels: List[str]) -> List[str]:
        """Labels that appear in the sentence, ordered by position."""
        positions = {}
        for label in labels:
            idx = sentence.find(label)
            if idx != -1 and label not in positions:
                positions[label] = idx
        return sorted(positions, key=positions.get)

    def _infer(self, sentence: str, source: str, target: str) -> str:
        """Infer the relationship type from the text between two nodes."""
        start = sentence.find(source) + len(source)
        end = sentence.find(target, start)
        between = sentence[start:end].lower() if end != -1 else ""

        for phrase, rel in _PHRASE_MAP:
            if phrase in between:
                return rel.value

        # Otherwise use the first meaningful verb-like word (e.g. "discovered").
        for word in _VERB_RE.findall(between):
            if word not in STOPWORDS and len(word) > 2:
                return word.upper()

        return RelationshipType.RELATED_TO.value
