"""
LinkAccessibilityAgent
----------------------
Validates that every URL/email in the document has a proper <Link>
structure element (PDF/UA "Completeness of Link elements" check).

Agent code : LINK_ACCESSIBILITY_AGENT
Check code : LINK-001
"""

from __future__ import annotations
from typing import Any

from src.modules.accessibility_plus.models.validation_issue import (
    Severity,
    ValidationIssue,
    ValidationStatus,
)
from .accessibility_agent_framework import BaseAccessibilityValidatorAgent

from src.core.logger import get_logger
logger = get_logger(__name__)


class LinkAccessibilityAgent(BaseAccessibilityValidatorAgent):
    """Check for URLs/emails that lack a <Link> structure element."""

    agent_code = "LINK_ACCESSIBILITY_AGENT"
    agent_name = "Link Accessibility Agent"
    category = "Link Accessibility"

    supported_checks = {
        "LINK-001",  # Completeness of Link elements
    }

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
            agent_name=LinkAccessibilityAgent.agent_name,
            rule_id=rule_id,
            category=LinkAccessibilityAgent.category,
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
                recommendation="Use LINK-001",
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
            from src.modules.accessibility_plus.engines.link_fixer import find_missing_links
            missing = find_missing_links(pdf_path)
        except Exception as exc:
            logger.error("LinkAccessibilityAgent.run_check error: %s", exc)
            return self._issue(
                rule_id=check_code,
                severity=Severity.HIGH,
                message=f"Link check failed: {exc}",
                recommendation="Check link_fixer.py dependencies (pdfplumber, pikepdf)",
                status=ValidationStatus.FAIL,
            )

        if not missing:
            return self._issue(
                rule_id=check_code,
                severity=Severity.LOW,
                message="All URLs/emails have <Link> structure elements.",
                recommendation="No action required.",
                status=ValidationStatus.PASS,
                auto_fixable=False,
            )

        summary = ", ".join(f"p{m['page']} {m['uri']}" for m in missing)
        return self._issue(
            rule_id=check_code,
            severity=Severity.HIGH,
            message=(
                f"{len(missing)} URL(s)/email(s) lack a <Link> structure element: {summary}"
            ),
            recommendation=(
                "Add /Link annotation and <Link> StructElem for each URL/email in the text."
            ),
            status=ValidationStatus.FAIL,
            auto_fixable=True,
        )
