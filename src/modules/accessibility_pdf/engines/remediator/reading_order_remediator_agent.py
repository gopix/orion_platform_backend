"""
ReadingOrderRemediatorAgent - Remediates reading-order issues in PDF documents.

Current auto-fixable rules from ReadingOrderAgent: **none**.

    UNTAGGED_PDF                → Delegated to DocumentRemediatorAgent (DOC_IS_TAGGED).
    EMPTY_STRUCTURE_TREE        → Delegated to DocumentRemediatorAgent (DOC_IS_TAGGED).
    CONTENT_EXTRACTION_VALIDATION → Internal check; not surfaced to users.
    MULTICOLUMN_POSSIBLE        → Requires layout-aware re-ordering; no safe auto-fix.
    WORD_READING_ORDER          → Correcting tag order vs. content order requires
                                  structure-tree re-sequencing, which PDFix does not
                                  expose as a single API call.

This agent is registered so it can be extended once PDFix exposes
``ReorderStructureElements`` or equivalent functionality.
"""

from __future__ import annotations

from typing import Any

from .base_remediator_agent import BaseRemediatorAgent, RemediationResult


class ReadingOrderRemediatorAgent(BaseRemediatorAgent):
    """Placeholder remediator for reading-order issues (no auto-fixes yet)."""

    agent_name = "Reading Order Remediator Agent"

    supported_rules: set[str] = set()

    def remediate(
        self,
        issue: dict[str, Any],
        context: dict[str, Any],
    ) -> RemediationResult:
        rule_id = issue.get("rule_id", "")
        return self._result(
            rule_id,
            success=False,
            action="not_implemented",
            error=(
                f"ReadingOrderRemediatorAgent: rule '{rule_id}' is not auto-fixable. "
                "Reading-order corrections require structure-tree re-sequencing."
            ),
        )
