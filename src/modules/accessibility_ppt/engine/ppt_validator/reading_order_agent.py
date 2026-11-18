"""
Checks
    Object order
    Screen reader order
    Decorative objects before content
    Z-order issues
"""

from __future__ import annotations

from typing import Any
from src.modules.accessibility_pdf.models.validation_issue import ValidationIssue
from src.modules.accessibility_ppt.engine.ppt_validator.base_agent import (
    BasePPTAccessibilityValidatorAgent,
)


class ReadingOrderAgent(BasePPTAccessibilityValidatorAgent):
    """Validate slide reading order for PPT accessibility."""

    agent_code = "PPT_READING_ORDER_AGENT"
    agent_name = "PPT Reading Order Agent"
    category = "Structure"
    supported_checks = {
        "PPT-READING-001",
        "PPT-READING-002",
        "PPT-READING-003",
        "PPT-READING-004",
    }

    def run_check(self, check_code: str, context: dict[str, Any]) -> ValidationIssue:
        slides = context.get("slides") or []
        if not isinstance(slides, list):
            slides = []

        if check_code == "PPT-READING-001":
            return self._check_object_order(slides)
        if check_code == "PPT-READING-002":
            return self._check_screen_reader_order(slides)
        if check_code == "PPT-READING-003":
            return self._check_decorative_objects_before_content(slides)
        if check_code == "PPT-READING-004":
            return self._check_z_order_issues(slides)

        return ValidationIssue(
            agent_name=self.agent_name,
            rule_id=check_code,
            category=self.category,
            severity="LOW",
            page_no=None,
            message=f"Check {check_code} is not implemented yet",
            recommendation="Implement the requested reading-order check",
            auto_fixable=False,
            status="INFO",
            internal_check=True,
        )

    def _check_object_order(self, slides: list[dict[str, Any]]) -> ValidationIssue:
        if not slides:
            return self._pass_issue(
                "PPT-READING-001",
                "No slides were found to validate object order.",
                "Add slide content so object order can be reviewed.",
            )

        for idx, slide in enumerate(slides, start=1):
            shapes = self._get_shapes(slide)
            if not shapes:
                continue

            title_seen = False
            title_index = -1
            body_index = -1

            for shape_index, shape in enumerate(shapes):
                shape_type = self._shape_type(shape)
                if shape_type == "title":
                    title_seen = True
                    title_index = shape_index
                    break

            for shape_index, shape in enumerate(shapes):
                if self._shape_type(shape) in {"body", "text"}:
                    body_index = shape_index
                    break

            if title_seen and body_index != -1 and title_index > body_index:
                return ValidationIssue(
                    agent_name=self.agent_name,
                    rule_id="PPT-READING-001",
                    category=self.category,
                    severity="HIGH",
                    page_no=idx,
                    message=f"Slide {idx} has object order issues: a body object appears before the slide title.",
                    recommendation="Place slide titles before body content so the reading order follows the intended narrative.",
                    auto_fixable=False,
                    status="FAIL",
                )

        return self._pass_issue(
            "PPT-READING-001",
            "Object order follows a sensible title-to-body sequence.",
            "Keep titles before body content to preserve clear reading flow.",
        )

    def _check_screen_reader_order(self, slides: list[dict[str, Any]]) -> ValidationIssue:
        if not slides:
            return self._pass_issue(
                "PPT-READING-002",
                "No slides were found to validate screen-reader order.",
                "Add slide text so the screen-reader reading order can be examined.",
            )

        for idx, slide in enumerate(slides, start=1):
            shapes = self._get_shapes(slide)
            ordered_shapes = [shape for shape in shapes if self._shape_text(shape)]
            if not ordered_shapes:
                continue

            expected_order = sorted(
                ordered_shapes,
                key=lambda shape: self._sequence_key(shape),
            )
            if [self._shape_text(shape) for shape in ordered_shapes] != [
                self._shape_text(shape) for shape in expected_order
            ]:
                return ValidationIssue(
                    agent_name=self.agent_name,
                    rule_id="PPT-READING-002",
                    category=self.category,
                    severity="MEDIUM",
                    page_no=idx,
                    message=f"Slide {idx} does not expose a consistent screen-reader reading order.",
                    recommendation="Arrange slide shapes in a predictable order for assistive technology users.",
                    auto_fixable=False,
                    status="FAIL",
                )

        return self._pass_issue(
            "PPT-READING-002",
            "Slide content has a consistent screen-reader reading order.",
            "Preserve the same top-to-bottom reading pattern across slides.",
        )

    def _check_decorative_objects_before_content(
        self,
        slides: list[dict[str, Any]],
    ) -> ValidationIssue:
        if not slides:
            return self._pass_issue(
                "PPT-READING-003",
                "No slides were found to validate decorative content placement.",
                "Add slide content so decorative objects can be reviewed.",
            )

        for idx, slide in enumerate(slides, start=1):
            shapes = self._get_shapes(slide)
            first_content_index = -1
            decorative_before_content = False

            for shape_index, shape in enumerate(shapes):
                if self._is_decorative(shape):
                    if first_content_index == -1:
                        decorative_before_content = True
                    continue
                if self._shape_text(shape):
                    first_content_index = shape_index
                    break

            if decorative_before_content:
                return ValidationIssue(
                    agent_name=self.agent_name,
                    rule_id="PPT-READING-003",
                    category=self.category,
                    severity="MEDIUM",
                    page_no=idx,
                    message=f"Slide {idx} places decorative objects before meaningful content.",
                    recommendation="Keep decorative shapes after or away from the main content flow so they do not interrupt the reading order.",
                    auto_fixable=False,
                    status="FAIL",
                )

        return self._pass_issue(
            "PPT-READING-003",
            "Decorative objects are not inserted ahead of meaningful content.",
            "Keep decorative elements visually supportive and not first in the reading path.",
        )

    def _check_z_order_issues(self, slides: list[dict[str, Any]]) -> ValidationIssue:
        if not slides:
            return self._pass_issue(
                "PPT-READING-004",
                "No slides were found to validate z-order semantics.",
                "Add slide objects so z-order consistency can be checked.",
            )

        for idx, slide in enumerate(slides, start=1):
            shapes = self._get_shapes(slide)
            z_orders = [self._z_order(shape) for shape in shapes if self._z_order(shape) is not None]
            if len(z_orders) < 2:
                continue

            if any(current < previous for previous, current in zip(z_orders, z_orders[1:])):
                return ValidationIssue(
                    agent_name=self.agent_name,
                    rule_id="PPT-READING-004",
                    category=self.category,
                    severity="MEDIUM",
                    page_no=idx,
                    message=f"Slide {idx} has inconsistent z-order values that can break the intended reading flow.",
                    recommendation="Keep z-order values aligned with the intended visual and screen-reader order.",
                    auto_fixable=False,
                    status="FAIL",
                )

        return self._pass_issue(
            "PPT-READING-004",
            "Z-order values are consistent enough for a predictable reading order.",
            "Use a stable z-order pattern so overlapping content remains understandable.",
        )

    @staticmethod
    def _get_shapes(slide: dict[str, Any]) -> list[dict[str, Any]]:
        if not isinstance(slide, dict):
            return []
        shapes = slide.get("shapes") or []
        return shapes if isinstance(shapes, list) else []

    @staticmethod
    def _shape_type(shape: dict[str, Any]) -> str:
        if not isinstance(shape, dict):
            return ""
        shape_type = shape.get("type")
        if isinstance(shape_type, str):
            normalized = shape_type.strip().casefold()
            if normalized == "title":
                return "title"
            if normalized in {"body", "text"}:
                return "body"
        return "text" if isinstance(shape.get("text"), str) and shape.get("text", "").strip() else ""

    @staticmethod
    def _shape_text(shape: dict[str, Any]) -> str | None:
        if not isinstance(shape, dict):
            return None
        text = shape.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
        return None

    @staticmethod
    def _sequence_key(shape: dict[str, Any]) -> tuple[int, int]:
        order = shape.get("order")
        if isinstance(order, int):
            return order, int(shape.get("z_order") or 0)
        z_order = shape.get("z_order")
        if isinstance(z_order, int):
            return z_order, 0
        return 0, 0

    @staticmethod
    def _z_order(shape: dict[str, Any]) -> int | None:
        if not isinstance(shape, dict):
            return None
        z_order = shape.get("z_order")
        if isinstance(z_order, int):
            return z_order
        order = shape.get("order")
        if isinstance(order, int):
            return order
        return None

    @staticmethod
    def _is_decorative(shape: dict[str, Any]) -> bool:
        if not isinstance(shape, dict):
            return False
        return bool(shape.get("decorative"))

    @staticmethod
    def _pass_issue(rule_id: str, message: str, recommendation: str) -> ValidationIssue:
        return ValidationIssue(
            agent_name=ReadingOrderAgent.agent_name,
            rule_id=rule_id,
            category=ReadingOrderAgent.category,
            severity="LOW",
            page_no=None,
            message=message,
            recommendation=recommendation,
            auto_fixable=False,
            status="PASS",
        )