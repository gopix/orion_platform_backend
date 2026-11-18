"""DocumentParsingException — a document failed to parse.

Raised when a provider can't parse the input (corrupt file, unreadable content,
underlying library error). The provider wraps the vendor error as ``cause`` so
callers see a BookForge exception, not a raw library one.
"""
from src.modules.book_forge.ai.intelligence.parsers.exceptions.parser_exception import (
    ParserException,
)


class DocumentParsingException(ParserException):
    """Raised when a document cannot be parsed."""

    default_error_code = "PARSE-002"
    default_message = "Failed to parse document"
