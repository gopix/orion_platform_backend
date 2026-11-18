"""Parser orchestration service.

The single entry point the rest of the application uses to turn a document into a
``ParsedDocument``. Callers depend on ``ParserService`` (or the shared
``parser_service`` singleton) and never instantiate a provider directly.

    source -> validate -> detect format & choose provider -> parse -> ParsedDocument

The service owns orchestration only — input validation, format detection,
provider selection/caching, and logging. It does not know *how* any format is
parsed.
"""
import time
from typing import Dict, Optional, Union

from src.core.logger import get_logger
from src.modules.book_forge.ai.intelligence.parsers.exceptions import (
    ParserException,
    UnsupportedDocumentException,
)
from src.modules.book_forge.ai.intelligence.parsers.factory import (
    ParserProviderFactory,
)
from src.modules.book_forge.ai.intelligence.parsers.models import (
    DocumentFormat,
    ParsedDocument,
)
from src.modules.book_forge.ai.intelligence.parsers.providers import (
    BaseParserProvider,
)
from src.modules.book_forge.ai.intelligence.parsers.utils import FileTypeDetector

logger = get_logger(__name__)

DocumentSource = Union[str, bytes]


class ParserService:
    """Orchestrates parsing a document into a ``ParsedDocument``."""

    def __init__(self) -> None:
        # Cache of instantiated providers, keyed by format.
        self._instances: Dict[DocumentFormat, BaseParserProvider] = {}

    def get_provider(self, document_format: DocumentFormat) -> BaseParserProvider:
        """Resolve the provider for a format, building it via the factory once."""
        if document_format not in self._instances:
            logger.info("Instantiating parser provider '%s'", document_format.value)
            self._instances[document_format] = ParserProviderFactory.create(
                document_format
            )
        return self._instances[document_format]

    def parse(
        self,
        source: DocumentSource,
        *,
        filename: Optional[str] = None,
        document_format: Optional[Union[DocumentFormat, str]] = None,
    ) -> ParsedDocument:
        """Parse ``source`` (path or bytes) into a ``ParsedDocument``."""
        self._validate(source)
        fmt = self._resolve_format(source, filename, document_format)
        provider = self.get_provider(fmt)

        start = time.perf_counter()
        result: Optional[ParsedDocument] = None
        error: Optional[BaseException] = None
        try:
            result = provider.parse(source, filename=filename)
            return result
        except BaseException as exc:  # noqa: BLE001 - re-raised after logging
            error = exc
            raise
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            self._log(fmt, filename, result, duration_ms, error)

    # -- validation & format resolution -----------------------------------

    def _validate(self, source: DocumentSource) -> None:
        if source is None:
            raise ParserException("No document source provided.")
        if isinstance(source, (bytes, bytearray)) and len(source) == 0:
            raise ParserException("Document bytes are empty.")
        if isinstance(source, str) and not source.strip():
            raise ParserException("Document path is empty.")

    def _resolve_format(
        self,
        source: DocumentSource,
        filename: Optional[str],
        document_format: Optional[Union[DocumentFormat, str]],
    ) -> DocumentFormat:
        """Use an explicit format if given, otherwise detect it."""
        if document_format is not None:
            return self._coerce_format(document_format)

        # For a path, its name drives extension detection; for bytes, sniff.
        effective_name = filename or (source if isinstance(source, str) else None)
        data = source if isinstance(source, (bytes, bytearray)) else None
        fmt = FileTypeDetector.detect(filename=effective_name, data=data)

        if fmt is DocumentFormat.UNKNOWN:
            raise UnsupportedDocumentException(
                "unknown", supported=ParserProviderFactory.available()
            )
        return fmt

    @staticmethod
    def _coerce_format(value: Union[DocumentFormat, str]) -> DocumentFormat:
        if isinstance(value, DocumentFormat):
            return value
        try:
            return DocumentFormat(str(value).lower())
        except ValueError:
            raise UnsupportedDocumentException(
                value, supported=ParserProviderFactory.available()
            )

    # -- logging -----------------------------------------------------------

    def _log(
        self,
        document_format: DocumentFormat,
        filename: Optional[str],
        result: Optional[ParsedDocument],
        duration_ms: float,
        error: Optional[BaseException],
    ) -> None:
        """Emit one structured log line per parse."""
        success = error is None
        sections = len(result.sections) if result is not None else 0
        paragraphs = len(result.paragraphs) if result is not None else 0

        log = logger.info if success else logger.error
        log(
            "Parse | format=%s filename=%s | sections=%s paragraphs=%s | "
            "duration_ms=%.1f | success=%s%s",
            document_format.value,
            filename,
            sections,
            paragraphs,
            duration_ms,
            success,
            f" | error={type(error).__name__}: {error}" if error else "",
        )


# Shared singleton — import this from other modules.
parser_service = ParserService()