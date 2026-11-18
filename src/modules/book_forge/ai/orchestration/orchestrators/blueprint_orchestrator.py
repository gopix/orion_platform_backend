"""BlueprintOrchestrator — entry into the blueprint workflow.

Mirrors ``book_processing_orchestrator`` but compiles the blueprint graph
PER REQUEST, injecting a ``BlueprintContext`` (db + prompt service + top_k) into
the nodes. Passing ``context`` as a build argument makes ``GraphExecutionService``
bypass its default compiled-graph cache and build a fresh graph bound to this
request's collaborators.

    BlueprintOrchestrator
        -> WorkflowService (lifecycle/state)
        -> GraphExecutionService.engine_for("blueprint", context=...)
        -> blueprint graph -> nodes (retrieve -> generate -> review)
"""
from src.modules.book_forge.ai.orchestration.blueprint_context import BlueprintContext
from src.modules.book_forge.ai.orchestration.langgraph.services import (
    graph_execution_service,
)
from src.modules.book_forge.ai.orchestration.services import WorkflowService
from src.modules.book_forge.ai.orchestration.workflow_state import BlueprintState

GRAPH_NAME = "blueprint"


class BlueprintOrchestrator:
    """Run the blueprint workflow for a project."""

    def __init__(self, *, graph_service=None) -> None:
        self._graph_service = graph_service or graph_execution_service

    def generate(
        self,
        state: BlueprintState,
        *,
        context: BlueprintContext,
        max_revisions: int = 2,
    ) -> BlueprintState:
        """Compile the blueprint graph for this request and run it."""
        engine = self._graph_service.engine_for(
            GRAPH_NAME, context=context, max_revisions=max_revisions
        )
        workflow = WorkflowService(engine=engine)
        return workflow.start(state)


# Shared singleton — import this from the entry-point service.
blueprint_orchestrator = BlueprintOrchestrator()
