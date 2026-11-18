"""KnowledgeGraph — the complete graph, the output of the module.

Bundles the nodes and edges with free-form metadata (source document, project,
build info). Nodes are annotated ``SerializeAsAny`` so specialised nodes
(``Entity`` / ``Concept``) keep their extra fields when the graph is serialised.
Data model only — no behaviour.
"""
from typing import Any, Dict, List

from pydantic import BaseModel, Field, SerializeAsAny

from src.modules.book_forge.ai.intelligence.knowledge_graph.models.graph_edge import (
    GraphEdge,
)
from src.modules.book_forge.ai.intelligence.knowledge_graph.models.graph_node import (
    GraphNode,
)


class KnowledgeGraph(BaseModel):
    nodes: List[SerializeAsAny[GraphNode]] = Field(default_factory=list)
    edges: List[GraphEdge] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"from_attributes": True}
