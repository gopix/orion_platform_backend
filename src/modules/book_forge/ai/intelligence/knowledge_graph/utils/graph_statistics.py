"""GraphStatistics — summary metrics for a knowledge graph.

Totals up nodes, edges, and per-type counts (entities vs concepts, relationships)
— handy for dashboards and monitoring. Works on lightweight node/edge dicts
(``{"id", "type", "name"}`` / ``{"source", "target", "type"}``) so it doesn't
depend on graph models that don't exist yet. Stateless and pure.
"""
from collections import Counter
from typing import Any, Dict, List

from src.modules.book_forge.ai.intelligence.knowledge_graph.utils._access import (
    get_field,
)


class GraphStatistics:
    """Compute summary statistics over a knowledge graph."""

    @staticmethod
    def calculate(
        nodes: List[Any], edges: List[Any]
    ) -> Dict[str, Any]:
        """Return node/edge totals and per-type node counts."""
        type_counts: Counter = Counter()
        for node in nodes:
            node_type = (get_field(node, "type") or "unknown")
            type_counts[str(node_type).lower()] += 1

        return {
            "nodes": len(nodes),
            "edges": len(edges),
            "entity_count": type_counts.get("entity", 0),
            "concept_count": type_counts.get("concept", 0),
            # Relationships are the graph's edges.
            "relationship_count": len(edges),
            # Full per-type breakdown for anything beyond entity/concept.
            "node_types": dict(type_counts),
        }
