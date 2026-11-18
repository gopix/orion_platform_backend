"""DocumentSection — a logical section of a document.

A heading plus the content beneath it (paragraphs, tables, images) and any nested
sub-sections, so the parser can preserve a document's outline (Chapter ->
Section -> Sub-section). Downstream modules (chunking, knowledge graph) walk this
tree instead of re-parsing the file. Data model only — no behaviour.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from src.modules.book_forge.ai.intelligence.parsers.models.document_image import (
    DocumentImage,
)
from src.modules.book_forge.ai.intelligence.parsers.models.document_paragraph import (
    DocumentParagraph,
)
from src.modules.book_forge.ai.intelligence.parsers.models.document_table import (
    DocumentTable,
)


class DocumentSection(BaseModel):
    title: Optional[str] = None
    # Heading depth (1 = top-level chapter, 2 = section, ...).
    level: Optional[int] = None
    order: Optional[int] = None
    page_number: Optional[int] = None

    # Content directly under this heading.
    paragraphs: List[DocumentParagraph] = Field(default_factory=list)
    tables: List[DocumentTable] = Field(default_factory=list)
    images: List[DocumentImage] = Field(default_factory=list)

    # Nested sub-sections, preserving the outline hierarchy.
    subsections: List["DocumentSection"] = Field(default_factory=list)

    model_config = {"from_attributes": True}


DocumentSection.model_rebuild()
