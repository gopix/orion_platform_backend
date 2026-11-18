"""Parser exception types.

    ParserException  (base)
      ├── UnsupportedDocumentException   (no parser for this format)
      └── DocumentParsingException        (a document failed to parse)
"""
from src.modules.book_forge.ai.intelligence.parsers.exceptions.document_parsing_exception import (
    DocumentParsingException,
)
from src.modules.book_forge.ai.intelligence.parsers.exceptions.parser_exception import (
    ParserException,
)
from src.modules.book_forge.ai.intelligence.parsers.exceptions.unsupported_document_exception import (
    UnsupportedDocumentException,
)

__all__ = [
    "ParserException",
    "UnsupportedDocumentException",
    "DocumentParsingException",
]
