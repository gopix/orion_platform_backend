"""Graph persistence — repository abstraction plus a JSON implementation.

The knowledge graph, unlike the parser, needs persistence: we may want to save a
built graph and load it later. The repository hides *where* it's stored, so the
service depends on ``BaseGraphRepository`` and never on a specific backend:

    KnowledgeGraph  <->  BaseGraphRepository  <->  { JSON today, Neo4j / DB later }

``JsonGraphRepository`` is the concrete backend for now (one JSON file per graph).
Future ``Neo4jGraphRepository`` / ``DbGraphRepository`` implement the same
interface and the service is untouched.
"""
import json
import os
from abc import ABC, abstractmethod
from typing import List

from src.modules.book_forge.ai.intelligence.knowledge_graph.exceptions import (
    KnowledgeGraphException,
)
from src.modules.book_forge.ai.intelligence.knowledge_graph.models import (
    Concept,
    Entity,
    GraphEdge,
    GraphNode,
    KnowledgeGraph,
    NodeType,
)


class BaseGraphRepository(ABC):
    """Contract for persisting and retrieving knowledge graphs."""

    @abstractmethod
    def save(self, graph_id: str, graph: KnowledgeGraph) -> str:
        """Persist ``graph`` under ``graph_id``; return a locator (path/uri/id)."""
        raise NotImplementedError

    @abstractmethod
    def load(self, graph_id: str) -> KnowledgeGraph:
        """Load the graph stored under ``graph_id``."""
        raise NotImplementedError

    @abstractmethod
    def exists(self, graph_id: str) -> bool:
        """Return whether a graph is stored under ``graph_id``."""
        raise NotImplementedError

    @abstractmethod
    def delete(self, graph_id: str) -> None:
        """Delete the graph stored under ``graph_id`` (no-op if absent)."""
        raise NotImplementedError

    @abstractmethod
    def list_ids(self) -> List[str]:
        """Return the ids of all stored graphs."""
        raise NotImplementedError


class JsonGraphRepository(BaseGraphRepository):
    """Store each graph as a JSON file in a directory (the default backend)."""

    def __init__(self, base_dir: str = "graph_store") -> None:
        self._base_dir = base_dir

    def save(self, graph_id: str, graph: KnowledgeGraph) -> str:
        os.makedirs(self._base_dir, exist_ok=True)
        path = self._path(graph_id)
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(graph.model_dump_json(indent=2))
        except OSError as exc:
            raise KnowledgeGraphException(
                f"Failed to save graph '{graph_id}': {exc}",
                details={"graph_id": graph_id, "path": path},
                cause=exc,
            )
        return path

    def load(self, graph_id: str) -> KnowledgeGraph:
        path = self._path(graph_id)
        if not os.path.exists(path):
            raise KnowledgeGraphException(
                f"Graph '{graph_id}' not found.",
                details={"graph_id": graph_id, "path": path},
            )
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise KnowledgeGraphException(
                f"Failed to load graph '{graph_id}': {exc}",
                details={"graph_id": graph_id, "path": path},
                cause=exc,
            )
        return self._deserialize(data)

    def exists(self, graph_id: str) -> bool:
        return os.path.exists(self._path(graph_id))

    def delete(self, graph_id: str) -> None:
        path = self._path(graph_id)
        if os.path.exists(path):
            os.remove(path)

    def list_ids(self) -> List[str]:
        if not os.path.isdir(self._base_dir):
            return []
        return sorted(
            name[:-5] for name in os.listdir(self._base_dir) if name.endswith(".json")
        )

    # -- internals ---------------------------------------------------------

    def _path(self, graph_id: str) -> str:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(graph_id))
        return os.path.join(self._base_dir, f"{safe}.json")

    @staticmethod
    def _deserialize(data: dict) -> KnowledgeGraph:
        """Rebuild a graph, restoring Entity/Concept node subtypes from ``type``."""
        nodes = [
            JsonGraphRepository._node_from_dict(n) for n in data.get("nodes", [])
        ]
        edges = [GraphEdge(**e) for e in data.get("edges", [])]
        return KnowledgeGraph(
            nodes=nodes, edges=edges, metadata=data.get("metadata", {})
        )

    @staticmethod
    def _node_from_dict(node: dict) -> GraphNode:
        node_type = str(node.get("type", "")).lower()
        if node_type == NodeType.ENTITY.value:
            return Entity(**node)
        if node_type == NodeType.CONCEPT.value:
            return Concept(**node)
        return GraphNode(**node)
