"""
TableRemediatorAgent - Remediates table accessibility issues in PDF documents.

Handles the following auto-fixable rule from TableAccessibilityAgent:

    TBL-004  Empty TH header cells
             → Traverses every ``Table → TR → TH`` element in the structure
               tree. For each TH whose ``GetText()`` is empty or whitespace,
               injects a generated header label ("Column N") via ``SetText()``.

Why only TBL-004?
    - TBL-001 (no tables): cannot create table structure automatically.
    - TBL-002 (no headers): converting TD→TH requires layout knowledge beyond
      what can be safely inferred; flagged for manual review.
    - TBL-003 (no rows): same structural complexity as TBL-002.
    - TBL-004 is safe to auto-fix because the header cells already exist in
      the structure; we are only populating their text content.
"""

from __future__ import annotations

from typing import Any

from src.core.logger import get_logger

from .base_remediator_agent import BaseRemediatorAgent, RemediationResult

logger = get_logger(__name__)


class TableRemediatorAgent(BaseRemediatorAgent):
    """Remediates table header cell accessibility issues using PDFix SDK."""

    agent_name = "Table Remediator Agent"

    supported_rules: set[str] = {
        "TBL-004",  # Empty TH header cells
    }

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def remediate(
        self,
        issue: dict[str, Any],
        context: dict[str, Any],
    ) -> RemediationResult:
        rule_id = issue.get("rule_id", "")
        if rule_id == "TBL-004":
            return self._fix_empty_headers(rule_id, context)
        return self._result(
            rule_id, False, "no_handler",
            error=f"TableRemediatorAgent: unsupported rule '{rule_id}'",
        )

    # ------------------------------------------------------------------
    # TBL-004 – Empty TH header cells
    # ------------------------------------------------------------------

    def _fix_empty_headers(
        self,
        rule_id: str,
        context: dict[str, Any],
    ) -> RemediationResult:
        """Set generated column labels on TH cells that contain no text."""
        pdf_doc = context.get("pdf_doc")
        if pdf_doc is None:
            return self._result(rule_id, False, "fix_empty_headers", error="pdf_doc not in context")

        changes: list[str] = []
        try:
            struct_tree = pdf_doc.GetStructTree()
            if not struct_tree:
                return self._result(
                    rule_id, False, "fix_empty_headers",
                    error="No structure tree – run DOC_IS_TAGGED remediation first",
                )

            _traverse_and_fix_headers(struct_tree, changes)

            # Invalidate table cache
            self._invalidate_cache(context, "tables_by_pdf")

            if not changes:
                return self._result(
                    rule_id, True, "fix_empty_headers",
                    changes_made=["No empty TH cells found – no changes made"],
                )
            return self._result(rule_id, True, "fix_empty_headers", changes_made=changes)

        except Exception as exc:
            logger.exception("TBL-004 remediation failed")
            return self._result(
                rule_id, False, "fix_empty_headers",
                changes_made=changes, error=str(exc),
            )


# ---------------------------------------------------------------------------
# Module-level traversal helpers
# ---------------------------------------------------------------------------

def _traverse_and_fix_headers(node: Any, changes: list[str], depth: int = 0) -> None:
    """
    Depth-first traversal to locate ``Table`` elements.

    When a Table is found, delegates to ``_fix_table_headers`` which iterates
    ``TR → TH`` cells and fills in empty ones.
    """
    try:
        num_children: int = node.GetNumChildren() if hasattr(node, "GetNumChildren") else 0
    except Exception:
        return

    for i in range(num_children):
        try:
            child = node.GetChildObject(i) if hasattr(node, "GetChildObject") else None
        except Exception:
            continue
        if child is None:
            continue

        try:
            el_type: str = child.GetType(True) if hasattr(child, "GetType") else ""
        except Exception:
            el_type = ""

        if el_type == "Table":
            try:
                table_page = child.GetPageNumber() + 1 if hasattr(child, "GetPageNumber") else "?"
                _fix_table_headers(child, table_page, changes)
            except Exception:
                pass
        else:
            # Recurse into non-table children (tables may be nested in sections)
            if hasattr(child, "GetNumChildren"):
                _traverse_and_fix_headers(child, changes, depth + 1)


def _fix_table_headers(table_node: Any, table_page: int | str, changes: list[str]) -> None:
    """
    Iterate ``Table → TR → TH`` and fill empty TH cells.

    Column indices are tracked per row; we use the first-row column position
    as the basis for generated labels ("Column 1", "Column 2", …).
    """
    try:
        num_rows: int = table_node.GetNumChildren() if hasattr(table_node, "GetNumChildren") else 0
    except Exception:
        return

    for row_idx in range(num_rows):
        try:
            row = table_node.GetChildObject(row_idx) if hasattr(table_node, "GetChildObject") else None
        except Exception:
            continue
        if row is None:
            continue

        try:
            row_type: str = row.GetType(True) if hasattr(row, "GetType") else ""
        except Exception:
            row_type = ""

        if row_type != "TR":
            continue

        _fix_row_headers(row, row_idx, table_page, changes)


def _fix_row_headers(
    row_node: Any,
    row_idx: int,
    table_page: int | str,
    changes: list[str],
) -> None:
    """Set generated labels on empty TH cells within a single TR element."""
    try:
        num_cells: int = row_node.GetNumChildren() if hasattr(row_node, "GetNumChildren") else 0
    except Exception:
        return

    col_idx = 0
    for cell_idx in range(num_cells):
        try:
            cell = row_node.GetChildObject(cell_idx) if hasattr(row_node, "GetChildObject") else None
        except Exception:
            col_idx += 1
            continue
        if cell is None:
            col_idx += 1
            continue

        try:
            cell_type: str = cell.GetType(True) if hasattr(cell, "GetType") else ""
        except Exception:
            col_idx += 1
            continue

        if cell_type == "TH":
            try:
                current_text: str = cell.GetText() if hasattr(cell, "GetText") else ""
                if not (current_text or "").strip():
                    label = f"Column {col_idx + 1}"
                    if hasattr(cell, "SetText"):
                        cell.SetText(label)
                        changes.append(
                            f"Table (page {table_page}) row {row_idx + 1} col {col_idx + 1}: "
                            f"TH text '' → '{label}'"
                        )
            except Exception:
                pass

        col_idx += 1
