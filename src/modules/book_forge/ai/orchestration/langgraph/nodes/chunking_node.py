"""ChunkingNode — graph step that runs the ChunkingAgent."""
from typing import Optional

from src.modules.book_forge.ai.orchestration.agents import ChunkingAgent
from src.modules.book_forge.ai.orchestration.workflow_state import (
    ProcessingWorkflowState,
)


class ChunkingNode:
    """Graph node wrapping the chunking agent."""

    name = "chunking"

    def __init__(self, *, agent: Optional[ChunkingAgent] = None) -> None:
        self._agent = agent or ChunkingAgent()

    def __call__(self, state: ProcessingWorkflowState) -> ProcessingWorkflowState:
        return self._agent.run(state)
