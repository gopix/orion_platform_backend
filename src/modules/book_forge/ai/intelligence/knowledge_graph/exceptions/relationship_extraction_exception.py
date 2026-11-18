"""RelationshipExtractionException — extracting relationships failed.

Raised when the relationship-extraction step (inferring edges between entities)
fails. Wraps the underlying error as ``cause``.
"""
from src.modules.book_forge.ai.intelligence.knowledge_graph.exceptions.knowledge_graph_exception import (
    KnowledgeGraphException,
)


class RelationshipExtractionException(KnowledgeGraphException):
    """Raised when relationship extraction fails."""

    default_error_code = "KG-003"
    default_message = "Relationship extraction failed"
