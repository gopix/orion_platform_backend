"""PDF implementation of the parser provider interface (pdfplumber).

Turns a PDF into a ``ParsedDocument``: text is extracted per page and split into
paragraphs, tables and image references are collected per page. PDFs rarely carry
reliable heading structure, so content goes into the flat top-level lists rather
than a section tree. Vendor errors are translated into
``DocumentParsingException``.
"""
import re
from typing import List, Optional

from src.modules.book_forge.ai.intelligence.parsers.exceptions import (
    DocumentParsingException,
    ParserException,
)
from src.modules.book_forge.ai.intelligence.parsers.models import (
    DocumentFormat,
    DocumentImage,
    DocumentMetadata,
    DocumentParagraph,
    DocumentTable,
    ParsedDocument,
)
from src.modules.book_forge.ai.intelligence.parsers.providers.base_parser_provider import (
    BaseParserProvider,
    DocumentSource,
)

_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")


class PdfParserProvider(BaseParserProvider):
    """Parses .pdf files via pdfplumber."""

    document_format = DocumentFormat.PDF

    def parse(
        self, source: DocumentSource, *, filename: Optional[str] = None
    ) -> ParsedDocument:
        pdfplumber = self._import_pdfplumber()
        stream, resolved_name = self._to_stream(source, filename)

        paragraphs: List[DocumentParagraph] = []
        tables: List[DocumentTable] = []
        images: List[DocumentImage] = []
        order = 0

        try:
            with pdfplumber.open(stream) as pdf:
                metadata = self._build_metadata(pdf, resolved_name)
                for page_index, page in enumerate(pdf.pages):
                    page_number = page_index + 1
                    order = self._collect_paragraphs(page, page_number, paragraphs, order)
                    self._collect_tables(page, page_number, tables)
                    self._collect_images(page, page_number, images)
        except DocumentParsingException:
            raise
        except Exception as exc:  # noqa: BLE001 - translated to a domain error
            raise DocumentParsingException(
                f"Could not parse PDF: {exc}",
                details={"filename": resolved_name},
                cause=exc,
            )

        return ParsedDocument(
            title=metadata.title,
            metadata=metadata,
            paragraphs=paragraphs,
            tables=tables,
            images=images,
        )

    # -- extraction --------------------------------------------------------

    def _collect_paragraphs(
        self, page, page_number: int, out: List[DocumentParagraph], order: int
    ) -> int:
        text = page.extract_text() or ""
        for block in _PARAGRAPH_SPLIT_RE.split(text):
            block = block.strip()
            if block:
                out.append(
                    DocumentParagraph(text=block, page_number=page_number, order=order)
                )
                order += 1
        return order

    def _collect_tables(
        self, page, page_number: int, out: List[DocumentTable]
    ) -> None:
        for raw in page.extract_tables() or []:
            # Normalise None cells to empty strings.
            rows = [[(cell or "") for cell in row] for row in raw]
            if not rows:
                continue
            out.append(
                DocumentTable(
                    header=rows[0],
                    rows=rows[1:],
                    page_number=page_number,
                    order=len(out),
                )
            )

    def _collect_images(
        self, page, page_number: int, out: List[DocumentImage]
    ) -> None:
        for img in getattr(page, "images", []) or []:
            width = self._dim(img.get("x1"), img.get("x0"))
            height = self._dim(img.get("bottom"), img.get("top"))
            out.append(
                DocumentImage(
                    page_number=page_number,
                    width=width,
                    height=height,
                    order=len(out),
                )
            )

    @staticmethod
    def _dim(a, b) -> Optional[int]:
        if a is None or b is None:
            return None
        return int(abs(a - b))

    # -- metadata ----------------------------------------------------------

    def _build_metadata(self, pdf, filename: Optional[str]) -> DocumentMetadata:
        meta = pdf.metadata or {}
        return DocumentMetadata(
            title=meta.get("Title") or None,
            author=meta.get("Author") or None,
            subject=meta.get("Subject") or None,
            producer=meta.get("Producer") or None,
            source_format=DocumentFormat.PDF,
            filename=filename,
            page_count=len(pdf.pages),
            created_at=meta.get("CreationDate") or None,
            modified_at=meta.get("ModDate") or None,
        )

    # -- deps --------------------------------------------------------------

    @staticmethod
    def _import_pdfplumber():
        try:
            import pdfplumber
        except ImportError as exc:  # pragma: no cover - depends on env
            raise ParserException(
                "The 'pdfplumber' package is not installed.",
                details={"provider": "pdf"},
                cause=exc,
            )
        return pdfplumber
