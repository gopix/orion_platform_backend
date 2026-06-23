"""
ArtifactRemediatorAgent
-----------------------
Schedules the artifact fix to run as a post-processing step.

Handled rule: ARTIFACT-001
"""
from __future__ import annotations
from typing import Any

from src.core.logger import get_logger
from .base_remediator_agent import BaseRemediatorAgent, RemediationResult

logger = get_logger(__name__)


class ArtifactRemediatorAgent(BaseRemediatorAgent):
    """Schedules artifact fix to run in pipeline post-processing."""

    agent_name     = "Artifact Remediator Agent"
    supported_rules: set[str] = {"ARTIFACT-001"}

    def remediate(self, issue: dict[str, Any], context: dict[str, Any]) -> RemediationResult:
        rule_id = issue.get("rule_id", "ARTIFACT-001")
        context["_fix_artifacts"] = True
        logger.info("ArtifactRemediatorAgent: scheduled artifact fix | rule=%s", rule_id)
        return self._result(
            rule_id,
            success=True,
            action="schedule_artifact_fix",
            changes_made=[
                "Scheduled artifact content fix to run as post-processing step: "
                "re-tag wrongly-artifacted text and correct /Type/Layout → /Type/Background."
            ],
        )
