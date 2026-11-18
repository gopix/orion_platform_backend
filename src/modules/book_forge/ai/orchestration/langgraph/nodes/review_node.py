"""ReviewNode — the graph step that reviews content.

Wraps ``ReviewAgent`` today. As a node it could later run multiple review agents
or validators and combine their verdicts without the graph changing. Callable:
``node(state) -> state``.
"""
from typing import Optional

from src.modules.book_forge.ai.orchestration.agents import ReviewAgent
from src.modules.book_forge.ai.orchestration.workflow_state import ReviewState


class ReviewNode:
    """Graph node wrapping the review agent."""

    name = "review"

    def __init__(self, *, agent: Optional[ReviewAgent] = None) -> None:
        self._agent = agent or ReviewAgent()

    def __call__(self, state: ReviewState) -> ReviewState:
        return self._agent.run(state)
