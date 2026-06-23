"""
HeadingRemediatorAgent
----------------------
Schedules the heading tag fix + bookmark generation as a post-processing step.

Handled rule: HDR-001  (matches StructureHeadingAgent check code)
"""
from __future__ import annotations
from typing import Any

from src.core.logger import get_logger
from .base_remediator_agent import BaseRemediatorAgent, RemediationResult

logger = get_logger(__name__)


class HeadingRemediatorAgent(BaseRemediatorAgent):
    """Schedules heading fix + bookmark generation in pipeline post-processing."""

    agent_name     = "Heading Remediator Agent"
    supported_rules: set[str] = {"HDR-001"}

    def remediate(self, issue: dict[str, Any], context: dict[str, Any]) -> RemediationResult:
        rule_id = issue.get("rule_id", "HDR-001")
        context["_fix_headings"] = True
        logger.info("HeadingRemediatorAgent: scheduled heading fix | rule=%s", rule_id)
        return self._result(
            rule_id,
            success=True,
            action="schedule_heading_fix",
            changes_made=[
                "Scheduled heading tag fix + PDF bookmark generation to run as "
                "post-processing step after PDFix saves the document."
            ],
        )
