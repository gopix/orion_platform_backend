"""DocumentImage — an image extracted from or referenced in a document.

Holds a reference and descriptive info (caption/alt text, dimensions, page)
rather than raw bytes, so the content model stays lightweight; the actual image
data is handled by the storage layer. Data model only — no behaviour.
"""
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class DocumentImage(BaseModel):
    # Where the extracted image lives / how to reference it (path, URI, id).
    source_ref: Optional[str] = None
    # Descriptive text.
    caption: Optional[str] = None
    alt_text: Optional[str] = None
    # Format and dimensions when known.
    image_format: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    # Locating context.
    page_number: Optional[int] = None
    order: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"from_attributes": True}
