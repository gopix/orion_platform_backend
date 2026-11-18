"""Factory responsible for constructing parser providers by document format.

Owns the format -> provider registry and builds a concrete provider, keeping
provider *creation* out of the service — exactly like the LLM/embeddings/vector
factories. Adding EPUB later means registering it here; the service is untouched.
Raises ``UnsupportedDocumentException`` when a format has no provider.
"""
from typing import Dict, List, Type

from src.modules.book_forge.ai.intelligence.parsers.exceptions import (
    UnsupportedDocumentException,
)
from src.modules.book_forge.ai.intelligence.parsers.models import DocumentFormat
from src.modules.book_forge.ai.intelligence.parsers.providers import (
    BaseParserProvider,
    DocxParserProvider,
    PdfParserProvider,
)


class ParserProviderFactory:
    """Builds parser provider instances from a ``DocumentFormat``."""

    _REGISTRY: Dict[DocumentFormat, Type[BaseParserProvider]] = {
        DocumentFormat.PDF: PdfParserProvider,
        DocumentFormat.DOCX: DocxParserProvider,
    }

    @classmethod
    def create(cls, document_format: DocumentFormat) -> BaseParserProvider:
        """Instantiate the provider for ``document_format``."""
        provider_cls = cls._REGISTRY.get(document_format)
        if provider_cls is None:
            raise UnsupportedDocumentException(
                getattr(document_format, "value", document_format),
                supported=cls.available(),
            )
        return provider_cls()

    @classmethod
    def register(
        cls, document_format: DocumentFormat, provider_cls: Type[BaseParserProvider]
    ) -> None:
        """Register or override the provider for a format."""
        cls._REGISTRY[document_format] = provider_cls

    @classmethod
    def available(cls) -> List[str]:
        """Return the format names this factory can build."""
        return [fmt.value for fmt in cls._REGISTRY]
