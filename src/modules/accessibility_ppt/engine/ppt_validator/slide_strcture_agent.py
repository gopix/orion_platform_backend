"""
Checks:
    Slide title exists
    Placeholder usage
    Empty slides
    Slide layout
    Reading hierarchy
"""


from __future__ import annotations

from typing import Any

from src.modules.accessibility_pdf.models.validation_issue import ValidationIssue
from src.modules.accessibility_ppt.engine.ppt_validator.base_agent import (
    BasePPTAccessibilityValidatorAgent,
)


class SlideStructureAgent(BasePPTAccessibilityValidatorAgent):
    """Validate slide-level structure and reading order for PPT accessibility."""

    agent_code = "PPT_STRUCTURE_AGENT"
    agent_name = "PPT Slide Structure Agent"
    category = "Structure"
    supported_checks = {
        "PPT-STRUCTURE-001",
        "PPT-STRUCTURE-002",
        "PPT-STRUCTURE-003",
        "PPT-STRUCTURE-004",
        "PPT-STRUCTURE-005",
    }

    PLACEHOLDER_TITLES = {
        "click to add title",
        "add a title",
        "title",
        "untitled",
    }

    def run_check(self, check_code: str, context: dict[str, Any]) -> ValidationIssue:
        slides = context.get("slides") or []
        if not isinstance(slides, list):
            slides = []

        if check_code == "PPT-STRUCTURE-001":
            return self._check_slide_title_exists(slides)
        if check_code == "PPT-STRUCTURE-002":
            return self._check_placeholder_title(slides)
        if check_code == "PPT-STRUCTURE-003":
            return self._check_empty_slides(slides)
        if check_code == "PPT-STRUCTURE-004":
            return self._check_slide_layout(slides)
        if check_code == "PPT-STRUCTURE-005":
            return self._check_reading_hierarchy(slides)

        return ValidationIssue(
            agent_name=self.agent_name,
            rule_id=check_code,
            category=self.category,
            severity="LOW",
            page_no=None,
            message=f"Check {check_code} is not implemented yet",
            recommendation="Implement the requested slide structure check",
            auto_fixable=False,
            status="INFO",
            internal_check=True,
        )

    def _check_slide_title_exists(self, slides: list[dict[str, Any]]) -> ValidationIssue:
        for idx, slide in enumerate(slides, start=1):
            title = self._extract_title(slide)
            if not title:
                return ValidationIssue(
                    agent_name=self.agent_name,
                    rule_id="PPT-STRUCTURE-001",
                    category=self.category,
                    severity="HIGH",
                    page_no=idx,
                    message=f"Slide {idx} is missing a title.",
                    recommendation="Add a clear slide title to establish the slide's topic.",
                    auto_fixable=False,
                    status="FAIL",
                )

        return ValidationIssue(
            agent_name=self.agent_name,
            rule_id="PPT-STRUCTURE-001",
            category=self.category,
            severity="LOW",
            page_no=None,
            message="All slides include a title.",
            recommendation="Keep titles concise and meaningful for screen reader users.",
            auto_fixable=False,
            status="PASS",
        )

    def _check_placeholder_title(self, slides: list[dict[str, Any]]) -> ValidationIssue:
        for idx, slide in enumerate(slides, start=1):
            title = self._extract_title(slide)
            if title and self._is_placeholder_title(title):
                return ValidationIssue(
                    agent_name=self.agent_name,
                    rule_id="PPT-STRUCTURE-002",
                    category=self.category,
                    severity="HIGH",
                    page_no=idx,
                    message=f"Slide {idx} still uses a placeholder title: '{title}'.",
                    recommendation="Replace the placeholder title with a descriptive title.",
                    auto_fixable=False,
                    status="FAIL",
                )

        return ValidationIssue(
            agent_name=self.agent_name,
            rule_id="PPT-STRUCTURE-002",
            category=self.category,
            severity="LOW",
            page_no=None,
            message="No placeholder slide titles found.",
            recommendation="Keep slide titles descriptive and unique.",
            auto_fixable=False,
            status="PASS",
        )

    def _check_empty_slides(self, slides: list[dict[str, Any]]) -> ValidationIssue:
        for idx, slide in enumerate(slides, start=1):
            if self._is_empty_slide(slide):
                return ValidationIssue(
                    agent_name=self.agent_name,
                    rule_id="PPT-STRUCTURE-003",
                    category=self.category,
                    severity="MEDIUM",
                    page_no=idx,
                    message=f"Slide {idx} is empty or contains no meaningful content.",
                    recommendation="Add content or remove the empty slide to avoid confusing navigation.",
                    auto_fixable=False,
                    status="FAIL",
                )

        return ValidationIssue(
            agent_name=self.agent_name,
            rule_id="PPT-STRUCTURE-003",
            category=self.category,
            severity="LOW",
            page_no=None,
            message="No empty slides detected.",
            recommendation="Avoid empty slides that add no semantic value.",
            auto_fixable=False,
            status="PASS",
        )

    def _check_slide_layout(self, slides: list[dict[str, Any]]) -> ValidationIssue:
        if not slides:
            return ValidationIssue(
                agent_name=self.agent_name,
                rule_id="PPT-STRUCTURE-004",
                category=self.category,
                severity="LOW",
                page_no=None,
                message="No slides were found to validate layout semantics.",
                recommendation="Add slides with a consistent layout.",
                auto_fixable=False,
                status="PASS",
            )

        for idx, slide in enumerate(slides, start=1):
            layout = slide.get("layout") if isinstance(slide, dict) else None
            if not layout:
                return ValidationIssue(
                    agent_name=self.agent_name,
                    rule_id="PPT-STRUCTURE-004",
                    category=self.category,
                    severity="LOW",
                    page_no=idx,
                    message=f"Slide {idx} does not expose a layout hint.",
                    recommendation="Assign a logical slide layout so the reading order remains predictable.",
                    auto_fixable=False,
                    status="WARNING",
                )

        return ValidationIssue(
            agent_name=self.agent_name,
            rule_id="PPT-STRUCTURE-004",
            category=self.category,
            severity="LOW",
            page_no=None,
            message="Slide layouts are available and consistent enough for structure review.",
            recommendation="Use consistent slide layouts to keep the reading flow stable.",
            auto_fixable=False,
            status="PASS",
        )

    def _check_reading_hierarchy(self, slides: list[dict[str, Any]]) -> ValidationIssue:
        if not slides:
            return ValidationIssue(
                agent_name=self.agent_name,
                rule_id="PPT-STRUCTURE-005",
                category=self.category,
                severity="LOW",
                page_no=None,
                message="No slides were found to validate reading hierarchy.",
                recommendation="Add slide titles and body content to establish a reading order.",
                auto_fixable=False,
                status="PASS",
            )

        for idx, slide in enumerate(slides, start=1):
            title = self._extract_title(slide)
            body_text = self._extract_body_text(slide)
            if not title:
                return ValidationIssue(
                    agent_name=self.agent_name,
                    rule_id="PPT-STRUCTURE-005",
                    category=self.category,
                    severity="HIGH",
                    page_no=idx,
                    message=f"Slide {idx} lacks a heading/title for the reading hierarchy.",
                    recommendation="Add a title before body content so assistive technology can interpret the slide structure.",
                    auto_fixable=False,
                    status="FAIL",
                )
            if not body_text:
                return ValidationIssue(
                    agent_name=self.agent_name,
                    rule_id="PPT-STRUCTURE-005",
                    category=self.category,
                    severity="MEDIUM",
                    page_no=idx,
                    message=f"Slide {idx} has a title but no body content to establish hierarchy.",
                    recommendation="Add logical body text or remove the slide if it is decorative.",
                    auto_fixable=False,
                    status="FAIL",
                )

        return ValidationIssue(
            agent_name=self.agent_name,
            rule_id="PPT-STRUCTURE-005",
            category=self.category,
            severity="LOW",
            page_no=None,
            message="Slides present a clear title-to-body hierarchy.",
            recommendation="Maintain a consistent heading-to-body pattern across all slides.",
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
                if not isinstance(shape, dict):
                    continue

                shape_type = shape.get("type")
                is_title = isinstance(shape_type, str) and shape_type.strip().casefold() == "title"
                if is_title:
                    text = shape.get("text")
                    if isinstance(text, str) and text.strip():
                        return text.strip()

        return None

    @staticmethod
    def _extract_body_text(slide: dict[str, Any]) -> str | None:
        if not isinstance(slide, dict):
            return None

        shapes = slide.get("shapes") or []
        if not isinstance(shapes, list):
            return None

        pieces: list[str] = []
        for shape in shapes:
            if not isinstance(shape, dict):
                continue
            text = shape.get("text")
            if isinstance(text, str) and text.strip():
                pieces.append(text.strip())

        return " ".join(pieces) or None

    def _is_placeholder_title(self, title: str) -> bool:
        normalized = title.strip().casefold()
        return normalized in self.PLACEHOLDER_TITLES

    @staticmethod
    def _is_empty_slide(slide: dict[str, Any]) -> bool:
        if not isinstance(slide, dict):
            return True

        title = slide.get("title")
        shapes = slide.get("shapes") or []
        if isinstance(title, str) and title.strip():
            return False
        if not isinstance(shapes, list):
            return True

        for shape in shapes:
            if not isinstance(shape, dict):
                continue
            text = shape.get("text")
            if isinstance(text, str) and text.strip():
                return False

        return True
