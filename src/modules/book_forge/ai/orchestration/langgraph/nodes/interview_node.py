"""InterviewNode — the graph step that runs the SME interview.

A node is one executable graph step. It is NOT an agent — it *wraps* one (today,
``SMEInterviewAgent``). The graph references the node, so tomorrow this node could
run two agents, a tool, and a validator without the graph changing. Callable:
``node(state) -> state``.
"""
from typing import Optional

from src.modules.book_forge.ai.orchestration.agents import SMEInterviewAgent
from src.modules.book_forge.ai.orchestration.workflow_state import InterviewState


class InterviewNode:
    """Graph node wrapping the SME interview agent."""

    name = "interview"

    def __init__(
        self, *, agent: Optional[SMEInterviewAgent] = None, llm: Optional[object] = None
    ) -> None:
        self._agent = agent or SMEInterviewAgent(llm=llm)

    def __call__(self, state: InterviewState) -> InterviewState:
        return self._agent.run(state)
