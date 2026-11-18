"""KnowledgeGraphNode — graph step that runs the KnowledgeGraphAgent."""
from typing import Optional

from src.modules.book_forge.ai.orchestration.agents import KnowledgeGraphAgent
from src.modules.book_forge.ai.orchestration.workflow_state import (
    ProcessingWorkflowState,
)


class KnowledgeGraphNode:
    """Graph node wrapping the knowledge graph agent."""

    name = "knowledge_graph"

    def __init__(self, *, agent: Optional[KnowledgeGraphAgent] = None) -> None:
        self._agent = agent or KnowledgeGraphAgent()

    def __call__(self, state: ProcessingWorkflowState) -> ProcessingWorkflowState:
        return self._agent.run(state)
