"""BookProcessingOrchestrator — the entry into the Orchestration layer.

This is the class that *uses* Orchestration. It doesn't know Parser, Embeddings,
or Pinecone — it hands a ``ProcessingWorkflowState`` to the book-processing graph
(via the graph engine, driven by ``WorkflowService`` for lifecycle/state) and
returns the final state.

    BookProcessingOrchestrator
        -> WorkflowService (lifecycle/state)
        -> GraphExecutionService (engine)
        -> book_processing graph -> nodes -> agents -> AI services
"""
from typing import Any, Dict, List, Optional

from src.modules.book_forge.ai.orchestration.langgraph.services import (
    graph_execution_service,
)
from src.modules.book_forge.ai.orchestration.services import WorkflowService
from src.modules.book_forge.ai.orchestration.workflow_state import (
    ProcessingWorkflowState,
)

GRAPH_NAME = "book_processing"


class BookProcessingOrchestrator:
    """Run the book-processing workflow for a project's documents."""

    def __init__(
        self,
        *,
        workflow_service: Optional[WorkflowService] = None,
        graph_service=None,
    ) -> None:
        self._graph_service = graph_service or graph_execution_service
        self._workflow = workflow_service or WorkflowService(
            engine=self._graph_service.engine_for(GRAPH_NAME)
        )

    def execute(self, state: ProcessingWorkflowState) -> ProcessingWorkflowState:
        """Run the graph over the given initial state and return the final state."""
        return self._workflow.start(state)

    def process(
        self, project_id: int, documents: List[Dict[str, Any]]
    ) -> ProcessingWorkflowState:
        """Convenience: build the initial state from inputs and run it."""
        state = ProcessingWorkflowState(project_id=project_id, documents=documents)
        return self.execute(state)


# Shared singleton — import this from the entry-point service.
book_processing_orchestrator = BookProcessingOrchestrator()
