"""GraphEvaluator — measure knowledge-graph quality.

Metrics: entity count (vs an expectation, or simply present), duplicate nodes
(unique-label ratio), and relationship quality (edges reference existing nodes,
no self-loops, adequate confidence). Input is a ``KnowledgeGraph`` (or a dict with
``nodes``/``edges``); ``metadata`` may carry ``expected_entities`` and
``min_confidence``. Heuristic baseline — stateless.
"""
import time

from src.modules.book_forge.ai.intelligence.evaluation.evaluators._common import (
    build_result,
    clamp,
    get,
    metric,
    normalize,
)
from src.modules.book_forge.ai.intelligence.evaluation.models import (
    AIModule,
    EvaluationRequest,
    EvaluationResult,
)


class GraphEvaluator:
    """Evaluate entity count, node duplication, and relationship quality."""

    def evaluate(self, request: EvaluationRequest) -> EvaluationResult:
        start = time.perf_counter()
        graph = request.input
        nodes = list(get(graph, "nodes", []) or [])
        edges = list(get(graph, "edges", []) or [])
        meta = request.metadata or {}

        if not nodes:
            return build_result(
                AIModule.KNOWLEDGE_GRAPH,
                [metric("entity_count", 0.0)],
                start,
                recommendations=["Graph has no nodes."],
            )

        expected = meta.get("expected_entities")
        entity_count = clamp(len(nodes) / expected) if expected else 1.0

        labels = [
            normalize(get(n, "label") or get(n, "name") or get(n, "id") or "")
            for n in nodes
        ]
        labels = [x for x in labels if x]
        duplicate_nodes = len(set(labels)) / len(labels) if labels else 1.0

        relationship_quality = self._relationship_quality(
            nodes, edges, meta.get("min_confidence", 0.5)
        )

        metrics = [
            metric("entity_count", entity_count),
            metric("duplicate_nodes", duplicate_nodes),
            metric("relationship_quality", relationship_quality),
        ]
        recs = []
        if duplicate_nodes < 0.7:
            recs.append("Duplicate nodes detected; run the NodeMerger before building.")
        if relationship_quality < 0.7:
            recs.append("Many edges are dangling/low-confidence; validate the graph.")
        return build_result(
            AIModule.KNOWLEDGE_GRAPH, metrics, start, recommendations=recs
        )

    @staticmethod
    def _relationship_quality(nodes, edges, min_confidence: float) -> float:
        if not edges:
            return 1.0
        node_ids = {get(n, "id") for n in nodes}
        good = 0
        for edge in edges:
            source, target = get(edge, "source"), get(edge, "target")
            confidence = get(edge, "confidence")
            ok = source in node_ids and target in node_ids and source != target
            if confidence is not None:
                ok = ok and confidence >= min_confidence
            good += 1 if ok else 0
        return good / len(edges)
