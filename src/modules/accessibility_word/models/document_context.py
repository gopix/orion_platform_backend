"""Read-only view of a DOCX. Built once by DocxParser and shared by all analyzers."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RunInfo:
    text: str
    bold: bool = False
    italic: bool = False
    underline: bool = False
    caps: bool = False
    hidden: bool = False
    size_pt: float = 10.0
    color: str | None = None        # RRGGBB; None means automatic
    background: str = "FFFFFF"
    background_known: bool = True   # False when the fill comes from a table style or shape
    vert_align: str | None = None
    lang: str | None = None


@dataclass
class ParagraphInfo:
    index: int
    part: str
    container: str                  # body | table | textbox | header | footer | footnote | endnote
    text: str = ""
    style_id: str | None = None
    style_name: str | None = None
    heading_level: int | None = None
    is_list: bool = False
    justification: str | None = None
    runs: list[RunInfo] = field(default_factory=list)
    has_drawing: bool = False
    has_page_break: bool = False
    has_section_break: bool = False
    table_index: int | None = None
    section: str | None = None      # nearest preceding heading

    @property
    def location(self) -> str:
        where = f'under "{self.section}"' if self.section else "before the first heading"
        if self.container in ("header", "footer", "footnote", "endnote", "textbox"):
            return f"{self.container.capitalize()} ({self.part}), {where}"
        if self.table_index is not None:
            return f"Table {self.table_index + 1}, {where}"
        return f"Paragraph {self.index + 1}, {where}"


@dataclass
class ImageInfo:
    index: int
    kind: str                       # picture | chart | diagram | shape | group | vml | ole
    part: str
    container: str
    alt: str = ""
    title: str = ""
    name: str = ""
    target: str | None = None
    decorative: bool = False
    floating: bool = False
    section: str | None = None

    @property
    def location(self) -> str:
        where = f'under "{self.section}"' if self.section else "before the first heading"
        label = self.name or self.kind
        return f'Image {self.index + 1} ("{label}"), {self.container}, {where}'


@dataclass
class TextBoxInfo:
    index: int
    text: str
    part: str
    floating: bool
    section: str | None = None

    @property
    def location(self) -> str:
        where = f'under "{self.section}"' if self.section else "before the first heading"
        return f"Text box {self.index + 1}, {where}"


@dataclass
class TableInfo:
    index: int
    part: str
    container: str
    rows: int = 0
    columns: int = 0
    depth: int = 0                  # 0 is top level; above 0 is nested
    has_header_row: bool = False
    merged_cells: int = 0
    blank_rows: int = 0
    blank_columns: int = 0
    caption: str = ""
    description: str = ""
    style_id: str | None = None
    section: str | None = None

    @property
    def location(self) -> str:
        where = f'under "{self.section}"' if self.section else "before the first heading"
        return f"Table {self.index + 1}, {where}"


@dataclass
class HyperlinkInfo:
    text: str
    target: str | None
    anchor: str | None
    location: str


@dataclass
class SectionInfo:
    index: int
    columns: int = 1


@dataclass
class DocumentMetadata:
    title: str = ""
    author: str = ""
    subject: str = ""
    keywords: str = ""
    core_language: str = ""
    default_language: str = ""
    application: str = ""
    pages_reported: int | None = None


@dataclass
class DocumentContext:
    file_name: str
    file_size: int
    sha256: str
    metadata: DocumentMetadata = field(default_factory=DocumentMetadata)
    paragraphs: list[ParagraphInfo] = field(default_factory=list)
    images: list[ImageInfo] = field(default_factory=list)
    text_boxes: list[TextBoxInfo] = field(default_factory=list)
    tables: list[TableInfo] = field(default_factory=list)
    hyperlinks: list[HyperlinkInfo] = field(default_factory=list)
    sections: list[SectionInfo] = field(default_factory=list)
    has_toc: bool = False
    tracked_changes: int = 0
    comments: int = 0
    word_count: int = 0
    # XML parts that exist but could not be parsed. Analyzers that depend on one
    # report "failed" instead of drawing conclusions from missing data.
    failed_parts: dict[str, str] = field(default_factory=dict)
    # Supplied by the caller; see ScreenReaderValidator.
    screen_reader_evidence: list[dict[str, Any]] = field(default_factory=list)

    @property
    def body_paragraphs(self) -> list[ParagraphInfo]:
        return [p for p in self.paragraphs if p.container == "body"]

    @property
    def headings(self) -> list[ParagraphInfo]:
        return [
            p for p in self.paragraphs
            if p.heading_level is not None and p.container in ("body", "table")
        ]
