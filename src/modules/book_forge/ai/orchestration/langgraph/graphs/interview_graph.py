"""InterviewGraph — the requirements-interview workflow.

    START -> interview -> generate_transcript -> END

Runs the SME interview, then turns the questions/answers into a transcript. Threads
an ``InterviewState``. Defines nodes, edges, and branches — nothing else.
"""
from typing import Optional

from src.modules.book_forge.ai.orchestration.langgraph.graphs._state_graph import (
    END,
    CompiledGraph,
    StateGraph,
)
from src.modules.book_forge.ai.orchestration.langgraph.nodes import InterviewNode
from src.modules.book_forge.ai.orchestration.workflow_state import InterviewState


def build_interview_graph(*, llm: Optional[object] = None) -> CompiledGraph:
    """Build and compile the interview workflow graph."""
    graph = StateGraph()
    graph.add_node("interview", InterviewNode(llm=llm))
    graph.add_node("generate_transcript", _generate_transcript)

    graph.set_entry_point("interview")
    graph.add_edge("interview", "generate_transcript")
    graph.add_edge("generate_transcript", END)
    return graph.compile()


def _generate_transcript(state: InterviewState) -> InterviewState:
    """Node: assemble a Q&A transcript from the interview."""
    state.advance("generate_transcript")
    lines = []
    for index, question in enumerate(state.questions):
        answer = state.answers.get(question) or state.answers.get(str(index)) or ""
        lines.append(f"Q: {question}\nA: {answer}")
    state.metadata["transcript"] = "\n\n".join(lines)
    state.add_message("assistant", "Interview transcript generated.")
    return state
