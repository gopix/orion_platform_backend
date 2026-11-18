"""GraphSerializer — export a knowledge graph to interchange formats.

Serialises node/edge lists to JSON and GraphML today, with Cypher (Neo4j)
statements for loading into a graph database. Keeping export here means the rest
of the module never hand-rolls format strings. Works on lightweight node/edge
dicts. Stateless and pure.
"""
import json
import xml.etree.ElementTree as ET
from typing import Any, List

from src.modules.book_forge.ai.intelligence.knowledge_graph.utils._access import (
    get_edge_type,
    get_field,
)


class GraphSerializer:
    """Serialise a knowledge graph to JSON / GraphML / Cypher."""

    @staticmethod
    def to_json(nodes: List[Any], edges: List[Any], *, indent: int = 2) -> str:
        """Serialise the graph to a JSON string."""
        payload = {
            "nodes": [GraphSerializer._as_dict(n) for n in nodes],
            "edges": [GraphSerializer._as_dict(e) for e in edges],
        }
        return json.dumps(payload, indent=indent, default=str)

    @staticmethod
    def to_graphml(nodes: List[Any], edges: List[Any]) -> str:
        """Serialise the graph to a GraphML (XML) string."""
        ns = "http://graphml.graphdrawing.org/xmlns"
        root = ET.Element("graphml", xmlns=ns)

        # Declare the two data keys we emit (node label/type, edge type).
        for key_id, domain, name in [
            ("label", "node", "label"),
            ("ntype", "node", "type"),
            ("etype", "edge", "type"),
        ]:
            key = ET.SubElement(root, "key")
            key.set("id", key_id)
            key.set("for", domain)
            key.set("attr.name", name)
            key.set("attr.type", "string")

        graph = ET.SubElement(root, "graph", edgedefault="directed")

        for node in nodes:
            n = ET.SubElement(graph, "node", id=str(GraphSerializer._node_id(node)))
            GraphSerializer._data(n, "label", GraphSerializer._node_name(node))
            GraphSerializer._data(n, "ntype", get_field(node, "type"))

        for index, edge in enumerate(edges):
            e = ET.SubElement(
                graph,
                "edge",
                id=f"e{index}",
                source=str(get_field(edge, "source")),
                target=str(get_field(edge, "target")),
            )
            GraphSerializer._data(e, "etype", get_edge_type(edge))

        return ET.tostring(root, encoding="unicode")

    @staticmethod
    def to_cypher(nodes: List[Any], edges: List[Any]) -> str:
        """Serialise the graph to Cypher CREATE statements for Neo4j."""
        lines: List[str] = []
        for node in nodes:
            var = GraphSerializer._var(GraphSerializer._node_id(node))
            label = (get_field(node, "type") or "Node").capitalize()
            name = GraphSerializer._escape(GraphSerializer._node_name(node))
            nid = GraphSerializer._escape(GraphSerializer._node_id(node))
            lines.append(f"CREATE ({var}:{label} {{id: '{nid}', name: '{name}'}})")
        for edge in edges:
            src = GraphSerializer._var(get_field(edge, "source"))
            dst = GraphSerializer._var(get_field(edge, "target"))
            rel = str(get_edge_type(edge) or "RELATED_TO").upper().replace(" ", "_")
            lines.append(f"CREATE ({src})-[:{rel}]->({dst})")
        return "\n".join(lines)

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _as_dict(obj: Any) -> dict:
        if isinstance(obj, dict):
            return obj
        if hasattr(obj, "model_dump"):  # pydantic
            return obj.model_dump()
        return dict(getattr(obj, "__dict__", {}))

    @staticmethod
    def _node_id(node: Any) -> Any:
        return (
            get_field(node, "id")
            or get_field(node, "name")
            or get_field(node, "label")
        )

    @staticmethod
    def _node_name(node: Any) -> Any:
        return (
            get_field(node, "name")
            or get_field(node, "label")
            or get_field(node, "id")
            or ""
        )

    @staticmethod
    def _data(parent: ET.Element, key: str, value: Any) -> None:
        if value is None:
            return
        data = ET.SubElement(parent, "data", key=key)
        data.text = str(value)

    @staticmethod
    def _var(node_id: Any) -> str:
        cleaned = "".join(ch if str(ch).isalnum() else "_" for ch in str(node_id))
        return f"n_{cleaned}" if cleaned else "n_"

    @staticmethod
    def _escape(value: Any) -> str:
        return str(value).replace("\\", "\\\\").replace("'", "\\'")
