"""KnowledgeGraphAgent — build a project knowledge graph from parsed documents.

Wraps the knowledge-graph service. Builds a graph per parsed document and merges
them into one project-level ``KnowledgeGraph`` on the state (dedup nodes by id,
edges by (source, target, type)).
"""
from src.modules.book_forge.ai.intelligence.knowledge_graph.models import (
    KnowledgeGraph,
)
from src.modules.book_forge.ai.intelligence.knowledge_graph.services import (
    knowledge_graph_service,
)
from src.modules.book_forge.ai.orchestration.agents.base_agent import BaseAgent
from src.modules.book_forge.ai.orchestration.workflow_state import (
    ProcessingWorkflowState,
)


class KnowledgeGraphAgent(BaseAgent[ProcessingWorkflowState]):
    """Extract and merge a knowledge graph across the project's documents."""

    name = "Knowledge Graph Agent"
    step = "knowledge_graph"

    def execute(self, state: ProcessingWorkflowState) -> None:
        if not state.parsed_documents:
            state.skip("knowledge_graph", "no parsed documents")
            return

        nodes: dict = {}
        edges: list = []
        seen_edges: set = set()

        for parsed in state.parsed_documents:
            try:
                graph = knowledge_graph_service.build_from_document(
                    parsed, metadata={"project_id": state.project_id}
                )
            except Exception as exc:  # noqa: BLE001 - skip a doc that can't build
                state.add_message("system", f"Knowledge graph skipped for a doc: {exc}")
                continue

            for node in graph.nodes:
                nodes.setdefault(node.id, node)
            for edge in graph.edges:
                signature = (edge.source, edge.target, edge.relationship_type)
                if signature in seen_edges:
                    continue
                seen_edges.add(signature)
                edges.append(edge)

        state.knowledge_graph = KnowledgeGraph(
            nodes=list(nodes.values()),
            edges=edges,
            metadata={"project_id": state.project_id},
        )
        state.add_message(
            "assistant",
            f"Knowledge graph: {len(nodes)} nodes, {len(edges)} edges.",
        )
