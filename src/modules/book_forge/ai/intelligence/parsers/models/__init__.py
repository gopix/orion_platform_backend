"""Parser data models (data only — no logic).

The parser returns a rich ``ParsedDocument`` rather than raw text; every
downstream module consumes this model.
"""
from src.modules.book_forge.ai.intelligence.parsers.models.document_image import (
    DocumentImage,
)
from src.modules.book_forge.ai.intelligence.parsers.models.document_metadata import (
    DocumentFormat,
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
from src.modules.book_forge.ai.intelligence.parsers.models.parsed_document import (
    ParsedDocument,
)

__all__ = [
    "ParsedDocument",
    "DocumentMetadata",
    "DocumentFormat",
    "DocumentSection",
    "DocumentParagraph",
    "DocumentTable",
    "DocumentImage",
]
