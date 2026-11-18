"""VectorSearchException — a similarity search failed.

Raised when a search operation against the vector database fails (bad query
vector dimensionality, backend/query error, ...). Distinct from store/persist
failures so callers can tell retrieval problems apart from write problems.
"""
from typing import Any, Dict, Optional

from src.modules.book_forge.ai.foundation.vector_store.exceptions.vector_store_exception import (
    VectorStoreException,
)


class VectorSearchException(VectorStoreException):
    """Raised when a vector similarity search fails."""

    default_error_code = "VDB-003"
    default_message = "Vector search failed"

    def __init__(
        self,
        message: Optional[str] = None,
        *,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        super().__init__(message, details=details, cause=cause)
