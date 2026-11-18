"""InvalidGraphException — the graph itself is malformed.

Raised when the graph can't be built/compiled: no entry point, a dangling edge to
an unknown node, an unreachable node, or a cycle where none is allowed. A
configuration problem, distinct from a runtime node failure.
"""
from src.modules.book_forge.ai.orchestration.langgraph.exceptions.graph_execution_exception import (
    GraphExecutionException,
)


class InvalidGraphException(GraphExecutionException):
    """Raised when a graph is structurally invalid."""

    default_error_code = "LG-002"
    default_message = "Invalid graph"
