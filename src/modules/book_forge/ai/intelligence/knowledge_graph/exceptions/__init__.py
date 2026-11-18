"""Knowledge graph exception types.

    KnowledgeGraphException  (base)
      ├── EntityExtractionException          (entity extraction failed)
      ├── RelationshipExtractionException    (relationship extraction failed)
      └── GraphValidationException           (assembled graph is invalid)
"""
from src.modules.book_forge.ai.intelligence.knowledge_graph.exceptions.entity_extraction_exception import (
    EntityExtractionException,
)
from src.modules.book_forge.ai.intelligence.knowledge_graph.exceptions.graph_validation_exception import (
    GraphValidationException,
)
from src.modules.book_forge.ai.intelligence.knowledge_graph.exceptions.knowledge_graph_exception import (
    KnowledgeGraphException,
)
from src.modules.book_forge.ai.intelligence.knowledge_graph.exceptions.relationship_extraction_exception import (
    RelationshipExtractionException,
)

__all__ = [
    "KnowledgeGraphException",
    "EntityExtractionException",
    "RelationshipExtractionException",
    "GraphValidationException",
]
