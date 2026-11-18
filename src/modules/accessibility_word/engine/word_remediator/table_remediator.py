"""Fixes table header rows, blank rows and missing table titles."""
from __future__ import annotations

import re

from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from src.modules.accessibility_word.engine.word_remediator.base_remediator import BaseRemediator
from src.modules.accessibility_word.engine.word_remediator.ooxml_utils import (
    TBLPR_CAPTION_SUCCESSORS,
    TRPR_HEADER_SUCCESSORS,
    get_or_insert,
    get_or_insert_first,
    has_visual_content,
    is_alternate_fallback,
    paragraph_text,
    snippet,
    table_rows,
)

_TABLE_LABEL = re.compile(r"^\s*(table|tbl\.?)\s*[\dIVXivx]+", re.IGNORECASE)


class TableRemediator(BaseRemediator):
    name = "TableRemediator"
    # Blank rows go first so the header row is the first real row.
    fixes = {
        "TBL-004": "fix_blank_rows",
        "TBL-001": "fix_header_rows",
        "TBL-005": "fix_titles",
    }

    @staticmethod
    def _tables(ctx):
        return [t for t in ctx.body.iter(qn("w:tbl")) if not is_alternate_fallback(t)]

    # ---- TBL-004 -------------------------------------------------------
    def fix_blank_rows(self, ctx, rec):
        columns_only = False
        for index, tbl in enumerate(self._tables(ctx)):
            rows = list(table_rows(tbl))
            blank = [r for r in rows if self._row_is_blank(r)]
            if not blank:
                columns_only = True
                continue
            if len(blank) == len(rows):
                blank = blank[1:]          # never empty a table completely
            for row in blank:
                row.getparent().remove(row)
            if blank:
                rec.applied(f"Table {index + 1}", f"Removed {len(blank)} blank rows")
        if not rec.actions and columns_only:
            rec.skip("Only blank columns were found; remove them manually.")

    @staticmethod
    def _row_is_blank(row) -> bool:
        if row.find(".//" + qn("w:vMerge")) is not None:
            return False                   # deleting it would break a vertical merge
        if row.find(".//" + qn("w:tbl")) is not None or has_visual_content(row):
            return False
        return not paragraph_text(row).strip()

    # ---- TBL-001 -------------------------------------------------------
    def fix_header_rows(self, ctx, rec):
        single_row = 0
        for index, tbl in enumerate(self._tables(ctx)):
            rows = list(table_rows(tbl))
            if len(rows) < 2:
                single_row += 1
                continue
            first = rows[0]
            trpr = get_or_insert_first(first, "w:trPr", after=("w:tblPrEx",))
            header = get_or_insert(trpr, "w:tblHeader", TRPR_HEADER_SUCCESSORS)
            if header.get(qn("w:val")) in ("0", "false", "off"):
                del header.attrib[qn("w:val")]
            rec.applied(f"Table {index + 1}", "Marked the first row as a repeating header row",
                        review=True, detail="Assumes the first row holds the column headers.")
        if not rec.actions and single_row:
            rec.skip("Single-row tables have no data rows to label; review them manually.")

    # ---- TBL-005 -------------------------------------------------------
    def fix_titles(self, ctx, rec):
        limit = ctx.options.max_caption_chars
        missing = 0
        for index, tbl in enumerate(self._tables(ctx)):
            tblpr = get_or_insert_first(tbl, "w:tblPr")
            caption = tblpr.find(qn("w:tblCaption"))
            description = tblpr.find(qn("w:tblDescription"))
            if any(el is not None and (el.get(qn("w:val")) or "").strip()
                   for el in (caption, description)):
                continue
            text = self._caption_text(ctx, tbl)
            if not text:
                missing += 1
                continue
            get_or_insert(tblpr, "w:tblCaption", TBLPR_CAPTION_SUCCESSORS).set(qn("w:val"), text[:limit])
            rec.applied(f"Table {index + 1}", f'Set the table title to "{snippet(text)}"',
                        detail="Taken from the adjacent caption.")
        if missing and not rec.actions:
            rec.skip("No caption was found next to the tables; add titles manually.")

    def _caption_text(self, ctx, tbl) -> str | None:
        for neighbour in (tbl.getprevious(), tbl.getnext()):
            if neighbour is None or neighbour.tag != qn("w:p"):
                continue
            text = paragraph_text(neighbour).strip()
            if not text:
                continue
            style = Paragraph(neighbour, ctx.document._body).style
            if (style is not None and (style.name or "").lower().startswith("caption")) \
                    or _TABLE_LABEL.match(text):
                return " ".join(text.split())
        return None
