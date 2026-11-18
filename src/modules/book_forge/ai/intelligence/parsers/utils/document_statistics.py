"""DocumentStatistics — summary metrics for a parsed document.

Walks a ``ParsedDocument`` (including its nested section tree) and totals up the
sections, paragraphs, tables, images, and words — handy for dashboards, logging,
and sanity-checking a parse. Stateless and pure: no I/O, no configuration.
"""
from typing import Any, Dict, List

from src.modules.book_forge.ai.intelligence.parsers.models import (
    DocumentSection,
    ParsedDocument,
)


class DocumentStatistics:
    """Compute summary statistics over a :class:`ParsedDocument`."""

    @staticmethod
    def calculate(document: ParsedDocument) -> Dict[str, Any]:
        """Return totals across the document's flat lists and section tree."""
        sections = 0
        paragraphs = list(document.paragraphs)
        tables = len(document.tables)
        images = len(document.images)

        def walk(section_list: List[DocumentSection]) -> None:
            nonlocal sections, tables, images
            for section in section_list:
                sections += 1
                paragraphs.extend(section.paragraphs)
                tables += len(section.tables)
                images += len(section.images)
                walk(section.subsections)

        walk(document.sections)

        word_count = sum(len(p.text.split()) for p in paragraphs)
        return {
            "total_sections": sections,
            "total_paragraphs": len(paragraphs),
            "total_tables": tables,
            "total_images": images,
            "total_words": word_count,
            "page_count": document.metadata.page_count,
        }
