"""
TreeStructureAgent - Provides complete document structure tree for UI visualization.

This agent extracts and returns the complete hierarchical structure of a PDF document
in a format optimized for tree visualization in the UI.

Provides insights such as:
- Full element hierarchy
- Element statistics and distribution
- Structure tree in JSON format
- Element filtering and search capabilities

Based on StructTreeExplorer for efficient traversal.
"""

from __future__ import annotations
from typing import Any

from src.modules.accessibility_plus.models.validation_issue import (
    Severity,
    ValidationIssue,
    ValidationStatus,
)
from .accessibility_agent_framework import BaseAccessibilityValidatorAgent
from .structure_tree_explorer import StructTreeExplorer, explore_document_structure


class TreeStructureAgent(BaseAccessibilityValidatorAgent):
    """Provides document structure tree extraction and analysis."""

    agent_code = "TREE_STRUCTURE_AGENT"
    agent_name = "Tree Structure Agent"
    category = "Document Structure"

    supported_checks = {
        "TREE-001",  # Get full tree structure
        "TREE-002",  # Get tree statistics
        "TREE-003",  # Get elements by type
    }

    @staticmethod
    def _issue(
        rule_id: str,
        severity: Severity,
        message: str,
        recommendation: str,
        status: ValidationStatus,
        auto_fixable: bool = False,
        value: Any = None,
    ) -> ValidationIssue:
        """Helper to construct ValidationIssue with common properties."""
        issue = ValidationIssue(
            agent_name=TreeStructureAgent.agent_name,
            rule_id=rule_id,
            category="Document Structure",
            severity=severity.value,
            page_no=None,
            message=message,
            recommendation=recommendation,
            auto_fixable=auto_fixable,
            status=status.value,
        )
        if value is not None:
            issue.value = value
        return issue

    def run_check(self, check_code: str, context: dict[str, Any]) -> ValidationIssue:
        """
        Execute structure tree extraction on PDF document.

        Args:
            check_code: Check identifier (e.g., TREE-001)
            context: Context dict containing:
                - pdf_doc: PDFix PdfDoc object (opened and ready)
                - pdf_doc_path: Path to PDF file
                - organization_id: Organization context
                - project_id: Project context
                - max_depth: (optional) Maximum traversal depth

        Returns:
            ValidationIssue with structure tree data as value
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

        # Use shared cache to avoid repeated traversals
        cache = context.setdefault("_cache", {})
        tree_cache = cache.setdefault("tree_structure_by_pdf", {})
        pdf_path = context.get("pdf_doc_path", "")
        
        check_handlers = {
            "TREE-001": self._get_full_tree,
            "TREE-002": self._get_tree_statistics,
            "TREE-003": self._get_elements_by_type,
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

            return handler(pdf_doc, check_code, context, tree_cache, pdf_path)
        except Exception as exc:
            return self._issue(
                rule_id=check_code,
                severity=Severity.HIGH,
                message=f"Structure extraction error: {str(exc)}",
                recommendation="Review the error and retry the extraction",
                status=ValidationStatus.FAIL,
            )

    @staticmethod
    def _get_full_tree(
        pdf_doc,
        check_code: str,
        context: dict,
        cache: dict,
        pdf_path: str,
    ) -> ValidationIssue:
        """Extract and return complete document structure tree."""
        try:
            # Check cache first
            if pdf_path in cache and "tree" in cache[pdf_path]:
                tree_structure = cache[pdf_path]["tree"]
            else:
                max_depth = context.get("max_depth")
                explorer = StructTreeExplorer(pdf_doc, max_depth=max_depth)
                tree_structure = explorer.get_tree_structure()
                
                # Cache the result
                cache.setdefault(pdf_path, {})["tree"] = tree_structure

            element_count = TreeStructureAgent._count_elements(tree_structure)

            return TreeStructureAgent._issue(
                rule_id=check_code,
                severity=Severity.MEDIUM,
                message=f"Document structure extracted successfully ({element_count} elements)",
                recommendation="Structure is ready for visualization",
                status=ValidationStatus.PASS,
                value=tree_structure,
            )
        except Exception as exc:
            return TreeStructureAgent._issue(
                rule_id=check_code,
                severity=Severity.HIGH,
                message=f"Error extracting tree structure: {str(exc)}",
                recommendation="Check PDF structure and retry",
                status=ValidationStatus.FAIL,
            )

    @staticmethod
    def _get_tree_statistics(
        pdf_doc,
        check_code: str,
        context: dict,
        cache: dict,
        pdf_path: str,
    ) -> ValidationIssue:
        """Get statistics about document structure."""
        try:
            # Check cache first
            if pdf_path in cache and "statistics" in cache[pdf_path]:
                statistics = cache[pdf_path]["statistics"]
            else:
                explorer = StructTreeExplorer(pdf_doc)
                statistics = explorer.get_tree_statistics()
                
                # Cache the result
                cache.setdefault(pdf_path, {})["statistics"] = statistics

            return TreeStructureAgent._issue(
                rule_id=check_code,
                severity=Severity.MEDIUM,
                message=(
                    f"Structure statistics: {statistics['total_elements']} elements, "
                    f"depth {statistics['max_depth']}, "
                    f"{len(statistics['element_types'])} unique types"
                ),
                recommendation="Statistics analyzed successfully",
                status=ValidationStatus.PASS,
                value=statistics,
            )
        except Exception as exc:
            return TreeStructureAgent._issue(
                rule_id=check_code,
                severity=Severity.HIGH,
                message=f"Error analyzing statistics: {str(exc)}",
                recommendation="Check PDF structure and retry",
                status=ValidationStatus.FAIL,
            )

    @staticmethod
    def _get_elements_by_type(
        pdf_doc,
        check_code: str,
        context: dict,
        cache: dict,
        pdf_path: str,
    ) -> ValidationIssue:
        """Get flat list of all elements for searching and filtering."""
        try:
            # Check cache first
            if pdf_path in cache and "flat_list" in cache[pdf_path]:
                flat_list = cache[pdf_path]["flat_list"]
            else:
                explorer = StructTreeExplorer(pdf_doc)
                flat_list = explorer.get_flat_element_list()
                
                # Cache the result
                cache.setdefault(pdf_path, {})["flat_list"] = flat_list

            type_counts = {}
            for elem in flat_list:
                elem_type = elem.get("type")
                type_counts[elem_type] = type_counts.get(elem_type, 0) + 1

            return TreeStructureAgent._issue(
                rule_id=check_code,
                severity=Severity.MEDIUM,
                message=f"Flat element list extracted ({len(flat_list)} elements)",
                recommendation="Ready for filtering and searching",
                status=ValidationStatus.PASS,
                value={
                    "total_elements": len(flat_list),
                    "type_counts": type_counts,
                    "elements": flat_list,
                },
            )
        except Exception as exc:
            return TreeStructureAgent._issue(
                rule_id=check_code,
                severity=Severity.HIGH,
                message=f"Error extracting flat list: {str(exc)}",
                recommendation="Check PDF structure and retry",
                status=ValidationStatus.FAIL,
            )

    @staticmethod
    def _count_elements(tree_dict: dict) -> int:
        """Recursively count elements in tree structure."""
        count = 1  # Count self
        if "children" in tree_dict:
            for child in tree_dict["children"]:
                count += TreeStructureAgent._count_elements(child)
        return count
