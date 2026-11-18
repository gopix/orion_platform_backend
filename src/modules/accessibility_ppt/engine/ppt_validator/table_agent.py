"""
table_agent.py
==============
TableAgent — validates every table (including tables nested in groups) on every
slide.

Checks (supported_checks)
    PPT-TABLE-001  Header row       (a data table with no header row)
    PPT-TABLE-002  Merged cells     (merged/spanned cells that break AT navigation)
    PPT-TABLE-003  Blank headers    (header row present but some header cells empty)
    PPT-TABLE-004  Reading order    (single-row/col table likely used for layout)
    PPT-TABLE-005  Table description (table graphic frame missing alt/description)

Reads the normalized context from ppt_loader: a table shape carries
    shape["table"] = {"rows","cols","header_row","has_merged","cells"}
and, like every shape, "alt_text". Each check returns one ValidationIssue,
aggregating findings across the deck.
"""
from __future__ import annotations

from typing import Any

from src.modules.accessibility_pdf.models.validation_issue import ValidationIssue
from src.modules.accessibility_ppt.engine.ppt_validator.base_agent import (
    BasePPTAccessibilityValidatorAgent,
)


class TableAgent(BasePPTAccessibilityValidatorAgent):
    """Validate table structure and semantics across slides."""

    agent_code = "PPT_TABLE_AGENT"
    agent_name = "PPT Table Agent"
    category = "Tables"
    supported_checks = {
        "PPT-TABLE-001",
        "PPT-TABLE-002",
        "PPT-TABLE-003",
        "PPT-TABLE-004",
        "PPT-TABLE-005",
    }

    # ---------------------------------------------------------------- dispatch
    def run_check(self, check_code: str, context: dict[str, Any]) -> ValidationIssue:
        slides = context.get("slides")
        slides = slides if isinstance(slides, list) else []

        dispatch = {
            "PPT-TABLE-001": self._check_header_row,
            "PPT-TABLE-002": self._check_merged_cells,
            "PPT-TABLE-003": self._check_blank_headers,
            "PPT-TABLE-004": self._check_reading_order,
            "PPT-TABLE-005": self._check_description,
        }
        handler = dispatch.get(check_code)
        if handler is None:
            return self._info(check_code, f"Check {check_code} is not implemented yet",
                              "Implement the requested table check")
        return handler(slides)

    # ---------------------------------------------------------------- helpers
    def _issue(self, rule_id, severity, status, message, recommendation,
               page_no=None, auto_fixable=False, internal=False) -> ValidationIssue:
        return ValidationIssue(
            agent_name=self.agent_name, rule_id=rule_id, category=self.category,
            severity=severity, page_no=page_no, message=message,
            recommendation=recommendation, auto_fixable=auto_fixable,
            status=status, internal_check=internal,
        )

    def _pass(self, rule_id, message, recommendation) -> ValidationIssue:
        return self._issue(rule_id, "LOW", "PASS", message, recommendation)

    def _info(self, rule_id, message, recommendation) -> ValidationIssue:
        return self._issue(rule_id, "LOW", "INFO", message, recommendation,
                           internal=True)

    @staticmethod
    def _slide_no(slide: dict, order_idx: int) -> int:
        idx = slide.get("index")
        return (idx + 1) if isinstance(idx, int) else (order_idx + 1)

    @staticmethod
    def _is_table(shape: dict) -> bool:
        if str(shape.get("type", "")).lower() == "table":
            return True
        return isinstance(shape.get("table"), dict)

    def _iter_tables(self, slides):
        """Yield (slide_no, shape, table_dict), recursing into groups."""
        def walk(shapes, sno):
            for sh in shapes:
                if not isinstance(sh, dict):
                    continue
                if self._is_table(sh) and isinstance(sh.get("table"), dict):
                    yield sno, sh, sh["table"]
                children = sh.get("shapes")
                if isinstance(children, list):
                    yield from walk(children, sno)

        for order_idx, slide in enumerate(slides):
            if not isinstance(slide, dict):
                continue
            sno = self._slide_no(slide, order_idx)
            shapes = slide.get("shapes")
            if isinstance(shapes, list):
                yield from walk(shapes, sno)

    @staticmethod
    def _rows(table: dict) -> int:
        r = table.get("rows")
        return r if isinstance(r, int) else 0

    @staticmethod
    def _cols(table: dict) -> int:
        c = table.get("cols")
        return c if isinstance(c, int) else 0

    # ---------------------------------------------------------------- 001 header
    def _check_header_row(self, slides) -> ValidationIssue:
        offenders = []
        total = 0
        for sno, _shape, table in self._iter_tables(slides):
            # Only true data tables (>=2 rows) need a header row.
            if self._rows(table) < 2:
                continue
            total += 1
            if not bool(table.get("header_row")):
                offenders.append(sno)
        if total == 0:
            return self._pass("PPT-TABLE-001", "No multi-row data tables found.",
                              "Give every data table a header row.")
        if offenders:
            slides_hit = sorted(set(offenders))
            return self._issue(
                "PPT-TABLE-001", "HIGH", "FAIL",
                f"{len(offenders)} table(s) have no header row on slide(s) "
                f"{', '.join(map(str, slides_hit))}.",
                "Enable the 'Header Row' option so the first row is exposed as "
                "column headers to screen readers.",
                page_no=slides_hit[0], auto_fixable=True)
        return self._pass("PPT-TABLE-001",
                          f"All {total} data table(s) have a header row.",
                          "Keep a header row on every data table.")

    # ---------------------------------------------------------------- 002 merged
    def _check_merged_cells(self, slides) -> ValidationIssue:
        offenders = []
        for sno, _shape, table in self._iter_tables(slides):
            if bool(table.get("has_merged")):
                offenders.append(sno)
        if offenders:
            slides_hit = sorted(set(offenders))
            return self._issue(
                "PPT-TABLE-002", "MEDIUM", "WARNING",
                f"{len(offenders)} table(s) contain merged/spanned cells on "
                f"slide(s) {', '.join(map(str, slides_hit))}.",
                "Avoid merged cells in data tables; they disrupt row/column "
                "navigation for screen-reader users. Split into simple tables.",
                page_no=slides_hit[0], auto_fixable=False)
        return self._pass("PPT-TABLE-002", "No merged cells in any table.",
                          "Keep tables simple and rectangular.")

    # ---------------------------------------------------------------- 003 blank hdr
    def _check_blank_headers(self, slides) -> ValidationIssue:
        offenders = []
        evaluated = False
        for sno, _shape, table in self._iter_tables(slides):
            if not bool(table.get("header_row")):
                continue
            cells = table.get("cells")
            if not isinstance(cells, list) or not cells:
                continue
            header = cells[0]
            if not isinstance(header, list):
                continue
            evaluated = True
            blanks = sum(1 for c in header if not (isinstance(c, str) and c.strip()))
            if blanks:
                offenders.append((sno, blanks))
        if not evaluated:
            return self._pass("PPT-TABLE-003", "No header rows to inspect.",
                              "Ensure header cells are labelled once headers exist.")
        if offenders:
            slides_hit = sorted({s for s, _ in offenders})
            return self._issue(
                "PPT-TABLE-003", "HIGH", "FAIL",
                f"{len(offenders)} table(s) have blank header cell(s) on slide(s) "
                f"{', '.join(map(str, slides_hit))}.",
                "Give every column a non-empty header label so each data cell is "
                "announced with its column name.",
                page_no=slides_hit[0], auto_fixable=False)
        return self._pass("PPT-TABLE-003", "All header cells are labelled.",
                          "Keep every column header populated.")

    # ---------------------------------------------------------------- 004 layout
    def _check_reading_order(self, slides) -> ValidationIssue:
        offenders = []
        for sno, _shape, table in self._iter_tables(slides):
            rows, cols = self._rows(table), self._cols(table)
            # A 1xN or Nx1 grid with no header is almost always a layout device,
            # not tabular data — screen readers still announce it as a table,
            # confusing the reading order.
            if (rows == 1 or cols == 1) and not bool(table.get("header_row")):
                offenders.append((sno, f"{rows}x{cols}"))
        if offenders:
            slides_hit = sorted({s for s, _ in offenders})
            return self._issue(
                "PPT-TABLE-004", "LOW", "WARNING",
                f"{len(offenders)} single-row/column table(s) look like layout "
                f"tables on slide(s) {', '.join(map(str, slides_hit))}.",
                "If the table is only for positioning, rebuild the content with "
                "text boxes/placeholders so the reading order stays logical; "
                "reserve tables for genuine tabular data.",
                page_no=slides_hit[0], auto_fixable=False)
        return self._pass("PPT-TABLE-004",
                          "No layout-style tables detected.",
                          "Use tables only for tabular data.")

    # ---------------------------------------------------------------- 005 descr
    def _check_description(self, slides) -> ValidationIssue:
        offenders = []
        total = 0
        for sno, shape, _table in self._iter_tables(slides):
            total += 1
            alt = shape.get("alt_text")
            if not (isinstance(alt, str) and alt.strip()):
                offenders.append((sno, shape.get("name") or "table"))
        if total == 0:
            return self._pass("PPT-TABLE-005", "No tables found.",
                              "Add a short description to tables you insert.")
        if offenders:
            slides_hit = sorted({s for s, _ in offenders})
            return self._issue(
                "PPT-TABLE-005", "MEDIUM", "WARNING",
                f"{len(offenders)} table(s) have no description/alt text on "
                f"slide(s) {', '.join(map(str, slides_hit))}.",
                "Add alt text summarising the table's purpose (e.g. 'Rainfall by "
                "month for 2025') so its intent is clear before the cells are read.",
                page_no=slides_hit[0], auto_fixable=False)
        return self._pass("PPT-TABLE-005",
                          f"All {total} table(s) have a description.",
                          "Summarise each table's purpose in its alt text.")
