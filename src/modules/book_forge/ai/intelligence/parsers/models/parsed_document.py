"""ParsedDocument — the rich model a parser returns (never raw text).

This is the architectural contract of the parser layer: PDF/DOCX/EPUB in, one
structured ``ParsedDocument`` out. Every downstream module — chunking, knowledge
graph, and later the agents — consumes this instead of parsing files itself::

    PDF / DOCX  ->  Parser  ->  ParsedDocument  ->  Chunking  ->  ...

It holds the document's title and metadata, its section tree, and flat lists of
paragraphs/tables/images (useful for documents without clear sections), plus
footnotes and references. Data model only — the parser fills it; the model
carries no logic.
"""
from typing import List, Optional

from pydantic import BaseModel, Field

from src.modules.book_forge.ai.intelligence.parsers.models.document_image import (
    DocumentImage,
)
from src.modules.book_forge.ai.intelligence.parsers.models.document_metadata import (
    DocumentMetadata,
)
from src.modules.book_forge.ai.intelligence.parsers.models.document_paragraph import (
    DocumentParagraph,
)
from src.modules.book_forge.ai.intelligence.parsers.models.document_section import (
    DocumentSection,
)
from src.modules.book_forge.ai.intelligence.parsers.models.document_table import (
    DocumentTable,
)


class ParsedDocument(BaseModel):
    title: Optional[str] = None
    metadata: DocumentMetadata = Field(default_factory=DocumentMetadata)

    # The document outline (Chapter -> Section -> ...).
    sections: List[DocumentSection] = Field(default_factory=list)

    # Flat content lists — handy for documents with no clear section structure,
    # or as a quick way to iterate all content of a kind.
    paragraphs: List[DocumentParagraph] = Field(default_factory=list)
    tables: List[DocumentTable] = Field(default_factory=list)
    images: List[DocumentImage] = Field(default_factory=list)

    # Apparatus captured as text for now (dedicated models can come later).
    footnotes: List[str] = Field(default_factory=list)
    references: List[str] = Field(default_factory=list)

    model_config = {"from_attributes": True}
