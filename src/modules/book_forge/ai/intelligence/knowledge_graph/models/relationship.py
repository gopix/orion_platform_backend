"""RelationshipType — the vocabulary of semantic relationships between nodes.

The canonical set of edge relationship types the graph uses. ``GraphEdge`` stores
``relationship_type`` as a string so extraction can emit custom kinds too, but
these are the well-known values callers should prefer.
"""
from enum import Enum


class RelationshipType(str, Enum):
    IS_A = "IS_A"
    PART_OF = "PART_OF"
    CAUSES = "CAUSES"
    EXPLAINS = "EXPLAINS"
    WRITTEN_BY = "WRITTEN_BY"
    DEPENDS_ON = "DEPENDS_ON"
    RELATED_TO = "RELATED_TO"
