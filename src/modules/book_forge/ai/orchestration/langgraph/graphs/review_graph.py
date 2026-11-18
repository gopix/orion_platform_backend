"""ReviewGraph — the standalone quality-review workflow.

    START -> review
             review --approved--> END
             review --revise----> request_revisions -> END

Reviews content and, when not approved, records the requested revisions. Threads a
``ReviewState``. Defines nodes, edges, and a conditional branch — nothing else.
"""
from src.modules.book_forge.ai.orchestration.langgraph.graphs._state_graph import (
    END,
    CompiledGraph,
    StateGraph,
)
from src.modules.book_forge.ai.orchestration.langgraph.nodes import ReviewNode
from src.modules.book_forge.ai.orchestration.workflow_state import ReviewState


def build_review_graph() -> CompiledGraph:
    """Build and compile the review workflow graph."""
    graph = StateGraph()
    graph.add_node("review", ReviewNode())
    graph.add_node("request_revisions", _request_revisions)

    graph.set_entry_point("review")
    graph.add_conditional_edges(
        "review",
        _approval_router,
        {"approved": END, "revise": "request_revisions"},
    )
    graph.add_edge("request_revisions", END)
    return graph.compile()


def _approval_router(state: ReviewState) -> str:
    return "approved" if state.approved else "revise"


def _request_revisions(state: ReviewState) -> ReviewState:
    """Node: record that revisions were requested."""
    state.advance("request_revisions")
    state.add_message(
        "assistant", f"{len(state.revisions_requested)} revision(s) requested."
    )
    return state
