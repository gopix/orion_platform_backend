"""BlueprintGraph — the book-blueprint RAG workflow.

    START -> generate_blueprint -> review
             review --approved--> END
             review --revise----> generate_blueprint   (up to max_revisions)

The graph owns only *what happens next*. Each step is a node that wraps its
collaborators (Node -> Agent -> services), so this file defines nodes, edges, and
the review branch — nothing about how retrieval or generation actually work.

    generate_blueprint : BlueprintNode -> BlueprintGenerationAgent
                         (per-chapter retrieval -> batched LLM -> guardrails)
    review             : ReviewAgent verdict; loop back to regenerate if needed

There is no separate retrieval node. The chapter structure now arrives on the
state already signed off by the SME, so retrieval is per chapter and belongs
inside generation — one broad whole-book query is what made the prose generic.

Compiled PER REQUEST with a ``BlueprintContext`` (db + prompt service + top_k),
which the nodes capture.
"""
from src.modules.book_forge.ai.orchestration.agents import ReviewAgent
from src.modules.book_forge.ai.orchestration.blueprint_context import BlueprintContext
from src.modules.book_forge.ai.orchestration.langgraph.graphs._state_graph import (
    END,
    CompiledGraph,
    StateGraph,
)
from src.modules.book_forge.ai.orchestration.langgraph.nodes import BlueprintNode
from src.modules.book_forge.ai.orchestration.workflow_state import (
    BlueprintState,
    ReviewState,
)


def build_blueprint_graph(
    *, context: BlueprintContext, max_revisions: int = 2
) -> CompiledGraph:
    """Build and compile the blueprint workflow graph for one request."""
    review_agent = ReviewAgent()

    graph = StateGraph()
    graph.add_node("generate_blueprint", BlueprintNode(context=context))
    graph.add_node("review", lambda s: _review(s, review_agent))

    graph.set_entry_point("generate_blueprint")
    graph.add_edge("generate_blueprint", "review")
    graph.add_conditional_edges(
        "review",
        lambda s: _review_router(s, max_revisions),
        {"approved": END, "revise": "generate_blueprint"},
    )
    return graph.compile()


def _review(state: BlueprintState, review_agent: ReviewAgent) -> BlueprintState:
    """Review the current blueprint and record the verdict on the state."""
    review_state = ReviewState(
        run_id=state.run_id,
        metadata={"blueprint": {"title": state.title, "chapters": state.chapters}},
    )
    review_agent.run(review_state)
    state.metadata["review"] = {
        "approved": review_state.approved,
        "score": review_state.score,
        "issues": review_state.issues,
    }
    state.add_message(
        "assistant", f"Blueprint reviewed: approved={review_state.approved}."
    )
    return state


def _review_router(state: BlueprintState, max_revisions: int) -> str:
    """Branch: end when approved (or out of revisions), else revise."""
    review = state.metadata.get("review", {})
    revisions = state.metadata.get("revision_count", 0)
    if review.get("approved") or revisions >= max_revisions:
        return "approved"
    state.metadata["revision_count"] = revisions + 1
    return "revise"
