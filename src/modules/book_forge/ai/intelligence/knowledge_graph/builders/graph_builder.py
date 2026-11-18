"""GraphBuilder — assemble extracted entities/concepts/relationships into a graph.

Once extraction is done, the builder does the assembly work:

    merge duplicate nodes  ->  ensure ids  ->  build & remap edges
    ->  return KnowledgeGraph

Merging happens at the model level so specialised nodes (``Entity`` / ``Concept``)
keep their type and extra fields. Because relationship extraction refers to nodes
by label while nodes carry slug ids, the builder remaps each edge endpoint (label
*or* id) onto the surviving canonical node id, and drops duplicate edges.
Stateless — no I/O.
"""
import re
from typing import Dict, List, Optional, Tuple

from src.modules.book_forge.ai.intelligence.knowledge_graph.models import (
    GraphEdge,
    GraphNode,
    KnowledgeGraph,
)

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


class GraphBuilder:
    """Build a :class:`KnowledgeGraph` from extractor output."""

    def build(
        self,
        entities: Optional[List[GraphNode]] = None,
        concepts: Optional[List[GraphNode]] = None,
        relationships: Optional[List[GraphEdge]] = None,
        *,
        metadata: Optional[dict] = None,
    ) -> KnowledgeGraph:
        """Assemble a graph from extracted entities, concepts, and relationships."""
        nodes = list(entities or []) + list(concepts or [])
        merged_nodes, endpoint_map = self._merge_nodes(nodes)
        edges = self._build_edges(relationships or [], endpoint_map)
        return KnowledgeGraph(
            nodes=merged_nodes, edges=edges, metadata=dict(metadata or {})
        )

    # -- node merging ------------------------------------------------------

    def _merge_nodes(
        self, nodes: List[GraphNode]
    ) -> Tuple[List[GraphNode], Dict[str, str]]:
        """Merge nodes whose labels normalise equally; keep the first instance.

        Returns the surviving nodes and a map from every original id/label to the
        surviving node's id (used to remap edges).
        """
        canonical: Dict[str, GraphNode] = {}   # normalised label -> node
        endpoint_map: Dict[str, str] = {}      # original id/label -> canonical id

        for node in nodes:
            self._ensure_id(node)
            norm = self._normalize(node.label)
            if norm in canonical:
                survivor = canonical[norm]
                self._add_alias(survivor, node.label)
            else:
                canonical[norm] = node
                survivor = node
            # Both the id and the label should resolve to the survivor.
            endpoint_map[node.id] = survivor.id
            endpoint_map[node.label] = survivor.id

        return list(canonical.values()), endpoint_map

    def _ensure_id(self, node: GraphNode) -> None:
        if not node.id:
            node.id = self._normalize(node.label) or "node"

    def _add_alias(self, survivor: GraphNode, label: str) -> None:
        if not label or label == survivor.label:
            return
        aliases = survivor.properties.setdefault("aliases", [])
        if label not in aliases:
            aliases.append(label)

    # -- edge building -----------------------------------------------------

    def _build_edges(
        self, relationships: List[GraphEdge], endpoint_map: Dict[str, str]
    ) -> List[GraphEdge]:
        """Remap edge endpoints onto canonical node ids and drop duplicates."""
        edges: List[GraphEdge] = []
        seen: set = set()
        for edge in relationships:
            source = endpoint_map.get(edge.source, edge.source)
            target = endpoint_map.get(edge.target, edge.target)
            signature = (source, target, edge.relationship_type)
            if signature in seen:
                continue
            seen.add(signature)
            edges.append(edge.model_copy(update={"source": source, "target": target}))
        return edges

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _normalize(label: str) -> str:
        return _NON_ALNUM.sub("", (label or "").lower())
