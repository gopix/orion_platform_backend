"""
metadata_agent.py
=================
MetadataAgent — validates presentation-level document properties.

Checks (supported_checks)
    PPT-META-001  Title     (core document title present & not a default)
    PPT-META-002  Subject   (subject set — best practice)
    PPT-META-003  Author    (author set — best practice)
    PPT-META-004  Keywords  (keywords/tags set — best practice)
    PPT-META-005  Language  (document language set — WCAG 3.1.1)

Reads the normalized context from ppt_loader:
    context["presentation"] = {title, author, subject, keywords, category,
                               comments, language, created, modified,
                               last_modified_by}

Title and Language are accessibility-relevant (a screen reader announces the
document title; the language drives pronunciation), so they FAIL when missing.
Subject/Author/Keywords are metadata hygiene and are reported as advisory
WARNINGs.
"""
from __future__ import annotations

from typing import Any

from src.modules.accessibility_pdf.models.validation_issue import ValidationIssue
from src.modules.accessibility_ppt.engine.ppt_validator.base_agent import (
    BasePPTAccessibilityValidatorAgent,
)

_DEFAULT_TITLES = {
    "powerpoint presentation", "presentation", "untitled",
    "untitled presentation", "slide 1", "deck",
}


class MetadataAgent(BasePPTAccessibilityValidatorAgent):
    """Validate presentation document properties."""

    agent_code = "PPT_METADATA_AGENT"
    agent_name = "PPT Metadata Agent"
    category = "Metadata"
    supported_checks = {
        "PPT-META-001",
        "PPT-META-002",
        "PPT-META-003",
        "PPT-META-004",
        "PPT-META-005",
    }

    # ---------------------------------------------------------------- dispatch
    def run_check(self, check_code: str, context: dict[str, Any]) -> ValidationIssue:
        meta = context.get("presentation")
        meta = meta if isinstance(meta, dict) else {}

        if check_code == "PPT-META-001":
            return self._check_title(meta)
        if check_code == "PPT-META-002":
            return self._check_simple(meta, "subject", "PPT-META-002", "Subject")
        if check_code == "PPT-META-003":
            return self._check_simple(meta, "author", "PPT-META-003", "Author")
        if check_code == "PPT-META-004":
            return self._check_simple(meta, "keywords", "PPT-META-004", "Keywords")
        if check_code == "PPT-META-005":
            return self._check_language(meta)
        return self._info(check_code, f"Check {check_code} is not implemented yet",
                          "Implement the requested metadata check")

    # ---------------------------------------------------------------- helpers
    def _issue(self, rule_id, severity, status, message, recommendation,
               auto_fixable=False, internal=False) -> ValidationIssue:
        return ValidationIssue(
            agent_name=self.agent_name, rule_id=rule_id, category=self.category,
            severity=severity, page_no=None, message=message,
            recommendation=recommendation, auto_fixable=auto_fixable,
            status=status, internal_check=internal,
        )

    def _pass(self, rule_id, message, recommendation) -> ValidationIssue:
        return self._issue(rule_id, "LOW", "PASS", message, recommendation)

    def _info(self, rule_id, message, recommendation) -> ValidationIssue:
        return self._issue(rule_id, "LOW", "INFO", message, recommendation,
                           internal=True)

    @staticmethod
    def _val(meta: dict, key: str) -> str:
        v = meta.get(key)
        return v.strip() if isinstance(v, str) else ""

    # ---------------------------------------------------------------- 001 title
    def _check_title(self, meta) -> ValidationIssue:
        title = self._val(meta, "title")
        if not title:
            return self._issue(
                "PPT-META-001", "HIGH", "FAIL",
                "The presentation has no document title.",
                "Set a descriptive title in File > Info / document properties so "
                "assistive tech can announce the presentation.",
                auto_fixable=True)
        if title.casefold() in _DEFAULT_TITLES:
            return self._issue(
                "PPT-META-001", "MEDIUM", "FAIL",
                f"The document title is a generic default: '{title}'.",
                "Replace the default title with a specific, descriptive one.",
                auto_fixable=False)
        return self._pass("PPT-META-001", f"Document title is set: '{title}'.",
                          "Keep the title descriptive and specific.")

    # ------------------------------------------------- 002/003/004 best-practice
    def _check_simple(self, meta, key, rule_id, label) -> ValidationIssue:
        val = self._val(meta, key)
        if val:
            return self._pass(rule_id, f"{label} is set: '{val[:60]}'.",
                              f"Keep {label.lower()} accurate.")
        return self._issue(
            rule_id, "LOW", "WARNING",
            f"{label} is not set in the document properties.",
            f"Add a {label.lower()} in the presentation's document properties for "
            "completeness and discoverability.",
            auto_fixable=False)

    # ---------------------------------------------------------------- 005 lang
    def _check_language(self, meta) -> ValidationIssue:
        lang = self._val(meta, "language")
        if lang:
            return self._pass("PPT-META-005", f"Document language is set: '{lang}'.",
                              "Keep the language set so pronunciation is correct.")
        return self._issue(
            "PPT-META-005", "MEDIUM", "FAIL",
            "No document language is set (WCAG 3.1.1).",
            "Set the presentation language (Review > Language > Set Proofing "
            "Language, applied to the whole deck) so screen readers pronounce "
            "content correctly. Note: per-run language overrides may still exist.",
            auto_fixable=False)
