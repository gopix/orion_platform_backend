"""EmbeddingNode — graph step that runs the EmbeddingAgent."""
from typing import Optional

from src.modules.book_forge.ai.orchestration.agents import EmbeddingAgent
from src.modules.book_forge.ai.orchestration.workflow_state import (
    ProcessingWorkflowState,
)


class EmbeddingNode:
    """Graph node wrapping the embedding agent."""

    name = "embedding"

    def __init__(self, *, agent: Optional[EmbeddingAgent] = None) -> None:
        self._agent = agent or EmbeddingAgent()

    def __call__(self, state: ProcessingWorkflowState) -> ProcessingWorkflowState:
        return self._agent.run(state)
