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

from src.modules.accessibility_plus.models.validation_issue import (
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
        auto_fixable: bool = False,
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
        if pdf_path not in table_cache:
            struct_tree = pdf_doc.GetStructTree()
            tables = self._extract_tables(struct_tree) if struct_tree else []
            table_cache[pdf_path] = tables
        else:
            tables = table_cache[pdf_path]

        check_handlers = {
            "TBL-001": self._check_table_exists,
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
    def _check_table_exists(pdf_doc, check_code: str, tables: list[dict]) -> ValidationIssue:
        """Check if document contains properly tagged table elements."""
        try:
            has_tables = len(tables) > 0

            return TableAccessibilityAgent._issue(
                rule_id=check_code,
                severity=Severity.CRITICAL,
                message=(
                    f"Document contains {len(tables)} table(s)"
                    if has_tables
                    else "Document does not contain any structured tables"
                ),
                recommendation=(
                    "Tables are properly tagged in document structure"
                    if has_tables
                    else "Ensure tables are tagged as Table elements in PDF structure"
                ),
                status=ValidationStatus.PASS if has_tables else ValidationStatus.FAIL,
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
                auto_fixable=True,
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
    def _extract_tables(struct_tree) -> list[dict]:
        """
        Extract all tables from structure tree in a single traversal.
        
        Returns a list of dicts with structure:
        [
            {
                "id": "table_id",
                "page": 1,
                "row_count": 5,
                "column_count": 3,
                "header_count": 3,
                "empty_headers": 0,
                "headers": ["Name", "Age", "Location"]
            },
            ...
        ]
        
        This single traversal is cached and reused by all check methods,
        avoiding repeated tree traversals for large PDFs.
        """
        tables = []
        try:
            if not struct_tree:
                return tables

            def traverse(node, depth=0):
                """Recursively traverse structure tree collecting tables."""
                try:
                    num_children = node.GetNumChildren() if hasattr(node, "GetNumChildren") else 0
                    for i in range(num_children):
                        child = node.GetChildObject(i) if hasattr(node, "GetChildObject") else None
                        if not child:
                            continue

                        element_type = child.GetType(True) if hasattr(child, "GetType") else ""
                        
                        # Collect Table elements
                        if element_type == "Table":
                            try:
                                table_data = {
                                    "id": child.GetId() if hasattr(child, "GetId") else "",
                                    "page": child.GetPageNumber() if hasattr(child, "GetPageNumber") else None,
                                    "type": element_type,
                                    "row_count": 0,
                                    "column_count": 0,
                                    "header_count": 0,
                                    "empty_headers": 0,
                                    "headers": [],
                                }
                                
                                # Extract table rows and cells
                                rows = []
                                tbl_children = child.GetNumChildren() if hasattr(child, "GetNumChildren") else 0
                                for row_idx in range(tbl_children):
                                    row_elem = child.GetChildObject(row_idx) if hasattr(child, "GetChildObject") else None
                                    if not row_elem:
                                        continue
                                    
                                    row_type = row_elem.GetType(True) if hasattr(row_elem, "GetType") else ""
                                    
                                    # Process row elements (TR)
                                    if row_type == "TR":
                                        cells = []
                                        row_children = row_elem.GetNumChildren() if hasattr(row_elem, "GetNumChildren") else 0
                                        for cell_idx in range(row_children):
                                            cell_elem = row_elem.GetChildObject(cell_idx) if hasattr(row_elem, "GetChildObject") else None
                                            if not cell_elem:
                                                continue
                                            
                                            cell_type = cell_elem.GetType(True) if hasattr(cell_elem, "GetType") else ""
                                            
                                            # Process header and data cells
                                            if cell_type in ["TH", "TD"]:
                                                cell_text = cell_elem.GetText() if hasattr(cell_elem, "GetText") else ""
                                                cells.append({
                                                    "type": cell_type,
                                                    "text": cell_text.strip() if cell_text else ""
                                                })
                                                
                                                # Track headers
                                                if cell_type == "TH":
                                                    table_data["header_count"] += 1
                                                    table_data["headers"].append(cell_text.strip() if cell_text else "")
                                                    if not cell_text or not cell_text.strip():
                                                        table_data["empty_headers"] += 1
                                        
                                        if cells:
                                            rows.append(cells)
                                            table_data["column_count"] = max(table_data["column_count"], len(cells))
                                
                                table_data["row_count"] = len(rows)
                                tables.append(table_data)
                            except (AttributeError, Exception):
                                pass

                        # Recurse into children
                        if hasattr(child, "GetNumChildren"):
                            traverse(child, depth + 1)
                except Exception:
                    pass

            traverse(struct_tree)
        except Exception:
            pass

        return tables

