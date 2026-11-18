"""Concept — an abstract concept node (an idea, not a nameable thing).

Examples: Force, Acceleration, Energy, Accessibility, WCAG. A specialised
``GraphNode`` with ``type = "concept"``. Concepts are deliberately different from
entities: they capture abstract notions rather than concrete named things. Data
model only — no behaviour.
"""
from typing import Optional

from src.modules.book_forge.ai.intelligence.knowledge_graph.models.graph_node import (
    GraphNode,
    NodeType,
)


class Concept(GraphNode):
    type: str = NodeType.CONCEPT.value
    # Optional domain the concept belongs to (e.g. "physics", "accessibility").
    domain: Optional[str] = None
