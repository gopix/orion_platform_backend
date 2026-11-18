"""VectorStoreNode — graph step that runs the VectorStoreAgent."""
from typing import Optional

from src.modules.book_forge.ai.orchestration.agents import VectorStoreAgent
from src.modules.book_forge.ai.orchestration.workflow_state import (
    ProcessingWorkflowState,
)


class VectorStoreNode:
    """Graph node wrapping the vector store agent."""

    name = "vector_store"

    def __init__(self, *, agent: Optional[VectorStoreAgent] = None) -> None:
        self._agent = agent or VectorStoreAgent()

    def __call__(self, state: ProcessingWorkflowState) -> ProcessingWorkflowState:
        return self._agent.run(state)
