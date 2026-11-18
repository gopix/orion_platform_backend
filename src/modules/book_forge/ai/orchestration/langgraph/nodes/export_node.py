"""ExportNode — the graph step that exports the finished book.

Wraps ``ExportAgent`` today. As a node it could later run a renderer tool plus a
final validator without the graph changing. Callable: ``node(state) -> state``.
"""
from typing import Optional

from src.modules.book_forge.ai.orchestration.agents import ExportAgent
from src.modules.book_forge.ai.orchestration.workflow_state import ExportState


class ExportNode:
    """Graph node wrapping the export agent."""

    name = "export"

    def __init__(self, *, agent: Optional[ExportAgent] = None) -> None:
        self._agent = agent or ExportAgent()

    def __call__(self, state: ExportState) -> ExportState:
        return self._agent.run(state)
