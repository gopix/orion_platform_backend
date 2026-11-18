from __future__ import annotations

from typing import Any

from src.modules.accessibility_pdf.models.validation_issue import ValidationIssue
from src.modules.accessibility_ppt.engine.ppt_validator.base_agent import (
    BasePPTAccessibilityValidatorAgent,
)


class HeadingAgent(BasePPTAccessibilityValidatorAgent):
    """Validate slide heading structure for PPT accessibility."""

    agent_code = "PPT_HEADING_AGENT"
    agent_name = "PPT Heading Agent"
    category = "Structure"
    supported_checks = {
        "PPT-HEADING-001",
        "PPT-HEADING-002",
        "PPT-HEADING-003",
        "PPT-HEADING-004",
    }

    PLACEHOLDER_TITLES = {
        "click to add title",
        "title",
        "untitled",
        "add a title",
    }

    def run_check(self, check_code: str, context: dict[str, Any]) -> ValidationIssue:
        slides = context.get("slides") or []
        if not isinstance(slides, list):
            slides = []

        if check_code == "PPT-HEADING-002":
            return self._check_placeholder_title(slides)
        if check_code == "PPT-HEADING-003":
            return self._check_duplicate_titles(slides)
        if check_code == "PPT-HEADING-004":
            return self._check_heading_hierarchy(slides)

        return ValidationIssue(
            agent_name=self.agent_name,
            rule_id=check_code,
            category=self.category,
            severity="LOW",
            page_no=None,
            message=f"Check {check_code} is not implemented yet",
            recommendation="Implement the requested heading check",
            auto_fixable=False,
            status="INFO",
            internal_check=True,
        )

    def _check_placeholder_title(self, slides: list[dict[str, Any]]) -> ValidationIssue:
        for idx, slide in enumerate(slides):
            title = self._extract_title(slide)
            if title and self._is_placeholder_title(title):
                return ValidationIssue(
                    agent_name=self.agent_name,
                    rule_id="PPT-HEADING-002",
                    category=self.category,
                    severity="HIGH",
                    page_no=idx + 1,
                    message=f"Slide {idx + 1} still uses a placeholder title: '{title}'",
                    recommendation="Replace the placeholder title with a meaningful slide title.",
                    auto_fixable=False,
                    status="FAIL",
                )

        return ValidationIssue(
            agent_name=self.agent_name,
            rule_id="PPT-HEADING-002",
            category=self.category,
            severity="LOW",
            page_no=None,
            message="No placeholder slide titles found.",
            recommendation="Keep slide titles descriptive and unique.",
            auto_fixable=False,
            status="PASS",
        )

    def _check_duplicate_titles(self, slides: list[dict[str, Any]]) -> ValidationIssue:
        seen: dict[str, int] = {}
        duplicates: list[str] = []
        for idx, slide in enumerate(slides):
            title = self._extract_title(slide)
            if not title:
                continue
            normalized = title.strip().casefold()
            if normalized in seen:
                duplicates.append(title)
            else:
                seen[normalized] = idx + 1

        if duplicates:
            return ValidationIssue(
                agent_name=self.agent_name,
                rule_id="PPT-HEADING-003",
                category=self.category,
                severity="MEDIUM",
                page_no=None,
                message=f"Duplicate slide titles detected: {', '.join(sorted(set(duplicates)))}",
                recommendation="Make each slide title unique and descriptive.",
                auto_fixable=False,
                status="FAIL",
            )

        return ValidationIssue(
            agent_name=self.agent_name,
            rule_id="PPT-HEADING-003",
            category=self.category,
            severity="LOW",
            page_no=None,
            message="All slide titles are unique.",
            recommendation="Keep slide titles unique across the presentation.",
            auto_fixable=False,
            status="PASS",
        )

    def _check_heading_hierarchy(self, slides: list[dict[str, Any]]) -> ValidationIssue:
        if not slides:
            return ValidationIssue(
                agent_name=self.agent_name,
                rule_id="PPT-HEADING-004",
                category=self.category,
                severity="LOW",
                page_no=None,
                message="No slides available to validate heading hierarchy.",
                recommendation="Add slide titles to establish a hierarchy.",
                auto_fixable=False,
                status="PASS",
            )

        first_title = self._extract_title(slides[0]) or ""
        if not first_title:
            return ValidationIssue(
                agent_name=self.agent_name,
                rule_id="PPT-HEADING-004",
                category=self.category,
                severity="MEDIUM",
                page_no=1,
                message="The first slide does not contain a title.",
                recommendation="Add a clear title to the first slide.",
                auto_fixable=False,
                status="FAIL",
            )

        return ValidationIssue(
            agent_name=self.agent_name,
            rule_id="PPT-HEADING-004",
            category=self.category,
            severity="LOW",
            page_no=None,
            message="Slide title hierarchy looks structurally consistent.",
            recommendation="Keep titles concise and consistent with the slide content.",
            auto_fixable=False,
            status="PASS",
        )

    @staticmethod
    def _extract_title(slide: dict[str, Any]) -> str | None:
        if not isinstance(slide, dict):
            return None

        title = slide.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()

        shapes = slide.get("shapes") or []
        if isinstance(shapes, list):
            for shape in shapes:
                if isinstance(shape, dict):
                    text = shape.get("text")
                    if isinstance(text, str) and text.strip():
                        return text.strip()

        return None

    def _is_placeholder_title(self, title: str) -> bool:
        normalized = title.strip().casefold()
        return normalized in self.PLACEHOLDER_TITLES