"""Abstract interface every document parser provider implements.

A provider knows how to read one document format and turn it into a rich
``ParsedDocument`` — nothing else. No vendor SDK objects leak past this boundary.

    PDF / DOCX / EPUB  ->  <Provider>  ->  ParsedDocument

Same pattern as LLM/embeddings/vector-store providers: a base contract plus
concrete implementations. The shared helpers here normalise the input (path or
raw bytes) so each provider just consumes a stream.
"""
import io
import os
from abc import ABC, abstractmethod
from typing import Optional, Tuple, Union

from src.modules.book_forge.ai.intelligence.parsers.models import (
    DocumentFormat,
    ParsedDocument,
)

# A document source may be a filesystem path or raw bytes.
DocumentSource = Union[str, bytes]


class BaseParserProvider(ABC):
    """Common contract for all document parser providers."""

    #: The format this provider handles; set by each subclass.
    document_format: DocumentFormat = DocumentFormat.UNKNOWN

    @abstractmethod
    def parse(
        self, source: DocumentSource, *, filename: Optional[str] = None
    ) -> ParsedDocument:
        """Parse ``source`` (a path or bytes) into a ``ParsedDocument``."""
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Shared helpers                                                     #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _to_stream(
        source: DocumentSource, filename: Optional[str] = None
    ) -> Tuple[io.BytesIO, Optional[str]]:
        """Return an in-memory stream for ``source`` plus a resolved filename.

        Accepts a filesystem path (str) or raw bytes; both parser libraries can
        read a file-like object, so callers get a uniform ``BytesIO``.
        """
        if isinstance(source, bytes):
            return io.BytesIO(source), filename
        # Treat as a path.
        with open(source, "rb") as handle:
            data = handle.read()
        return io.BytesIO(data), filename or os.path.basename(source)
