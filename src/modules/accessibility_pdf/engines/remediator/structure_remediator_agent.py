"""
StructureRemediatorAgent - Remediates heading / document-structure issues.

Current auto-fixable rules from StructureHeadingAgent: **none**.

    HDR-001  No H1 heading         → Cannot be auto-fixed (no content to tag).
    HDR-002  Multiple H1 headings  → Changing heading levels requires semantic
                                     understanding of the content.
    HDR-003  Heading level skips   → Safe automatic re-numbering is ambiguous
                                     without understanding document intent.
    HDR-004  Empty heading tags    → Empty headings should be removed or filled;
                                     both require authoring context.

This agent is registered with the service so it can be extended as PDFix
SDK exposes richer structure-editing APIs or as AI-assisted remediation is
introduced for heading re-labelling.
"""

from __future__ import annotations

from typing import Any

from .base_remediator_agent import BaseRemediatorAgent, RemediationResult


class StructureRemediatorAgent(BaseRemediatorAgent):
    """Placeholder remediator for heading/structure issues (no auto-fixes yet)."""

    agent_name = "Structure Remediator Agent"

    # No rules are auto-fixable in the current validator
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
                f"StructureRemediatorAgent: rule '{rule_id}' is not auto-fixable. "
                "Heading structure remediation requires authoring-level intervention."
            ),
        )
