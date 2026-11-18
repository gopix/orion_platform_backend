"""Workflow graphs — each defines one business workflow (nodes/edges/branches).

Each ``build_*_graph`` returns a compiled graph exposing ``invoke(state) -> state``
(the ``WorkflowEngine`` contract), so it can be driven by ``WorkflowService``.
"""
from src.modules.book_forge.ai.orchestration.langgraph.graphs.blueprint_graph import (
    build_blueprint_graph,
)
from src.modules.book_forge.ai.orchestration.langgraph.graphs.book_processing_graph import (
    build_book_processing_graph,
)
from src.modules.book_forge.ai.orchestration.langgraph.graphs.interview_graph import (
    build_interview_graph,
)
from src.modules.book_forge.ai.orchestration.langgraph.graphs.review_graph import (
    build_review_graph,
)

__all__ = [
    "build_interview_graph",
    "build_blueprint_graph",
    "build_review_graph",
    "build_book_processing_graph",
]
