"""GraphValidator — sanity-check a document and its built knowledge graph.

Collects all problems and raises a single ``GraphValidationException`` with the
full list, rather than failing on the first. It covers:

* the source ``ParsedDocument`` exists and has content;
* node uniqueness (no duplicate ids or labels — the builder should have merged);
* relationship consistency (edges reference existing nodes, no self-loops, a
  non-empty type);
* circular relationships (optional — allowed via ``allow_cycles``).

Stateless — no I/O.
"""
from collections import Counter, defaultdict
from typing import Any, List, Optional

from src.modules.book_forge.ai.intelligence.knowledge_graph.exceptions import (
    GraphValidationException,
)
from src.modules.book_forge.ai.intelligence.knowledge_graph.models import (
    KnowledgeGraph,
)

_NON_ALNUM_LOWER = str.maketrans("", "", " \t\n")


class GraphValidator:
    """Validate a knowledge graph (and optionally its source document)."""

    def validate(
        self,
        graph: KnowledgeGraph,
        *,
        document: Optional[Any] = None,
        allow_cycles: bool = True,
    ) -> None:
        """Raise ``GraphValidationException`` if the document/graph is invalid."""
        issues = self.find_issues(
            graph, document=document, allow_cycles=allow_cycles
        )
        if issues:
            raise GraphValidationException(
                "Knowledge graph failed validation.",
                details={"issues": issues, "count": len(issues)},
            )

    def find_issues(
        self,
        graph: KnowledgeGraph,
        *,
        document: Optional[Any] = None,
        allow_cycles: bool = True,
    ) -> List[str]:
        """Return a list of validation problems (empty means valid)."""
        issues: List[str] = []
        if document is not None:
            issues.extend(self._check_document(document))
        issues.extend(self._check_nodes(graph))
        issues.extend(self._check_relationships(graph, allow_cycles))
        return issues

    # -- document ----------------------------------------------------------

    def _check_document(self, document: Any) -> List[str]:
        issues: List[str] = []
        sections = getattr(document, "sections", None) or []
        paragraphs = getattr(document, "paragraphs", None) or []
        # "Section count > 0" — but flat-paragraph docs (e.g. PDFs) are valid too,
        # so require content in either sections or paragraphs.
        if not sections and not paragraphs:
            issues.append("Document has no content (no sections or paragraphs).")
        return issues

    # -- nodes -------------------------------------------------------------

    def _check_nodes(self, graph: KnowledgeGraph) -> List[str]:
        issues: List[str] = []

        id_counts = Counter(node.id for node in graph.nodes)
        for node_id, count in id_counts.items():
            if count > 1:
                issues.append(f"Duplicate node id '{node_id}' ({count} occurrences).")

        label_counts = Counter(
            node.label.lower().translate(_NON_ALNUM_LOWER) for node in graph.nodes
        )
        for label, count in label_counts.items():
            if label and count > 1:
                issues.append(
                    f"Duplicate node label (normalised '{label}') appears {count} "
                    "times; should have been merged."
                )
        return issues

    # -- relationships -----------------------------------------------------

    def _check_relationships(
        self, graph: KnowledgeGraph, allow_cycles: bool
    ) -> List[str]:
        issues: List[str] = []
        node_ids = {node.id for node in graph.nodes}

        for edge in graph.edges:
            if edge.source not in node_ids:
                issues.append(
                    f"Edge references missing source node '{edge.source}'."
                )
            if edge.target not in node_ids:
                issues.append(
                    f"Edge references missing target node '{edge.target}'."
                )
            if edge.source == edge.target:
                issues.append(f"Self-loop on node '{edge.source}'.")
            if not (edge.relationship_type or "").strip():
                issues.append(
                    f"Edge {edge.source}->{edge.target} has no relationship_type."
                )

        if not allow_cycles and self._has_cycle(node_ids, graph.edges):
            issues.append("Graph contains a circular relationship (cycle).")

        return issues

    @staticmethod
    def _has_cycle(node_ids: set, edges: list) -> bool:
        """Detect a directed cycle among edges connecting existing nodes."""
        adjacency = defaultdict(list)
        for edge in edges:
            if edge.source in node_ids and edge.target in node_ids:
                adjacency[edge.source].append(edge.target)

        WHITE, GRAY, BLACK = 0, 1, 2
        color = {node_id: WHITE for node_id in node_ids}

        def visit(node: str) -> bool:
            color[node] = GRAY
            for neighbour in adjacency[node]:
                state = color.get(neighbour, WHITE)
                if state == GRAY:
                    return True
                if state == WHITE and visit(neighbour):
                    return True
            color[node] = BLACK
            return False

        return any(color[n] == WHITE and visit(n) for n in list(node_ids))
