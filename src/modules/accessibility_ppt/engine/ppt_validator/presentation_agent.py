from __future__ import annotations

from typing import Any

from src.modules.accessibility_pdf.models.validation_issue import ValidationIssue
from src.modules.accessibility_ppt.engine.ppt_validator.base_agent import (
    BasePPTAccessibilityValidatorAgent,
)


class PresentationAgent(BasePPTAccessibilityValidatorAgent):
    """Validate presentation-level accessibility metadata and structure."""

    agent_code = "PPT_PRESENTATION_AGENT"
    agent_name = "PPT Presentation Agent"
    category = "Presentation"
    supported_checks = {
        "PPT-PRESENTATION-001",
        "PPT-PRESENTATION-002",
        "PPT-PRESENTATION-003",
        "PPT-PRESENTATION-004",
        "PPT-PRESENTATION-005",
        "PPT-PRESENTATION-006",
        "PPT-PRESENTATION-007",
    }

    def run_check(self, check_code: str, context: dict[str, Any]) -> ValidationIssue:
        presentation = context.get("presentation") or {}
        slides = context.get("slides") or []
        if not isinstance(slides, list):
            slides = []

        if check_code == "PPT-PRESENTATION-001":
            return self._check_presentation_title(presentation)
        if check_code == "PPT-PRESENTATION-002":
            return self._check_author(presentation)
        if check_code == "PPT-PRESENTATION-003":
            return self._check_language(presentation)
        if check_code == "PPT-PRESENTATION-004":
            return self._check_theme(presentation)
        if check_code == "PPT-PRESENTATION-005":
            return self._check_default_fonts(presentation)
        if check_code == "PPT-PRESENTATION-006":
            return self._check_slide_count(slides)
        if check_code == "PPT-PRESENTATION-007":
            return self._check_hidden_slides(slides)

        return ValidationIssue(
            agent_name=self.agent_name,
            rule_id=check_code,
            category=self.category,
            severity="LOW",
            page_no=None,
            message=f"Check {check_code} is not implemented yet",
            recommendation="Implement the requested presentation check",
            auto_fixable=False,
            status="INFO",
            internal_check=True,
        )

    def _check_presentation_title(self, presentation: dict[str, Any]) -> ValidationIssue:
        title = self._get_value(presentation, "title")
        if not title:
            return ValidationIssue(
                agent_name=self.agent_name,
                rule_id="PPT-PRESENTATION-001",
                category=self.category,
                severity="MEDIUM",
                page_no=None,
                message="Presentation title is missing.",
                recommendation="Add a meaningful title to the presentation metadata.",
                auto_fixable=False,
                status="FAIL",
            )
        return ValidationIssue(
            agent_name=self.agent_name,
            rule_id="PPT-PRESENTATION-001",
            category=self.category,
            severity="LOW",
            page_no=None,
            message="Presentation title is present.",
            recommendation="Keep the presentation title descriptive.",
            auto_fixable=False,
            status="PASS",
        )

    def _check_author(self, presentation: dict[str, Any]) -> ValidationIssue:
        author = self._get_value(presentation, "author")
        if not author:
            return ValidationIssue(
                agent_name=self.agent_name,
                rule_id="PPT-PRESENTATION-002",
                category=self.category,
                severity="LOW",
                page_no=None,
                message="Author metadata is missing.",
                recommendation="Add author information to the presentation properties.",
                auto_fixable=False,
                status="WARNING",
            )
        return ValidationIssue(
            agent_name=self.agent_name,
            rule_id="PPT-PRESENTATION-002",
            category=self.category,
            severity="LOW",
            page_no=None,
            message="Author metadata is present.",
            recommendation="Keep author metadata up to date.",
            auto_fixable=False,
            status="PASS",
        )

    def _check_language(self, presentation: dict[str, Any]) -> ValidationIssue:
        language = self._get_value(presentation, "language")
        if not language:
            return ValidationIssue(
                agent_name=self.agent_name,
                rule_id="PPT-PRESENTATION-003",
                category=self.category,
                severity="MEDIUM",
                page_no=None,
                message="Presentation language is not defined.",
                recommendation="Set the presentation language for assistive technology support.",
                auto_fixable=False,
                status="FAIL",
            )
        return ValidationIssue(
            agent_name=self.agent_name,
            rule_id="PPT-PRESENTATION-003",
            category=self.category,
            severity="LOW",
            page_no=None,
            message="Presentation language is defined.",
            recommendation="Use the correct language for the audience.",
            auto_fixable=False,
            status="PASS",
        )

    def _check_theme(self, presentation: dict[str, Any]) -> ValidationIssue:
        theme = self._get_value(presentation, "theme")
        if not theme:
            return ValidationIssue(
                agent_name=self.agent_name,
                rule_id="PPT-PRESENTATION-004",
                category=self.category,
                severity="LOW",
                page_no=None,
                message="No theme information was provided.",
                recommendation="Specify a theme to improve visual consistency.",
                auto_fixable=False,
                status="WARNING",
            )
        return ValidationIssue(
            agent_name=self.agent_name,
            rule_id="PPT-PRESENTATION-004",
            category=self.category,
            severity="LOW",
            page_no=None,
            message="Theme information is available.",
            recommendation="Use a theme with sufficient contrast.",
            auto_fixable=False,
            status="PASS",
        )

    def _check_default_fonts(self, presentation: dict[str, Any]) -> ValidationIssue:
        fonts = self._get_value(presentation, "default_fonts")
        if not fonts:
            return ValidationIssue(
                agent_name=self.agent_name,
                rule_id="PPT-PRESENTATION-005",
                category=self.category,
                severity="MEDIUM",
                page_no=None,
                message="No default font information was provided.",
                recommendation="Define a readable default font for the presentation.",
                auto_fixable=False,
                status="FAIL",
            )
        return ValidationIssue(
            agent_name=self.agent_name,
            rule_id="PPT-PRESENTATION-005",
            category=self.category,
            severity="LOW",
            page_no=None,
            message="Default font information is available.",
            recommendation="Prefer accessible fonts such as Arial or Calibri.",
            auto_fixable=False,
            status="PASS",
        )

    def _check_slide_count(self, slides: list[dict[str, Any]]) -> ValidationIssue:
        if not slides:
            return ValidationIssue(
                agent_name=self.agent_name,
                rule_id="PPT-PRESENTATION-006",
                category=self.category,
                severity="LOW",
                page_no=None,
                message="No slides were found.",
                recommendation="Add slides to the presentation.",
                auto_fixable=False,
                status="WARNING",
            )
        return ValidationIssue(
            agent_name=self.agent_name,
            rule_id="PPT-PRESENTATION-006",
            category=self.category,
            severity="LOW",
            page_no=None,
            message=f"Presentation contains {len(slides)} slide(s).",
            recommendation="Ensure each slide is accessible and meaningful.",
            auto_fixable=False,
            status="PASS",
        )

    def _check_hidden_slides(self, slides: list[dict[str, Any]]) -> ValidationIssue:
        hidden_count = sum(1 for slide in slides if bool(slide.get("hidden")))
        if hidden_count:
            return ValidationIssue(
                agent_name=self.agent_name,
                rule_id="PPT-PRESENTATION-007",
                category=self.category,
                severity="LOW",
                page_no=None,
                message=f"{hidden_count} hidden slide(s) detected.",
                recommendation="Review hidden slides to ensure they are not excluded from the intended narrative.",
                auto_fixable=False,
                status="WARNING",
            )
        return ValidationIssue(
            agent_name=self.agent_name,
            rule_id="PPT-PRESENTATION-007",
            category=self.category,
            severity="LOW",
            page_no=None,
            message="No hidden slides detected.",
            recommendation="Keep slide visibility intentional.",
            auto_fixable=False,
            status="PASS",
        )

    @staticmethod
    def _get_value(source: dict[str, Any], key: str) -> Any:
        if not isinstance(source, dict):
            return None
        return source.get(key)
