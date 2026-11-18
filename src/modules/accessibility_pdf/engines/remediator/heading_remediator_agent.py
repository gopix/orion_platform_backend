"""
HeadingRemediatorAgent
----------------------
Schedules heading-related fixes as post-processing steps.

Handled rules:
    HDR-001  Missing H1 — triggers run_heading_fix.py
    HDR-005  Invalid heading parent type — triggers run_heading_parent_fix.py
             (PAC Matterhorn "Invalid use of Hn structure element")

Both fixes always run unconditionally in the pipeline, so scheduling them
here just marks the issue as handled and sets a context flag for logging.
"""
from __future__ import annotations
from typing import Any

from src.core.logger import get_logger
from .base_remediator_agent import BaseRemediatorAgent, RemediationResult

logger = get_logger(__name__)


class HeadingRemediatorAgent(BaseRemediatorAgent):
    """Schedules heading fix + bookmark generation + parent-type fix in post-processing."""

    agent_name     = "Heading Remediator Agent"
    supported_rules: set[str] = {"HDR-001", "HDR-005"}

    def remediate(self, issue: dict[str, Any], context: dict[str, Any]) -> RemediationResult:
        rule_id = issue.get("rule_id", "HDR-001")

        if rule_id == "HDR-005":
            context["_fix_heading_parents"] = True
            logger.info(
                "HeadingRemediatorAgent: scheduled heading-parent fix | rule=%s", rule_id
            )
            return self._result(
                rule_id,
                success=True,
                action="schedule_heading_parent_fix",
                changes_made=[
                    "Scheduled invalid heading parent re-parenting to run as "
                    "post-processing step (run_heading_parent_fix.py)."
                ],
            )

        # HDR-001 (and any other HDR-* we might add)
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
