"""NodeExecutionException — a single node failed while running.

Raised when a graph node (agent) errors during execution. Carries the node name
so the failing step is obvious, and wraps the underlying error as ``cause``.
"""
from typing import Any, Dict, Optional

from src.modules.book_forge.ai.orchestration.langgraph.exceptions.graph_execution_exception import (
    GraphExecutionException,
)


class NodeExecutionException(GraphExecutionException):
    """Raised when a graph node fails to execute."""

    default_error_code = "LG-003"
    default_message = "Node execution failed"

    def __init__(
        self,
        message: Optional[str] = None,
        *,
        node: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        self.node = node
        merged: Dict[str, Any] = dict(details or {})
        if node is not None:
            merged.setdefault("node", node)
        super().__init__(message, details=merged or None, cause=cause)
