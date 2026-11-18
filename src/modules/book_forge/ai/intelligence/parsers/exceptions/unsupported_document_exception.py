"""UnsupportedDocumentException — no parser for this document format.

Raised when a document's format has no registered parser provider (e.g. an EPUB
before that provider exists, or an unknown extension). A configuration problem
distinct from a document that fails to parse, so it gets its own type — parallel
to ``InvalidChunkStrategyException`` / ``InvalidVectorProviderException``.
"""
from typing import Any, Iterable, Optional

from src.modules.book_forge.ai.intelligence.parsers.exceptions.parser_exception import (
    ParserException,
)


class UnsupportedDocumentException(ParserException):
    """Raised when a document's format is not supported by any parser."""

    default_error_code = "PARSE-003"
    default_message = "Unsupported document format"

    def __init__(
        self,
        document_format: Any,
        supported: Optional[Iterable[Any]] = None,
        *,
        cause: Optional[BaseException] = None,
    ) -> None:
        self.document_format = document_format
        self.supported = [str(s) for s in supported] if supported is not None else []

        message = f"Unsupported document format: {document_format}."
        if self.supported:
            message += f" Supported: {', '.join(self.supported)}."

        super().__init__(
            message,
            details={"format": document_format, "supported": self.supported},
            cause=cause,
        )
