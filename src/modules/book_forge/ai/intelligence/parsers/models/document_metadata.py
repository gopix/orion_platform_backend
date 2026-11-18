"""DocumentMetadata — descriptive metadata about a parsed document.

Captures the document-level facts a parser can extract (title, author, page
count, source format, ...) independent of the body content. Kept separate from
``ParsedDocument`` so metadata can grow without touching the content model. Data
model only — no behaviour.
"""
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class DocumentFormat(str, Enum):
    """Source file format a document was parsed from."""

    PDF = "pdf"
    DOCX = "docx"
    EPUB = "epub"  # future
    UNKNOWN = "unknown"


class DocumentMetadata(BaseModel):
    title: Optional[str] = None
    author: Optional[str] = None
    subject: Optional[str] = None
    keywords: List[str] = Field(default_factory=list)
    language: Optional[str] = None

    # Source provenance.
    source_format: DocumentFormat = DocumentFormat.UNKNOWN
    filename: Optional[str] = None
    page_count: Optional[int] = None

    # Producer/creation info when available (PDF producer, DOCX created/modified).
    producer: Optional[str] = None
    created_at: Optional[str] = None
    modified_at: Optional[str] = None

    # Anything format-specific that doesn't have a first-class field yet.
    extra: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"from_attributes": True}
