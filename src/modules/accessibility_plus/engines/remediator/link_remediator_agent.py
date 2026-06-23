"""
LinkRemediatorAgent
-------------------
Schedules the pikepdf link-tag fix to run as a post-processing step
after PDFix has saved the remediated document.

Sets context["_fix_missing_links"] = True; the actual fix is applied
in AccessibilityRemediationPipeline._save_remediated_pdf Step 4.

Handled rule: LINK-001  (matches LinkAccessibilityAgent check code)
"""

from __future__ import annotations
from typing import Any

from src.core.logger import get_logger
from src.modules.accessibility_plus.engines.remediator.base_remediator_agent import (
    BaseRemediatorAgent,
    RemediationResult,
)

logger = get_logger(__name__)


class LinkRemediatorAgent(BaseRemediatorAgent):
    """Schedules the pikepdf link-tag fix to run in post-processing."""

    agent_name = "Link Remediator Agent"
    supported_rules: set[str] = {"LINK-001"}

    def remediate(self, issue: dict[str, Any], context: dict[str, Any]) -> RemediationResult:
        rule_id = issue.get("rule_id", "LINK-001")
        context["_fix_missing_links"] = True
        logger.info("LinkRemediatorAgent: scheduled link-tag fix | rule=%s", rule_id)
        return self._result(
            rule_id,
            success=True,
            action="schedule_link_fix",
            changes_made=[
                "Scheduled pikepdf Link annotation + <Link> structure-element fix "
                "to run as a post-processing step after PDFix saves the document."
            ],
        )
