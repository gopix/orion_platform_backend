"""DOCX implementation of the parser provider interface (python-docx).

Turns a Word document into a ``ParsedDocument``: heading-styled paragraphs build
the section tree, body paragraphs attach to their section, and tables/images are
collected. Vendor errors are translated into ``DocumentParsingException``.
"""
from typing import List, Optional, Tuple

from src.modules.book_forge.ai.intelligence.parsers.exceptions import (
    DocumentParsingException,
    ParserException,
)
from src.modules.book_forge.ai.intelligence.parsers.models import (
    DocumentFormat,
    DocumentImage,
    DocumentMetadata,
    DocumentParagraph,
    DocumentSection,
    DocumentTable,
    ParsedDocument,
)
from src.modules.book_forge.ai.intelligence.parsers.providers.base_parser_provider import (
    BaseParserProvider,
    DocumentSource,
)


class DocxParserProvider(BaseParserProvider):
    """Parses .docx files via python-docx."""

    document_format = DocumentFormat.DOCX

    def parse(
        self, source: DocumentSource, *, filename: Optional[str] = None
    ) -> ParsedDocument:
        docx = self._import_docx()
        stream, resolved_name = self._to_stream(source, filename)
        try:
            document = docx.Document(stream)
        except Exception as exc:  # noqa: BLE001 - translated to a domain error
            raise DocumentParsingException(
                f"Could not open DOCX: {exc}",
                details={"filename": resolved_name},
                cause=exc,
            )

        metadata = self._build_metadata(document, resolved_name)
        sections, flat_paragraphs = self._build_sections(document)
        tables = self._build_tables(document)
        images = self._build_images(document)

        return ParsedDocument(
            title=metadata.title,
            metadata=metadata,
            sections=sections,
            paragraphs=flat_paragraphs,
            tables=tables,
            images=images,
        )

    # -- metadata ----------------------------------------------------------

    def _build_metadata(self, document, filename: Optional[str]) -> DocumentMetadata:
        props = document.core_properties
        keywords = [k.strip() for k in (props.keywords or "").split(",") if k.strip()]
        return DocumentMetadata(
            title=props.title or None,
            author=props.author or None,
            subject=props.subject or None,
            keywords=keywords,
            language=props.language or None,
            source_format=DocumentFormat.DOCX,
            filename=filename,
            created_at=str(props.created) if props.created else None,
            modified_at=str(props.modified) if props.modified else None,
        )

    # -- sections / paragraphs --------------------------------------------

    def _build_sections(
        self, document
    ) -> Tuple[List[DocumentSection], List[DocumentParagraph]]:
        """Build the section tree from heading styles.

        Paragraphs before the first heading go into a flat top-level list.
        """
        sections: List[DocumentSection] = []
        flat: List[DocumentParagraph] = []
        stack: List[Tuple[int, DocumentSection]] = []
        order = 0

        for para in document.paragraphs:
            text = (para.text or "").strip()
            if not text:
                continue
            style = para.style.name if para.style else None
            level = self._heading_level(style)

            if level:
                section = DocumentSection(title=text, level=level, order=order)
                while stack and stack[-1][0] >= level:
                    stack.pop()
                if stack:
                    stack[-1][1].subsections.append(section)
                else:
                    sections.append(section)
                stack.append((level, section))
            else:
                paragraph = DocumentParagraph(text=text, style=style, order=order)
                if stack:
                    stack[-1][1].paragraphs.append(paragraph)
                else:
                    flat.append(paragraph)
            order += 1

        return sections, flat

    @staticmethod
    def _heading_level(style: Optional[str]) -> Optional[int]:
        """Return the heading level from a style name like 'Heading 2'."""
        if not style or not style.lower().startswith("heading"):
            return None
        tail = style.split()[-1]
        return int(tail) if tail.isdigit() else 1

    # -- tables / images ---------------------------------------------------

    def _build_tables(self, document) -> List[DocumentTable]:
        tables: List[DocumentTable] = []
        for order, table in enumerate(document.tables):
            rows = [[cell.text for cell in row.cells] for row in table.rows]
            header = rows[0] if rows else None
            body = rows[1:] if len(rows) > 1 else []
            tables.append(DocumentTable(header=header, rows=body, order=order))
        return tables

    def _build_images(self, document) -> List[DocumentImage]:
        images: List[DocumentImage] = []
        order = 0
        for rel in document.part.rels.values():
            if "image" in rel.reltype:
                images.append(
                    DocumentImage(source_ref=rel.target_ref, order=order)
                )
                order += 1
        return images

    # -- deps --------------------------------------------------------------

    @staticmethod
    def _import_docx():
        try:
            import docx  # python-docx
        except ImportError as exc:  # pragma: no cover - depends on env
            raise ParserException(
                "The 'python-docx' package is not installed.",
                details={"provider": "docx"},
                cause=exc,
            )
        return docx
