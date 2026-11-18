"""
TreeStructureRemediatorAgent - Remediates structural tree extraction issues.

Current auto-fixable rules from TreeStructureAgent: **none**.

    TREE-001  Full tree structure  → Informational output; not a fixable issue.
    TREE-002  Tree statistics      → Informational output; not a fixable issue.
    TREE-003  Elements by type     → Informational output; not a fixable issue.

This agent is a registered placeholder.  It is listed here for completeness
and to support future rules such as removing orphaned structure elements or
correcting malformed parent-child relationships.
"""

from __future__ import annotations

from typing import Any

from .base_remediator_agent import BaseRemediatorAgent, RemediationResult


class TreeStructureRemediatorAgent(BaseRemediatorAgent):
    """Placeholder remediator for tree-structure issues (no auto-fixes yet)."""

    agent_name = "Tree Structure Remediator Agent"

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
                f"TreeStructureRemediatorAgent: rule '{rule_id}' is not auto-fixable. "
                "Tree structure checks are informational and do not require remediation."
            ),
        )
