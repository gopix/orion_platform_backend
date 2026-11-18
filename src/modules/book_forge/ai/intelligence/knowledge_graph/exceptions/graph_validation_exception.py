"""GraphValidationException — the assembled graph is invalid.

Raised when the built graph fails validation (dangling edges, duplicate nodes,
cycles where none are allowed, ...). A different problem from an extraction
failure, so it gets its own type.
"""
from typing import Any, Dict, Optional

from src.modules.book_forge.ai.intelligence.knowledge_graph.exceptions.knowledge_graph_exception import (
    KnowledgeGraphException,
)


class GraphValidationException(KnowledgeGraphException):
    """Raised when a constructed knowledge graph fails validation."""

    default_error_code = "KG-004"
    default_message = "Invalid knowledge graph"

    def __init__(
        self,
        message: Optional[str] = None,
        *,
        field: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        merged: Dict[str, Any] = dict(details or {})
        if field is not None:
            merged.setdefault("field", field)
        super().__init__(message, details=merged or None, cause=cause)
