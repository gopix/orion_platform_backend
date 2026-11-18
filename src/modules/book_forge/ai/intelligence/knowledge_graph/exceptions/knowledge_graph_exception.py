"""KnowledgeGraphException — base exception for the knowledge graph module.

    Exception
        │
        ▼
    KnowledgeGraphException          (catch the whole family here)
        │
   ┌────┼───────────────────────────────┐
   ▼    ▼                               ▼
EntityExtractionException  RelationshipExtractionException  GraphValidationException

Same shape as the other module bases: every knowledge-graph error derives from
this, so callers can catch everything with a single
``except KnowledgeGraphException``.
"""
from typing import Any, Dict, Optional


class KnowledgeGraphException(Exception):
    """Base class for every error raised by the knowledge graph module."""

    default_error_code: str = "KG-001"
    default_message: str = "Knowledge graph error"

    def __init__(
        self,
        message: Optional[str] = None,
        *,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        self.message = message or self.default_message
        self.error_code = error_code or self.default_error_code
        self.details = details
        self.cause = cause
        super().__init__(self.message)
        if cause is not None:
            self.__cause__ = cause

    def __str__(self) -> str:
        parts = [f"[{self.error_code}] {self.message}"]
        if self.details:
            rendered = ", ".join(f"{k}={v}" for k, v in self.details.items())
            parts.append(f"({rendered})")
        return " ".join(parts)
