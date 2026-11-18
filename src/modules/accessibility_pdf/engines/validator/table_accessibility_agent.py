"""
TableAccessibilityAgent - Validates PDF table accessibility using PDFix metadata.

Checks include:
- TBL-001: Table tags exist in document structure
- TBL-002: Table contains header cells (TH elements)
- TBL-003: Table contains data rows (TR elements)
- TBL-004: Header cells must not be empty

PDFix-based validation using:
    pdf_doc.GetStructTree()
    element.GetType() == "Table"
    traverse Table → TR (rows) → TH/TD (cells)
    element.GetText() for cell content

No external dependencies - pure PDFix metadata + rule-based validation.
"""

from __future__ import annotations
from typing import Any

from src.modules.accessibility_pdf.models.validation_issue import (
    Severity,
    ValidationIssue,
    ValidationStatus,
)
from .accessibility_agent_framework import BaseAccessibilityValidatorAgent


class TableAccessibilityAgent(BaseAccessibilityValidatorAgent):
    """Validates table accessibility in documents using PDFix metadata."""

    agent_code = "TABLE_ACCESSIBILITY_AGENT"
    agent_name = "Table Accessibility Agent"
    category = "Table Accessibility"

    supported_checks = {
        "TBL-001",
        "TBL-002",
        "TBL-003",
        "TBL-004",
    }

    @staticmethod
    def _issue(
        rule_id: str,
        severity: Severity,
        message: str,
        recommendation: str,
        status: ValidationStatus,
        auto_fixable: bool | None = None,
    ) -> ValidationIssue:
        """Helper to construct ValidationIssue with common properties."""
        return ValidationIssue(
            agent_name=TableAccessibilityAgent.agent_name,
            rule_id=rule_id,
            category="Table Accessibility",
            severity=severity.value,
            page_no=None,
            message=message,
            recommendation=recommendation,
            auto_fixable=auto_fixable,
            status=status.value,
        )

    def run_check(self, check_code: str, context: dict[str, Any]) -> ValidationIssue:
        """
        Execute accessibility check on PDF document tables.

        Args:
            check_code: Check identifier (e.g., TBL-001)
            context: Context dict containing:
                - pdf_doc: PDFix PdfDoc object (opened and ready)
                - pdf_doc_path: Path to PDF file
                - organization_id: Organization context
                - project_id: Project context

        Returns:
            ValidationIssue with check results
        """
        if check_code not in self.supported_checks:
            return self._issue(
                rule_id=check_code,
                severity=Severity.MEDIUM,
                message=f"Check code {check_code} is not supported",
                recommendation="Use a valid check code from supported_checks",
                status=ValidationStatus.FAIL,
            )

        pdf_doc = context.get("pdf_doc")
        if not pdf_doc:
            return self._issue(
                rule_id=check_code,
                severity=Severity.CRITICAL,
                message="PDF document not provided in context",
                recommendation="Ensure PDF document is opened and provided in context",
                status=ValidationStatus.FAIL,
            )

        # Extract tables once per PDF to avoid repeated tree traversals
        cache = context.setdefault("_cache", {})
        table_cache = cache.setdefault("tables_by_pdf", {})
        pdf_path = context.get("pdf_doc_path", "")
        # Key the cache on (path, size, mtime), not path alone: the pipeline
        # re-validates the REMEDIATED file, and several stages rewrite a file
        # in place. Keying on path alone would serve the pre-remediation result
        # back for the post-remediation check.
        try:
            import os
            stat = os.stat(pdf_path)
            cache_key = (pdf_path, stat.st_size, stat.st_mtime_ns)
        except Exception:
            cache_key = (pdf_path, None, None)

        if cache_key not in table_cache:
            struct_tree = pdf_doc.GetStructTree() if pdf_doc else None
            tables = self._extract_tables(struct_tree, pdf_path)
            table_cache[cache_key] = tables
        else:
            tables = table_cache[cache_key]

        check_handlers = {
            "TBL-001": lambda doc, code, tabs: self._check_table_exists(doc, code, tabs, pdf_path),
            "TBL-002": self._check_header_cells,
            "TBL-003": self._check_rows_exist,
            "TBL-004": self._check_empty_headers,
        }

        try:
            handler = check_handlers.get(check_code)
            if not handler:
                return self._issue(
                    rule_id=check_code,
                    severity=Severity.MEDIUM,
                    message=f"Unknown check code: {check_code}",
                    recommendation="Verify check code is in supported_checks",
                    status=ValidationStatus.FAIL,
                )

            return handler(pdf_doc, check_code, tables)
        except Exception as exc:
            return self._issue(
                rule_id=check_code,
                severity=Severity.HIGH,
                message=f"Check execution error: {str(exc)}",
                recommendation="Review the error and retry the check",
                status=ValidationStatus.FAIL,
            )

    @staticmethod
    def _check_table_exists(
        pdf_doc, check_code: str, tables: list[dict], pdf_path: str = ""
    ) -> ValidationIssue:
        """Check if document contains properly tagged table elements.

        Logic:
        - Structured Table elements found → PASS
        - No structured tables, but pdfplumber detects visual tables → FAIL
          (tables exist but are untagged)
        - No structured tables, no visual tables → PASS
          (document genuinely has no tables; rule is trivially satisfied)
        """
        try:
            # Structured tables found — straightforward pass
            if tables:
                return TableAccessibilityAgent._issue(
                    rule_id=check_code,
                    severity=Severity.CRITICAL,
                    message=f"Document contains {len(tables)} properly tagged table(s)",
                    recommendation="Tables are properly tagged in document structure",
                    status=ValidationStatus.PASS,
                )

            # No structured tables — check for visual tables via pdfplumber.
            #
            # pdfplumber's default strategy infers a table from ANY intersecting
            # ruled lines, so a decorative header rule, a page border or an
            # aligned bulleted list is happily reported as a "table". On this
            # document it claimed 12 tables, including one on each of pages 1-4,
            # which contain no table at all. Reporting that count to the user as
            # "12 visual tables that are not tagged" is simply false.
            #
            # A grid is only treated as a real table if it has at least 2 rows
            # AND at least 2 columns AND more than one row carries actual text.
            # A 1xN or Nx1 strip, or a grid of empty cells, is decoration.
            visual_table_count = 0
            if pdf_path:
                try:
                    import pdfplumber
                    with pdfplumber.open(pdf_path) as plumb:
                        for page in plumb.pages:
                            for grid in (page.extract_tables() or []):
                                if not grid or len(grid) < 2:
                                    continue
                                if max(len(r) for r in grid) < 2:
                                    continue
                                filled = sum(
                                    1 for r in grid
                                    if any((c or "").strip() for c in r)
                                )
                                if filled >= 2:
                                    visual_table_count += 1
                except Exception:
                    pass  # pdfplumber unavailable or failed — stay conservative

            if visual_table_count == 0:
                # Document genuinely has no tables — rule is trivially satisfied
                return TableAccessibilityAgent._issue(
                    rule_id=check_code,
                    severity=Severity.CRITICAL,
                    message="No tables found in document",
                    recommendation="No action required — document does not contain tables",
                    status=ValidationStatus.PASS,
                )

            # Visual tables exist but lack Table structure tags — actual failure
            return TableAccessibilityAgent._issue(
                rule_id=check_code,
                severity=Severity.CRITICAL,
                message=(
                    f"Document contains {visual_table_count} visual table(s) "
                    "that are not tagged as Table elements in PDF structure"
                ),
                recommendation="Tag all tables as Table elements using a PDF authoring tool",
                status=ValidationStatus.FAIL,
            )

        except Exception as exc:
            return TableAccessibilityAgent._issue(
                rule_id=check_code,
                severity=Severity.HIGH,
                message=f"Error checking for tables: {str(exc)}",
                recommendation="Check PDF structure and retry",
                status=ValidationStatus.FAIL,
            )

    @staticmethod
    def _check_header_cells(pdf_doc, check_code: str, tables: list[dict]) -> ValidationIssue:
        """Check if tables contain header cells (TH elements)."""
        try:
            if not tables:
                return TableAccessibilityAgent._issue(
                    rule_id=check_code,
                    severity=Severity.MEDIUM,
                    message="No tables found in document",
                    recommendation="If document contains tables, ensure they are properly tagged",
                    status=ValidationStatus.PASS,
                )

            tables_with_headers = sum(1 for t in tables if t.get("header_count", 0) > 0)
            all_have_headers = tables_with_headers == len(tables)

            return TableAccessibilityAgent._issue(
                rule_id=check_code,
                severity=Severity.HIGH,
                message=(
                    f"All {len(tables)} table(s) contain header cells"
                    if all_have_headers
                    else f"{tables_with_headers} out of {len(tables)} tables contain header cells"
                ),
                recommendation=(
                    "All tables have header cells defined"
                    if all_have_headers
                    else "Add TH (header) cells to all tables using PDF authoring tool"
                ),
                status=ValidationStatus.PASS if all_have_headers else ValidationStatus.FAIL,
            )
        except Exception as exc:
            return TableAccessibilityAgent._issue(
                rule_id=check_code,
                severity=Severity.HIGH,
                message=f"Error checking header cells: {str(exc)}",
                recommendation="Check PDF structure and retry",
                status=ValidationStatus.FAIL,
            )

    @staticmethod
    def _check_rows_exist(pdf_doc, check_code: str, tables: list[dict]) -> ValidationIssue:
        """Check if tables contain row elements (TR)."""
        try:
            if not tables:
                return TableAccessibilityAgent._issue(
                    rule_id=check_code,
                    severity=Severity.MEDIUM,
                    message="No tables found in document",
                    recommendation="If document contains tables, ensure they are properly tagged",
                    status=ValidationStatus.PASS,
                )

            tables_with_rows = sum(1 for t in tables if t.get("row_count", 0) > 0)
            all_have_rows = tables_with_rows == len(tables)

            return TableAccessibilityAgent._issue(
                rule_id=check_code,
                severity=Severity.HIGH,
                message=(
                    f"All {len(tables)} table(s) contain data rows"
                    if all_have_rows
                    else f"{tables_with_rows} out of {len(tables)} tables contain rows"
                ),
                recommendation=(
                    "All tables have properly structured rows"
                    if all_have_rows
                    else "Ensure all table data is organized in TR (row) elements"
                ),
                status=ValidationStatus.PASS if all_have_rows else ValidationStatus.FAIL,
            )
        except Exception as exc:
            return TableAccessibilityAgent._issue(
                rule_id=check_code,
                severity=Severity.HIGH,
                message=f"Error checking table rows: {str(exc)}",
                recommendation="Check PDF structure and retry",
                status=ValidationStatus.FAIL,
            )

    @staticmethod
    def _check_empty_headers(pdf_doc, check_code: str, tables: list[dict]) -> ValidationIssue:
        """Check if all header cells (TH) contain text."""
        try:
            if not tables:
                return TableAccessibilityAgent._issue(
                    rule_id=check_code,
                    severity=Severity.MEDIUM,
                    message="No tables found in document",
                    recommendation="If document contains tables, ensure they are properly tagged",
                    status=ValidationStatus.PASS,
                )

            # Collect all empty headers across all tables
            total_headers = sum(t.get("header_count", 0) for t in tables)
            empty_headers = sum(t.get("empty_headers", 0) for t in tables)
            all_headers_filled = empty_headers == 0

            return TableAccessibilityAgent._issue(
                rule_id=check_code,
                severity=Severity.HIGH,
                message=(
                    f"All {total_headers} header cell(s) contain text"
                    if all_headers_filled
                    else f"{empty_headers} out of {total_headers} header cells are empty"
                ),
                recommendation=(
                    "All header cells have text content"
                    if all_headers_filled
                    else "Ensure all TH header cells contain descriptive text"
                ),
                status=ValidationStatus.PASS if all_headers_filled else ValidationStatus.FAIL,
                auto_fixable=None if all_headers_filled else True,
            )
        except Exception as exc:
            return TableAccessibilityAgent._issue(
                rule_id=check_code,
                severity=Severity.HIGH,
                message=f"Error checking header cell text: {str(exc)}",
                recommendation="Check PDF structure and retry",
                status=ValidationStatus.FAIL,
            )

    @staticmethod
    def _extract_tables(struct_tree, pdf_path: str = "") -> list[dict]:
        """Extract every <Table> in the structure tree.

        Reads the structure tree directly from the PDF with pikepdf rather than
        walking it through PDFix.

        Why: the previous implementation traversed with
        ``node.GetChildObject(i)`` and then tested ``child.GetType(True) ==
        "Table"``.  ``GetChildObject()`` returns a **PdsObject** (a raw PDF
        object), not a PdsStructElement -- a PdsObject has no ``GetType(bool)``
        returning a struct tag name.  The defensive ``hasattr(child, "GetType")``
        guard swallowed that, so ``element_type`` was always "" and NOTHING ever
        matched "Table".  The result: this returned [] for every document, no
        matter how well tagged.

        The knock-on effects were silent and severe:
          * TBL-001 always fell through to the pdfplumber "visual table"
            fallback and reported a document with perfectly tagged tables as
            FAIL / CRITICAL.
          * TBL-002/003/004 all take a ``if not tables: -> PASS`` early exit,
            so they reported PASS without ever inspecting a single table.
            Header, row and empty-header validation were dead code.

        Returns the same dict shape the check handlers already expect.
        """
        tables: list[dict] = []
        if not pdf_path:
            return tables

        try:
            import pikepdf
        except Exception:
            return tables

        try:
            pdf = pikepdf.open(pdf_path)
        except Exception:
            return tables

        try:
            st = pdf.Root.get("/StructTreeRoot")
            if st is None:
                return tables

            page_no = {p.obj.objgen: i + 1 for i, p in enumerate(pdf.pages)}

            def kids(e):
                k = e.get("/K")
                if k is None:
                    return []
                return list(k) if isinstance(k, pikepdf.Array) else [k]

            def is_elem(k):
                if not isinstance(k, pikepdf.Dictionary):
                    return False
                t = k.get("/Type")
                return not (t is not None and str(t) != "/StructElem")

            def tag(e):
                s = e.get("/S")
                return str(s).lstrip("/") if s is not None else ""

            def scope_of(e):
                a = e.get("/A")
                if isinstance(a, pikepdf.Dictionary) and "/Scope" in a:
                    return str(a["/Scope"]).lstrip("/")
                if isinstance(a, pikepdf.Array):
                    for item in a:
                        if isinstance(item, pikepdf.Dictionary) and "/Scope" in item:
                            return str(item["/Scope"]).lstrip("/")
                return None

            def first_page(e, inherited=None):
                """Table elements often carry no /Pg -- inherit, else descend."""
                pg = e.get("/Pg") or inherited
                if pg is not None:
                    n = page_no.get(pg.objgen)
                    if n:
                        return n
                for k in kids(e):
                    if isinstance(k, pikepdf.Dictionary):
                        n = first_page(k, pg) if is_elem(k) else None
                        if n:
                            return n
                        kpg = k.get("/Pg")
                        if kpg is not None and page_no.get(kpg.objgen):
                            return page_no[kpg.objgen]
                return None

            def has_content(e):
                """True if the cell references any marked content."""
                for k in kids(e):
                    if isinstance(k, int):
                        return True
                    if isinstance(k, pikepdf.Dictionary):
                        if str(k.get("/Type", "")) == "/MCR":
                            return True
                        if is_elem(k) and has_content(k):
                            return True
                return False

            def walk(e, pg=None):
                pg = e.get("/Pg") or pg
                if tag(e) == "Table":
                    rows = [r for r in kids(e) if is_elem(r) and tag(r) == "TR"]
                    headers, empty_headers, no_scope, ncols = [], 0, 0, 0
                    for r in rows:
                        cells = [c for c in kids(r)
                                 if is_elem(c) and tag(c) in ("TH", "TD")]
                        ncols = max(ncols, len(cells))
                        for c in cells:
                            if tag(c) != "TH":
                                continue
                            headers.append(c)
                            if not has_content(c):
                                empty_headers += 1
                            if not scope_of(c):
                                no_scope += 1
                    tables.append({
                        "id": str(e.objgen[0]) if e.is_indirect else "",
                        "page": first_page(e, pg),
                        "type": "Table",
                        "row_count": len(rows),
                        "column_count": ncols,
                        "header_count": len(headers),
                        "empty_headers": empty_headers,
                        "headers_missing_scope": no_scope,
                        "headers": [],
                    })
                for k in kids(e):
                    if is_elem(k):
                        walk(k, pg)

            walk(st)
        except Exception:
            return tables
        finally:
            try:
                pdf.close()
            except Exception:
                pass

        return tables

