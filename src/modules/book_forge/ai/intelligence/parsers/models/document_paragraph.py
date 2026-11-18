"""DocumentParagraph — one paragraph (block of body text) in a document.

The smallest text unit the parser emits. Carries locating context (page, order)
and, where the source exposes it, the style name (e.g. a DOCX "Heading 1"). Data
model only — no behaviour.
"""
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class DocumentParagraph(BaseModel):
    text: str
    # Ordinal position within its parent section/document (0-based).
    order: Optional[int] = None
    page_number: Optional[int] = None
    # Source style name when available (e.g. DOCX paragraph style).
    style: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"from_attributes": True}
