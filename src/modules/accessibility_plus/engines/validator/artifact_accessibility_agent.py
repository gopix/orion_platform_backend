"""
ArtifactAccessibilityAgent
--------------------------
Validates that PDF content is not wrongly tagged as Artifact.

Agent code : ARTIFACT_ACCESSIBILITY_AGENT
Check code : ARTIFACT-001  — wrongly artifacted text / bad artifact types
"""
from __future__ import annotations
from typing import Any

from src.modules.accessibility_plus.models.validation_issue import (
    Severity, ValidationIssue, ValidationStatus,
)
from .accessibility_agent_framework import BaseAccessibilityValidatorAgent
from src.core.logger import get_logger

logger = get_logger(__name__)


class ArtifactAccessibilityAgent(BaseAccessibilityValidatorAgent):
    """Check for content wrongly tagged as Artifact."""

    agent_code = "ARTIFACT_ACCESSIBILITY_AGENT"
    agent_name = "Artifact Accessibility Agent"
    category   = "Content Accessibility"

    supported_checks = {"ARTIFACT-001"}

    @staticmethod
    def _issue(
        rule_id: str,
        severity: Severity,
        message: str,
        recommendation: str,
        status: ValidationStatus,
        auto_fixable: bool = False,
        page_no: int | None = None,
    ) -> ValidationIssue:
        return ValidationIssue(
            agent_name=ArtifactAccessibilityAgent.agent_name,
            rule_id=rule_id,
            category=ArtifactAccessibilityAgent.category,
            severity=severity.value,
            page_no=page_no,
            message=message,
            recommendation=recommendation,
            auto_fixable=auto_fixable,
            status=status.value,
        )

    def run_check(self, check_code: str, context: dict[str, Any]) -> ValidationIssue:
        if check_code not in self.supported_checks:
            return self._issue(
                rule_id=check_code,
                severity=Severity.MEDIUM,
                message=f"Check code {check_code} is not supported",
                recommendation="Use ARTIFACT-001",
                status=ValidationStatus.FAIL,
            )

        pdf_path = context.get("pdf_doc_path", "")
        if not pdf_path:
            return self._issue(
                rule_id=check_code,
                severity=Severity.HIGH,
                message="pdf_doc_path not set in context",
                recommendation="Ensure pdf_doc_path is provided",
                status=ValidationStatus.FAIL,
            )

        try:
            from src.modules.accessibility_plus.engines.artifact_fixer import find_artifact_issues
            issues = find_artifact_issues(pdf_path)
        except Exception as exc:
            logger.error("ArtifactAccessibilityAgent error: %s", exc)
            return self._issue(
                rule_id=check_code,
                severity=Severity.HIGH,
                message=f"Artifact check failed: {exc}",
                recommendation="Check artifact_fixer.py dependencies (pikepdf)",
                status=ValidationStatus.FAIL,
            )

        if not issues:
            return self._issue(
                rule_id=check_code,
                severity=Severity.LOW,
                message="No wrongly-artifacted content detected.",
                recommendation="No action required.",
                status=ValidationStatus.PASS,
                auto_fixable=False,
            )

        text_issues = [i for i in issues if i['type'] == 'wrong_artifact_text']
        bg_issues   = [i for i in issues if i['type'] == 'wrong_artifact_type']
        desc = (
            f"{len(text_issues)} text artifact(s) hidden from screen readers; "
            f"{len(bg_issues)} decorative fill(s) with wrong /Type/Layout."
        )
        return self._issue(
            rule_id=check_code,
            severity=Severity.HIGH,
            message=desc,
            recommendation=(
                "Re-tag text artifacts as MCID-tagged content; "
                "change decorative fills from /Type/Layout to /Type/Background."
            ),
            status=ValidationStatus.FAIL,
            auto_fixable=True,
        )
