"""
ColorAccessibilityAgent - Validates text color contrast (WCAG 1.4.3) using pdfplumber.

Checks include:
- COLOR-001: Normal-size text with contrast ratio below 4.5:1 (WCAG AA)
- COLOR-002: Large text (>= 18 pt, or >= 14 pt bold) with contrast ratio below 3:1

Analysis strategy:
    A single pdfplumber pass per document (cached in context["_cache"]) collects
    every distinct text colour together with its font size / weight, and the
    light background colours present on each page (rect fills + white).
    The WORST-CASE contrast ratio (text colour vs the lightest qualifying
    background on the same page) is compared against the WCAG AA thresholds.

    The luminance / contrast maths is imported from contrast_fixer.py so the
    validator and the remediation post-processing step can never disagree on
    the formula.
"""

from __future__ import annotations

from typing import Any

from src.modules.accessibility_pdf.models.validation_issue import (
    Severity,
    ValidationIssue,
    ValidationStatus,
)
from ..contrast_fixer import _contrast, _luminance
from .accessibility_agent_framework import BaseAccessibilityValidatorAgent

NORMAL_TEXT_TARGET = 4.5   # WCAG 1.4.3 AA - normal text
LARGE_TEXT_TARGET = 3.0    # WCAG 1.4.3 AA - large text
LARGE_TEXT_PT = 18.0       # >= 18 pt is "large"
LARGE_BOLD_PT = 14.0       # >= 14 pt bold is "large"
LIGHT_BG_LUMINANCE = 0.60  # rect fills lighter than this count as backgrounds


class ColorAccessibilityAgent(BaseAccessibilityValidatorAgent):
    """Validates colour-contrast accessibility for PDF text content."""

    agent_code = "COLOR_ACCESSIBILITY_AGENT"
    agent_name = "Color Accessibility Agent"
    category = "Color Accessibility"

    supported_checks = {
        "COLOR-001",
        "COLOR-002",
    }

    @staticmethod
    def _issue(
        rule_id: str,
        severity: Severity,
        message: str,
        recommendation: str,
        status: ValidationStatus,
        auto_fixable: bool | None = None,
        page_no: int | None = None,
    ) -> ValidationIssue:
        return ValidationIssue(
            agent_name=ColorAccessibilityAgent.agent_name,
            rule_id=rule_id,
            category="Color Accessibility",
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
                recommendation="Use a valid check code from supported_checks",
                status=ValidationStatus.FAIL,
            )

        pdf_path = context.get("pdf_doc_path")
        if not pdf_path:
            return self._issue(
                rule_id=check_code,
                severity=Severity.CRITICAL,
                message="PDF document path not provided in context",
                recommendation="Ensure pdf_doc_path is set in the pipeline context",
                status=ValidationStatus.FAIL,
            )

        cache = context.setdefault("_cache", {})
        color_cache = cache.setdefault("color_accessibility", {})
        if pdf_path not in color_cache:
            color_cache[pdf_path] = self._build_color_analysis(pdf_path)

        analysis = color_cache[pdf_path]

        check_handlers = {
            "COLOR-001": self._check_normal_text_contrast,
            "COLOR-002": self._check_large_text_contrast,
        }

        try:
            handler = check_handlers[check_code]
            return handler(check_code, analysis)
        except Exception as exc:
            return self._issue(
                rule_id=check_code,
                severity=Severity.HIGH,
                message=f"Check execution error: {str(exc)}",
                recommendation="Review the error and retry the check",
                status=ValidationStatus.FAIL,
            )

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    @staticmethod
    def _to_rgb(color: Any) -> tuple[float, float, float] | None:
        """Normalise a pdfplumber non_stroking_color to an (r, g, b) tuple in 0-1."""
        if color is None:
            return None
        try:
            if isinstance(color, (int, float)):
                v = float(color)
                return (v, v, v)
            values = [float(v) for v in color]
        except (TypeError, ValueError):
            return None
        if len(values) == 1:          # DeviceGray
            v = values[0]
            return (v, v, v)
        if len(values) == 3:          # DeviceRGB
            return tuple(values)
        if len(values) == 4:          # DeviceCMYK -> naive RGB conversion
            c, m, y, k = values
            return ((1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))
        return None

    @staticmethod
    def _build_color_analysis(pdf_path: str) -> dict[str, Any]:
        """Single pdfplumber pass: contrast of every distinct text colour."""
        import pdfplumber

        analysis: dict[str, Any] = {
            "normal_violations": 0,
            "large_violations": 0,
            "normal_pages": set(),
            "large_pages": set(),
            "worst_normal_ratio": None,
            "worst_large_ratio": None,
            # Light text colours (luminance > 0.50) confirmed as TEXT by
            # pdfplumber and safe to darken (not also used as rect fills).
            # Passed to contrast_fixer as its whitelist.
            "light_text_colors": [],
            # Light text colours that are ALSO used as rect fills — cannot be
            # darkened safely via content-stream patching; manual review.
            "manual_review_colors": 0,
            "analyzed": False,
            "error": None,
        }

        light_text_colors: set[tuple[float, float, float]] = set()
        rect_fill_colors: set[tuple[float, float, float]] = set()

        try:
            with pdfplumber.open(pdf_path) as pdf:
                # Pass 1 - all rect fill colours doc-wide (a colour used for a
                # rect fill anywhere must never be darkened as "text").
                for page in pdf.pages:
                    for rect in page.rects:
                        rgb = ColorAccessibilityAgent._to_rgb(rect.get("non_stroking_color"))
                        if rgb:
                            rect_fill_colors.add(tuple(round(v, 3) for v in rgb))

                for page_index, page in enumerate(pdf.pages):
                    page_no = page_index + 1

                    # Light background candidates on this page (white + light rect fills)
                    backgrounds: list[tuple[float, float, float]] = [(1.0, 1.0, 1.0)]
                    for rect in page.rects:
                        rgb = ColorAccessibilityAgent._to_rgb(rect.get("non_stroking_color"))
                        if rgb and _luminance(*rgb) > LIGHT_BG_LUMINANCE:
                            backgrounds.append(rgb)

                    # Distinct (colour, size-class) combinations on this page
                    seen: set[tuple] = set()
                    for char in page.chars:
                        rgb = ColorAccessibilityAgent._to_rgb(char.get("non_stroking_color"))
                        if rgb is None:
                            continue
                        size = float(char.get("size") or 0)
                        fontname = str(char.get("fontname") or "")
                        is_bold = "bold" in fontname.lower()
                        is_large = size >= LARGE_TEXT_PT or (is_bold and size >= LARGE_BOLD_PT)

                        key = (round(rgb[0], 3), round(rgb[1], 3), round(rgb[2], 3), is_large)
                        if key in seen:
                            continue
                        seen.add(key)

                        rounded = (round(rgb[0], 3), round(rgb[1], 3), round(rgb[2], 3))
                        eff_bgs = [bg for bg in backgrounds
                                   if abs(bg[0] - rgb[0]) + abs(bg[1] - rgb[1]) + abs(bg[2] - rgb[2]) > 1e-6] \
                                  or [(1.0, 1.0, 1.0)]
                        worst_ratio = min(_contrast(rgb, bg) for bg in eff_bgs)

                        threshold = LARGE_TEXT_TARGET if is_large else NORMAL_TEXT_TARGET
                        if worst_ratio < threshold and _luminance(*rgb) > 0.50:
                            if rounded in rect_fill_colors:
                                analysis["manual_review_colors"] += 1
                            else:
                                light_text_colors.add(rounded)

                        if is_large:
                            if worst_ratio < LARGE_TEXT_TARGET:
                                analysis["large_violations"] += 1
                                analysis["large_pages"].add(page_no)
                                if (analysis["worst_large_ratio"] is None
                                        or worst_ratio < analysis["worst_large_ratio"]):
                                    analysis["worst_large_ratio"] = worst_ratio
                        else:
                            if worst_ratio < NORMAL_TEXT_TARGET:
                                analysis["normal_violations"] += 1
                                analysis["normal_pages"].add(page_no)
                                if (analysis["worst_normal_ratio"] is None
                                        or worst_ratio < analysis["worst_normal_ratio"]):
                                    analysis["worst_normal_ratio"] = worst_ratio

            analysis["light_text_colors"] = sorted(light_text_colors)
            analysis["analyzed"] = True
        except Exception as exc:  # pragma: no cover - defensive
            analysis["error"] = str(exc)

        return analysis

    # ------------------------------------------------------------------
    # Checks
    # ------------------------------------------------------------------

    def _check_normal_text_contrast(
        self, check_code: str, analysis: dict[str, Any]
    ) -> ValidationIssue:
        if analysis.get("error"):
            return self._issue(
                rule_id=check_code,
                severity=Severity.HIGH,
                message=f"Contrast analysis failed: {analysis['error']}",
                recommendation="Verify the PDF is readable and retry the check",
                status=ValidationStatus.WARNING,
            )

        violations = analysis.get("normal_violations", 0)
        if not violations:
            return self._issue(
                rule_id=check_code,
                severity=Severity.HIGH,
                message="All normal-size text meets the 4.5:1 contrast ratio (WCAG 1.4.3 AA)",
                recommendation="Text contrast is adequate",
                status=ValidationStatus.PASS,
            )

        pages = sorted(analysis.get("normal_pages", set()))
        worst = analysis.get("worst_normal_ratio")
        worst_txt = f"; worst ratio {worst:.2f}:1" if worst else ""
        return self._issue(
            rule_id=check_code,
            severity=Severity.HIGH,
            message=(
                f"{violations} normal-size text colour(s) fall below the 4.5:1 "
                f"contrast ratio on page(s) {pages}{worst_txt}"
            ),
            recommendation=(
                "Darken low-contrast text colours to reach at least 4.5:1 against "
                "the background (WCAG 1.4.3 AA)"
            ),
            status=ValidationStatus.FAIL,
            auto_fixable=True,
            page_no=pages[0] if pages else None,
        )

    def _check_large_text_contrast(
        self, check_code: str, analysis: dict[str, Any]
    ) -> ValidationIssue:
        if analysis.get("error"):
            return self._issue(
                rule_id=check_code,
                severity=Severity.MEDIUM,
                message=f"Contrast analysis failed: {analysis['error']}",
                recommendation="Verify the PDF is readable and retry the check",
                status=ValidationStatus.WARNING,
            )

        violations = analysis.get("large_violations", 0)
        if not violations:
            return self._issue(
                rule_id=check_code,
                severity=Severity.MEDIUM,
                message="All large text meets the 3:1 contrast ratio (WCAG 1.4.3 AA)",
                recommendation="Large-text contrast is adequate",
                status=ValidationStatus.PASS,
            )

        pages = sorted(analysis.get("large_pages", set()))
        worst = analysis.get("worst_large_ratio")
        worst_txt = f"; worst ratio {worst:.2f}:1" if worst else ""
        return self._issue(
            rule_id=check_code,
            severity=Severity.MEDIUM,
            message=(
                f"{violations} large-text colour(s) fall below the 3:1 contrast "
                f"ratio on page(s) {pages}{worst_txt}"
            ),
            recommendation=(
                "Darken low-contrast large text (>= 18 pt, or >= 14 pt bold) to "
                "reach at least 3:1 against the background (WCAG 1.4.3 AA)"
            ),
            status=ValidationStatus.FAIL,
            auto_fixable=True,
            page_no=pages[0] if pages else None,
        )
