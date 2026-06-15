"""
StructureHeadingAgent - Validates PDF document heading structure and hierarchy.

Checks include:
- HDR-001: Document Contains H1 - at least one H1 must exist
- HDR-002: Only One H1 - only one primary H1 should exist
- HDR-003: No Heading Level Skip - H1 → H2 → H3 allowed, not H1 → H3 (forward skips only)
- HDR-004: Heading Must Contain Text - heading tags must contain visible text

Based on WCAG 2.1 and PDF-UA accessibility standards.

Uses PDFix SDK for validation:
    pdf_doc.GetStructTree()
    struct_tree.GetChildren()
    element.GetType()
    element.GetNumChildren()
"""

from __future__ import annotations
from typing import Any


from src.modules.accessibility_plus.models.validation_issue import (
    Severity,
    ValidationIssue,
    ValidationStatus,
)
from .accessibility_agent_framework import BaseAccessibilityValidatorAgent


class StructureHeadingAgent(BaseAccessibilityValidatorAgent):
    """Validates document heading structure and hierarchy."""

    agent_code = "STRUCTURE_HEADING_AGENT"
    agent_name = "Structure Heading Agent"
    category = "Document Structure"

    supported_checks = {
        "HDR-001",
        "HDR-002",
        "HDR-003",
        "HDR-004",
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
            agent_name=StructureHeadingAgent.agent_name,
            rule_id=rule_id,
            category="Document Structure",
            severity=severity.value,
            page_no=None,
            message=message,
            recommendation=recommendation,
            auto_fixable=auto_fixable,
            status=status.value,
        )

    def run_check(self, check_code: str, context: dict[str, Any]) -> ValidationIssue:
        """
        Execute accessibility check on PDF document heading structure.

        Args:
            check_code: Check identifier (e.g., HDR-001)
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

        # Extract headings once per PDF to avoid repeated tree traversals
        cache = context.setdefault("_cache", {})
        heading_cache = cache.setdefault("headings_by_pdf", {})
        pdf_path = context.get("pdf_doc_path", "")
        if pdf_path not in heading_cache:
            struct_tree = pdf_doc.GetStructTree()
            headings = self._extract_headings(struct_tree) if struct_tree else []
            heading_cache[pdf_path] = headings
        else:
            headings = heading_cache[pdf_path]

        check_handlers = {
            "HDR-001": self._check_h1_exists,
            "HDR-002": self._check_only_one_h1,
            "HDR-003": self._check_no_heading_skip,
            "HDR-004": self._check_heading_text,
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

            return handler(pdf_doc, check_code, headings)
        except Exception as exc:
            return self._issue(
                rule_id=check_code,
                severity=Severity.HIGH,
                message=f"Check execution error: {str(exc)}",
                recommendation="Review the error and retry the check",
                status=ValidationStatus.FAIL,
            )

    @staticmethod
    def _check_h1_exists(pdf_doc, check_code: str, headings: list[dict]) -> ValidationIssue:
        """Check if document contains at least one H1 heading."""
        try:
            h1_count = sum(1 for h in headings if h["level"] == 1)
            has_h1 = h1_count > 0

            return StructureHeadingAgent._issue(
                rule_id=check_code,
                severity=Severity.CRITICAL,
                message=(
                    f"Document contains {h1_count} H1 heading(s)"
                    if has_h1
                    else "Document does not contain any H1 headings"
                ),
                recommendation=(
                    "H1 heading is present"
                    if has_h1
                    else "Add at least one H1 heading at the document start"
                ),
                status=ValidationStatus.PASS if has_h1 else ValidationStatus.FAIL,
            )
        except Exception as exc:
            return StructureHeadingAgent._issue(
                rule_id=check_code,
                severity=Severity.HIGH,
                message=f"Error checking for H1 headings: {str(exc)}",
                recommendation="Check PDF structure and retry",
                status=ValidationStatus.FAIL,
            )

    @staticmethod
    def _check_only_one_h1(pdf_doc, check_code: str, headings: list[dict]) -> ValidationIssue:
        """Check if document contains only one H1 heading."""
        try:
            h1_count = sum(1 for h in headings if h["level"] == 1)
            only_one_h1 = h1_count == 1

            return StructureHeadingAgent._issue(
                rule_id=check_code,
                severity=Severity.MEDIUM,
                message=(
                    "Document contains exactly one H1 heading"
                    if only_one_h1
                    else f"Document contains {h1_count} H1 headings (should be exactly 1)"
                ),
                recommendation=(
                    "Primary H1 is unique"
                    if only_one_h1
                    else "Ensure only one H1 heading exists as document primary heading"
                ),
                status=ValidationStatus.PASS if only_one_h1 else ValidationStatus.FAIL,
            )
        except Exception as exc:
            return StructureHeadingAgent._issue(
                rule_id=check_code,
                severity=Severity.HIGH,
                message=f"Error checking H1 count: {str(exc)}",
                recommendation="Check PDF structure and retry",
                status=ValidationStatus.FAIL,
            )

    @staticmethod
    def _check_no_heading_skip(pdf_doc, check_code: str, headings: list[dict]) -> ValidationIssue:
        """Check if heading levels follow proper hierarchy without skipping."""
        try:
            if not headings:
                return StructureHeadingAgent._issue(
                    rule_id=check_code,
                    severity=Severity.MEDIUM,
                    message="No headings found in document",
                    recommendation="Add heading tags to document for proper structure",
                    status=ValidationStatus.WARNING,
                )

            has_skips = StructureHeadingAgent._has_heading_skips(headings)

            return StructureHeadingAgent._issue(
                rule_id=check_code,
                severity=Severity.HIGH,
                message=(
                    "Heading levels follow proper hierarchy without skipping"
                    if not has_skips
                    else "Heading levels skip levels (e.g., H1 → H3)"
                ),
                recommendation=(
                    "Heading hierarchy is sequential"
                    if not has_skips
                    else "Ensure heading levels follow H1 → H2 → H3 progression without gaps"
                ),
                status=ValidationStatus.PASS if not has_skips else ValidationStatus.FAIL,
            )
        except Exception as exc:
            return StructureHeadingAgent._issue(
                rule_id=check_code,
                severity=Severity.HIGH,
                message=f"Error checking heading hierarchy: {str(exc)}",
                recommendation="Check PDF structure and retry",
                status=ValidationStatus.FAIL,
            )

    @staticmethod
    def _check_heading_text(pdf_doc, check_code: str, headings: list[dict]) -> ValidationIssue:
        """Check if all heading tags contain visible text."""
        try:
            if not headings:
                return StructureHeadingAgent._issue(
                    rule_id=check_code,
                    severity=Severity.MEDIUM,
                    message="No headings found in document",
                    recommendation="Add heading tags to document for proper structure",
                    status=ValidationStatus.WARNING,
                )

            empty_headings = [h for h in headings if not h.get("text", "").strip()]
            all_have_text = len(empty_headings) == 0

            return StructureHeadingAgent._issue(
                rule_id=check_code,
                severity=Severity.HIGH,
                message=(
                    f"All {len(headings)} headings contain visible text"
                    if all_have_text
                    else f"{len(empty_headings)} out of {len(headings)} headings are empty"
                ),
                recommendation=(
                    "Heading text content is present"
                    if all_have_text
                    else "Ensure all heading tags contain meaningful visible text"
                ),
                status=ValidationStatus.PASS if all_have_text else ValidationStatus.FAIL,
            )
        except Exception as exc:
            return StructureHeadingAgent._issue(
                rule_id=check_code,
                severity=Severity.HIGH,
                message=f"Error checking heading text: {str(exc)}",
                recommendation="Check PDF structure and retry",
                status=ValidationStatus.FAIL,
            )

    @staticmethod
    def _extract_headings(struct_tree) -> list[dict]:
        """
        Extract all headings from structure tree in a single traversal.
        
        Returns a list of dicts with structure:
        [
            {"level": 1, "text": "Introduction"},
            {"level": 2, "text": "Background"},
            ...
        ]
        
        This single traversal is cached and reused by all check methods,
        avoiding repeated tree traversals for large PDFs.
        """
        headings = []
        try:
            if not struct_tree:
                return headings

            def resolve_struct_element(node):
                if node is None:
                    return None
                if hasattr(node, "GetType"):
                    return node
                if hasattr(struct_tree, "GetStructElementFromObject"):
                    try:
                        resolved = struct_tree.GetStructElementFromObject(node)
                        if resolved is not None:
                            return resolved
                    except Exception:
                        pass
                return node

            def traverse(node):
                """Recursively traverse structure tree collecting headings."""
                try:
                    num_children = node.GetNumChildren() if hasattr(node, "GetNumChildren") else 0
                    for i in range(num_children):
                        child = node.GetChildObject(i) if hasattr(node, "GetChildObject") else None
                        child = resolve_struct_element(child)
                        if not child:
                            continue

                        element_type = child.GetType() if hasattr(child, "GetType") else ""
                        
                        # Check if this is a heading element (H1, H2, ..., H6)
                        if element_type and element_type.startswith("H") and len(element_type) == 2:
                            try:
                                level = int(element_type[1])
                                text = child.GetText() if hasattr(child, "GetText") else ""
                                headings.append({"level": level, "text": text.strip()})
                            except (ValueError, AttributeError):
                                pass

                        # Recurse into children
                        if hasattr(child, "GetNumChildren"):
                            traverse(child)
                except Exception:
                    pass

            traverse(struct_tree)
        except Exception:
            pass

        return headings

    @staticmethod
    def _has_heading_skips(headings: list[dict]) -> bool:
        """Check if heading sequence has forward level skips (e.g., H1 → H3).
        
        Backward navigation (H3 → H1) is allowed as section resets.
        Only forward skips without intermediate levels are violations.
        """
        if len(headings) < 2:
            return False

        try:
            for i in range(len(headings) - 1):
                current_level = headings[i]["level"]
                next_level = headings[i + 1]["level"]
                
                # Flag only forward skips (e.g., H1 → H3)
                # Backward navigation (e.g., H3 → H1) is a reset, not a skip
                if next_level > current_level + 1:
                    return True
        except (ValueError, IndexError, TypeError, KeyError):
            pass

        return False

