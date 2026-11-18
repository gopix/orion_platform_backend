"""Shared helpers for the knowledge-graph extractors (private).

Small, stateless bits reused across the entity/concept/relationship extractors:
a stopword set and an id slugifier.
"""
import re

# Common function words that should never be treated as entities/concepts.
STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "then", "of", "to", "in", "on",
    "at", "by", "for", "with", "as", "is", "are", "was", "were", "be", "been",
    "this", "that", "these", "those", "it", "its", "he", "she", "they", "we",
    "you", "i", "from", "into", "than", "such", "not", "no", "yes", "can", "will",
    "would", "should", "could", "may", "might", "also", "which", "who", "whom",
    "what", "when", "where", "why", "how", "there", "here", "their", "his", "her",
}

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(label: str) -> str:
    """Turn a label into a stable lowercase id (``"Laws Of Motion" -> "laws_of_motion"``)."""
    return _SLUG_RE.sub("_", (label or "").lower()).strip("_")
