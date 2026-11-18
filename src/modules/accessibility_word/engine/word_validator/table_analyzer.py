"""Step 6: table structure."""
from __future__ import annotations

from src.modules.accessibility_word.engine.word_validator.base_analyzer import BaseAnalyzer, Item


class TableAnalyzer(BaseAnalyzer):
    name = "TableAnalyzer"
    category = "TABLE_ACCESSIBILITY"

    def _evaluate(self, ctx, rec, rule_id, build):
        if not ctx.tables:
            rec.not_applicable(rule_id, "The document has no tables.")
            return
        rec.evaluate(rule_id, [item for item in map(build, ctx.tables) if item])

    def check_tbl_001_header_row(self, ctx, rec):
        self._evaluate(ctx, rec, "TBL-001", lambda t: None if t.has_header_row else Item(
            "The first row is not marked as a header row", t.location))

    def check_tbl_002_merged_cells(self, ctx, rec):
        self._evaluate(ctx, rec, "TBL-002", lambda t: None if not t.merged_cells else Item(
            f"The table has {t.merged_cells} merged cells", t.location))

    def check_tbl_003_nested(self, ctx, rec):
        self._evaluate(ctx, rec, "TBL-003", lambda t: None if not t.depth else Item(
            "The table is nested inside another table", t.location))

    def check_tbl_004_blank_cells(self, ctx, rec):
        self._evaluate(ctx, rec, "TBL-004", lambda t: None if not (t.blank_rows or t.blank_columns) else Item(
            f"The table has {t.blank_rows} blank rows and {t.blank_columns} blank columns", t.location))

    def check_tbl_005_description(self, ctx, rec):
        self._evaluate(ctx, rec, "TBL-005", lambda t: None if (t.caption or t.description) else Item(
            "The table has no title or description", t.location))

    def check_tbl_006_layout_tables(self, ctx, rec):
        if not ctx.tables:
            rec.not_applicable("TBL-006", "The document has no tables.")
            return
        items = [Item(f"A {t.rows}x{t.columns} table may be used only for layout", t.location)
                 for t in ctx.tables if t.rows <= 1 or t.columns <= 1]
        if items:
            rec.manual("TBL-006", items, "Heuristic match; a person must confirm each one.")
        else:
            rec.evaluate("TBL-006", [])
