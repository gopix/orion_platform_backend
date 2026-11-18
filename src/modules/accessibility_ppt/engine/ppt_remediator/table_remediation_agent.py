"""
table_remediation_agent.py
==========================
TableRemediationAgent — makes tables screen-reader friendly, mutating
context["presentation"] in place.

Rules handled (supported_rules)
    PPT-TABLE-001  No header row      -> enable Header Row (first row = headers)
    PPT-TABLE-002  Merged cells       -> split EMPTY merges (safe subset)
    PPT-TABLE-003  Blank header cells -> label them 'Column N'

Automatic actions (per the remediation spec)
    ✓ enable Header Row + identify the first row as headers
    ✓ label blank header cells
    ✓ remove fully-blank columns (only when no merges touch the table)
    ✓ simplify merged cells WHERE SAFE — an empty merged region is split back
      into individual cells; a merge that still holds data is left intact and
      reported (auto-unmerging real data would scramble the table).

Order of operations per table: split empty merges -> (if now merge-free) remove
blank columns -> enable header -> label blank headers. Each table is wrapped in
try/except so one malformed table never aborts the run.
"""
from __future__ import annotations

from typing import Any

from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.oxml.ns import qn

from src.modules.accessibility_ppt.engine.ppt_remediator.base_remediation_agent import (
    BasePPTRemediationAgent,
    RemediationResult,
)


class TableRemediationAgent(BasePPTRemediationAgent):
    """Enable headers, label them, drop blank columns, split empty merges."""

    agent_name = "PPT Table Remediation Agent"
    supported_rules = {"PPT-TABLE-001", "PPT-TABLE-002", "PPT-TABLE-003"}

    def remediate(self, issue: dict[str, Any],
                  context: dict[str, Any]) -> RemediationResult:
        rule_id = (issue or {}).get("rule_id", "PPT-TABLE-001")
        try:
            prs = self._presentation(context)
        except ValueError as exc:
            return self._result(rule_id, False, "table", error=str(exc))

        changes: list[str] = []
        merges_left: list[int] = []
        for si, gf in self._iter_table_frames(prs):
            try:
                self._fix_one_table(gf, si + 1, changes, merges_left)
            except Exception as exc:
                changes.append(f"slide {si + 1}: table skipped ({exc})")

        err = None
        if merges_left:
            err = (f"non-empty merged cells remain on slide(s) "
                   f"{', '.join(map(str, sorted(set(merges_left))))} — split them "
                   "manually if the data needs a simple grid")
        return self._result(rule_id, True, "fix_tables",
                            changes_made=changes, error=err)

    # ------------------------------------------------------------- iteration
    def _iter_table_frames(self, prs):
        for si, shape in self._iter_shapes(prs):
            try:
                if shape.has_table:
                    yield si, shape
            except Exception:
                continue

    # --------------------------------------------------------------- per table
    def _fix_one_table(self, gf, slide_no, changes, merges_left):
        table = gf.table

        # 1) split EMPTY merged regions; remember non-empty ones
        split = 0
        had_nonempty_merge = False
        for r in range(len(table.rows)):
            for c in range(len(table.columns)):
                cell = table.cell(r, c)
                if not cell.is_merge_origin:
                    continue
                if (cell.text or "").strip():
                    had_nonempty_merge = True
                else:
                    try:
                        cell.split()
                        split += 1
                    except Exception:
                        had_nonempty_merge = True
        if split:
            changes.append(f"slide {slide_no}: split {split} empty merged cell(s)")
        if had_nonempty_merge:
            merges_left.append(slide_no)

        table = gf.table                      # refresh after structural change

        # 2) remove fully-blank columns (only when the table has no merges)
        if not self._has_merges(table) and len(table.columns) > 1:
            removed = self._remove_blank_columns(table)
            if removed:
                changes.append(f"slide {slide_no}: removed {removed} blank column(s)")
            table = gf.table

        # 3) enable header row on real data tables
        if len(table.rows) >= 2 and not bool(table.first_row):
            table.first_row = True
            changes.append(f"slide {slide_no}: enabled header row")

        # 4) label blank header cells
        if bool(table.first_row) and len(table.rows) >= 1:
            labelled = 0
            for c in range(len(table.columns)):
                cell = table.cell(0, c)
                if cell.is_spanned:
                    continue
                if not (cell.text or "").strip():
                    cell.text = f"Column {c + 1}"
                    labelled += 1
            if labelled:
                changes.append(f"slide {slide_no}: labelled {labelled} blank "
                               "header cell(s)")

    # --------------------------------------------------------------- helpers
    @staticmethod
    def _has_merges(table) -> bool:
        for r in range(len(table.rows)):
            for c in range(len(table.columns)):
                cell = table.cell(r, c)
                if cell.is_merge_origin or cell.is_spanned:
                    return True
        return False

    @staticmethod
    def _remove_blank_columns(table) -> int:
        n_cols = len(table.columns)
        n_rows = len(table.rows)
        blanks = [c for c in range(n_cols)
                  if all(not (table.cell(r, c).text or "").strip()
                         for r in range(n_rows))]
        if not blanks or len(blanks) >= n_cols:      # never delete every column
            blanks = blanks[:n_cols - 1] if len(blanks) >= n_cols else blanks
        removed = 0
        tbl = table._tbl
        grid = tbl.find(qn("a:tblGrid"))
        for c in sorted(blanks, reverse=True):       # right-to-left keeps indices
            cols = grid.findall(qn("a:gridCol"))
            if c < len(cols):
                grid.remove(cols[c])
            for tr in tbl.findall(qn("a:tr")):
                tcs = tr.findall(qn("a:tc"))
                if c < len(tcs):
                    tr.remove(tcs[c])
            removed += 1
        return removed
