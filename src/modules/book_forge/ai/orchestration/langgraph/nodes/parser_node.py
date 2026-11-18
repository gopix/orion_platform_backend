"""ParserNode — graph step that runs the ParserAgent."""
from typing import Optional

from src.modules.book_forge.ai.orchestration.agents import ParserAgent
from src.modules.book_forge.ai.orchestration.workflow_state import (
    ProcessingWorkflowState,
)


class ParserNode:
    """Graph node wrapping the parser agent."""

    name = "parser"

    def __init__(self, *, agent: Optional[ParserAgent] = None) -> None:
        self._agent = agent or ParserAgent()

    def __call__(self, state: ProcessingWorkflowState) -> ProcessingWorkflowState:
        return self._agent.run(state)
