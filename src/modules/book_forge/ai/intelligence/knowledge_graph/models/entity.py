"""Entity — a named entity node (a concrete, nameable thing).

Examples: a Person, Organization, Location, Book, Author, Country. A specialised
``GraphNode`` with ``type = "entity"`` and an ``entity_type`` classification.
Distinct from ``Concept`` (abstract ideas). Data model only — no behaviour.
"""
from enum import Enum

from src.modules.book_forge.ai.intelligence.knowledge_graph.models.graph_node import (
    GraphNode,
    NodeType,
)


class EntityType(str, Enum):
    """Kinds of named entity."""

    PERSON = "person"
    ORGANIZATION = "organization"
    LOCATION = "location"
    COUNTRY = "country"
    BOOK = "book"
    AUTHOR = "author"
    DATE = "date"
    EVENT = "event"
    OTHER = "other"


class Entity(GraphNode):
    type: str = NodeType.ENTITY.value
    entity_type: EntityType = EntityType.OTHER
