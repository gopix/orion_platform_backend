"""EntityExtractionException — extracting entities from content failed.

Raised when the entity-extraction step (LLM/NLP call, parsing its output, ...)
fails. Wraps the underlying error as ``cause`` so callers see a knowledge-graph
exception rather than a raw dependency error.
"""
from src.modules.book_forge.ai.intelligence.knowledge_graph.exceptions.knowledge_graph_exception import (
    KnowledgeGraphException,
)


class EntityExtractionException(KnowledgeGraphException):
    """Raised when entity extraction fails."""

    default_error_code = "KG-002"
    default_message = "Entity extraction failed"
