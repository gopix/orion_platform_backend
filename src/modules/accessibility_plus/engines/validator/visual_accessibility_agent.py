"""
VisualAccessibilityAgent - Validates visual PDF accessibility traits using PDFix.

Checks include:
- VIS-001: Tiny text that may be difficult to read
- VIS-002: Watermark or watermark-like annotations that can interfere with readability
- VIS-003: Pages that look scanned/image-heavy with little extractable text
- VIS-004: Image-only page candidates with no selectable text
- VIS-005: Text density analysis for heavy text blocks and tight margins
- VIS-006: Font consistency issues when many fonts appear on a page
- VIS-007: Page rotation issues detected by PDF page rotation metadata
- VIS-008: Informational colored text usage for visual styling
- VIS-009: Light-colored text and image overlay styling
"""

from __future__ import annotations

import math
from typing import Any

from src.modules.accessibility_plus.models.validation_issue import (
    Severity,
    ValidationIssue,
    ValidationStatus,
)
from .accessibility_agent_framework import BaseAccessibilityValidatorAgent


class VisualAccessibilityAgent(BaseAccessibilityValidatorAgent):
    """Validates visual accessibility properties for PDF pages."""

    agent_code = "VISUAL_ACCESSIBILITY_AGENT"
    agent_name = "Visual Accessibility Agent"
    category = "Visual Accessibility"

    supported_checks = {
        "VIS-001",
        "VIS-002",
        "VIS-003",
        "VIS-004",
        "VIS-005",
        "VIS-006",
        "VIS-007",
        "VIS-008",
        "VIS-009",
    }

    @staticmethod
    def _issue(
        rule_id: str,
        severity: Severity,
        message: str,
        recommendation: str,
        status: ValidationStatus,
        auto_fixable: bool = False,
    ) -> ValidationIssue:
        return ValidationIssue(
            agent_name=VisualAccessibilityAgent.agent_name,
            rule_id=rule_id,
            category="Visual Accessibility",
            severity=severity.value,
            page_no=None,
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

        pdf_doc = context.get("pdf_doc")
        if not pdf_doc:
            return self._issue(
                rule_id=check_code,
                severity=Severity.CRITICAL,
                message="PDF document not provided in context",
                recommendation="Ensure PDF document is opened and provided in context",
                status=ValidationStatus.FAIL,
            )

        cache = context.setdefault("_cache", {})
        visual_cache = cache.setdefault("visual_accessibility", {})
        pdf_key = context.get("pdf_doc_path") or str(id(pdf_doc))
        if pdf_key not in visual_cache:
            visual_cache[pdf_key] = VisualAccessibilityAgent._build_visual_analysis(pdf_doc)

        analysis = visual_cache[pdf_key]

        check_handlers = {
            "VIS-001": self._check_tiny_text,
            "VIS-002": self._check_watermarks,
            "VIS-003": self._check_scanned_pages,
            "VIS-004": self._check_image_only_page,
            "VIS-005": self._check_text_density,
            "VIS-006": self._check_font_consistency,
            "VIS-007": self._check_page_rotation,
            "VIS-008": self._check_colored_text_usage,
            "VIS-009": self._check_light_colored_text,
        }

        try:
            handler = check_handlers.get(check_code)
            if not handler:
                return self._issue(
                    rule_id=check_code,
                    severity=Severity.MEDIUM,
                    message=f"Unknown check code: {check_code}",
                    recommendation="Verify check code is in supported_checks",
                    status=ValidationStatus.FAIL,
                )

            return handler(check_code, analysis)
        except Exception as exc:
            return self._issue(
                rule_id=check_code,
                severity=Severity.HIGH,
                message=f"Check execution error: {str(exc)}",
                recommendation="Review the error and retry the check",
                status=ValidationStatus.FAIL,
            )

    @staticmethod
    def _build_visual_analysis(pdf_doc) -> dict[str, int]:
        from pdfixsdk.Pdfix import kAnnotWatermark, kPdeWord, kPdeImage

        analysis = {
            "tiny_text_count": 0,
            "watermark_count": 0,
            "scanned_page_candidate_count": 0,
            "image_only_candidate_count": 0,
            "text_density_candidate_count": 0,
            "font_variant_count": 0,
            "rotated_page_count": 0,
            "color_only_text_count": 0,
            "image_background_text_count": 0,
            "light_colored_text_count": 0,
        }

        page_count = pdf_doc.GetNumPages()
        for page_index in range(page_count):
            page = pdf_doc.AcquirePage(page_index)
            if not page:
                continue

            try:
                analysis["watermark_count"] += VisualAccessibilityAgent._count_watermarks(
                    page, kAnnotWatermark
                )
                page_analysis = VisualAccessibilityAgent._analyze_page_content(
                    page, kPdeWord, kPdeImage
                )
                analysis["tiny_text_count"] += page_analysis["tiny_text_count"]
                analysis["color_only_text_count"] += page_analysis["color_only_text_count"]
                analysis["image_background_text_count"] += page_analysis["image_background_text_count"]
                analysis["light_colored_text_count"] += page_analysis["light_colored_text_count"]
                if page_analysis["image_count"] > 0 and page_analysis["word_count"] == 0:
                    analysis["image_only_candidate_count"] += 1
                if page_analysis.get("text_density_candidate"):
                    analysis["text_density_candidate_count"] += 1
                if len(page_analysis.get("font_names", set())) > 6:
                    analysis["font_variant_count"] += 1
                if page_analysis.get("page_rotation", 0) != 0:
                    analysis["rotated_page_count"] += 1
                if page_analysis["image_count"] > 0 and page_analysis["word_count"] < 20:
                    analysis["scanned_page_candidate_count"] += 1
            finally:
                try:
                    page.Release()
                except Exception:
                    pass

        return analysis

    @staticmethod
    def _count_watermarks(page, watermark_constant: int) -> int:
        watermark_count = 0
        try:
            num_annots = page.GetNumAnnots()
            for index in range(num_annots):
                try:
                    annot = page.GetAnnot(index)
                    if annot and getattr(annot, "GetSubtype", None):
                        if annot.GetSubtype() == watermark_constant:
                            watermark_count += 1
                except Exception:
                    continue
        except Exception:
            pass
        return watermark_count

    @staticmethod
    def _analyze_page_content(page, word_constant: int, image_constant: int) -> dict[str, int]:
        page_analysis = {
            "tiny_text_count": 0,
            "color_only_text_count": 0,
            "image_background_text_count": 0,
            "light_colored_text_count": 0,
            "word_count": 0,
            "image_count": 0,
            "wide_text_count": 0,
            "font_names": set(),
            "page_width": 0,
            "page_height": 0,
            "page_rotation": 0,
            "text_density_candidate": 0,
        }
        try:
            page_analysis["page_rotation"] = page.GetRotate() if getattr(page, "GetRotate", None) else 0
            page_map = page.AcquirePageMap()
            if page_map:
                try:
                    page_bbox = page_map.GetBBox() if getattr(page_map, "GetBBox", None) else None
                    if page_bbox is not None:
                        page_analysis["page_width"] = abs(getattr(page_bbox, "right", 0) - getattr(page_bbox, "left", 0))
                        page_analysis["page_height"] = abs(getattr(page_bbox, "top", 0) - getattr(page_bbox, "bottom", 0))

                    if not page_map.HasElements():
                        page_map.CreateElements()

                    root = page_map.GetElement()
                    if root:
                        VisualAccessibilityAgent._traverse_visual_elements(
                            root,
                            page_analysis,
                            word_constant,
                            image_constant,
                        )
                finally:
                    try:
                        page_map.Release()
                    except Exception:
                        pass
        except Exception:
            pass

        if page_analysis["word_count"] > 500 or page_analysis["wide_text_count"] > 40:
            page_analysis["text_density_candidate"] = 1

        return page_analysis

    @staticmethod
    def _traverse_visual_elements(element, analysis, word_constant: int, image_constant: int) -> None:
        try:
            if element.GetType() == word_constant:
                analysis["word_count"] += 1
                VisualAccessibilityAgent._inspect_word_element(
                    element,
                    analysis,
                    image_constant,
                )

            num_children = element.GetNumChildren() if getattr(element, "GetNumChildren", None) else 0
            for child_index in range(num_children):
                child = element.GetChild(child_index) if getattr(element, "GetChild", None) else None
                if child:
                    VisualAccessibilityAgent._traverse_visual_elements(
                        child,
                        analysis,
                        word_constant,
                        image_constant,
                    )
        except Exception:
            pass

    @staticmethod
    def _inspect_word_element(word_element, analysis, image_constant: int) -> None:
        try:
            if getattr(word_element, "HasTextState", None) and word_element.HasTextState():
                text_state = word_element.GetTextState()
                font_size = getattr(text_state, "font_size", 0)
                if font_size and font_size < 8:
                    analysis["tiny_text_count"] += 1

                if getattr(text_state, "font", None) is not None and getattr(text_state.font, "GetFontName", None):
                    try:
                        font_name = text_state.font.GetFontName()
                        if font_name:
                            analysis["font_names"].add(font_name)
                    except Exception:
                        pass

                fill_color = getattr(getattr(text_state, "color_state", None), "fill_color", None)
                if fill_color is not None:
                    if not VisualAccessibilityAgent._is_monochrome(fill_color):
                        analysis["color_only_text_count"] += 1
                    brightness = VisualAccessibilityAgent._compute_brightness(fill_color)
                    if brightness is not None and brightness > 0.85:
                        analysis["light_colored_text_count"] += 1

            if getattr(word_element, "GetBBox", None):
                bbox = word_element.GetBBox()
                page_width = analysis.get("page_width", 0)
                word_width = abs(getattr(bbox, "right", 0) - getattr(bbox, "left", 0))
                if page_width and word_width / page_width > 0.9:
                    analysis["wide_text_count"] += 1

            if getattr(word_element, "GetBackground", None):
                background = word_element.GetBackground()
                if background and getattr(background, "GetType", None):
                    if background.GetType() == image_constant:
                        analysis["image_background_text_count"] += 1
        except Exception:
            pass

    @staticmethod
    def _compute_brightness(fill_color) -> float | None:
        try:
            r = getattr(fill_color, "r", 0)
            g = getattr(fill_color, "g", 0)
            b = getattr(fill_color, "b", 0)
            return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0
        except Exception:
            return None

    @staticmethod
    def _is_monochrome(fill_color) -> bool:
        try:
            r = getattr(fill_color, "r", 0)
            g = getattr(fill_color, "g", 0)
            b = getattr(fill_color, "b", 0)
            return abs(r - g) < 16 and abs(g - b) < 16
        except Exception:
            return True

    def _check_tiny_text(self, check_code: str, analysis: dict[str, int]) -> ValidationIssue:
        tiny_text_count = analysis.get("tiny_text_count", 0)
        return self._issue(
            rule_id=check_code,
            severity=Severity.MEDIUM,
            message=(
                f"Potentially small text runs detected: {tiny_text_count}"
                if tiny_text_count
                else "No potentially small text detected"
            ),
            recommendation=(
                "Review the text size for readability; small text may be acceptable for footnotes, captions, or references"
                if tiny_text_count
                else "Text size is adequate"
            ),
            status=ValidationStatus.WARNING if tiny_text_count else ValidationStatus.PASS,
            auto_fixable=True,
        )

    def _check_watermarks(self, check_code: str, analysis: dict[str, int]) -> ValidationIssue:
        watermark_count = analysis.get("watermark_count", 0)
        return self._issue(
            rule_id=check_code,
            severity=Severity.MEDIUM,
            message=(
                f"{watermark_count} watermark annotation(s) detected"
                if watermark_count
                else "No watermark annotations detected"
            ),
            recommendation=(
                "Review or remove watermarks that reduce readability"
                if watermark_count
                else "Document does not contain watermark annotations"
            ),
            status=ValidationStatus.WARNING if watermark_count else ValidationStatus.PASS,
            auto_fixable=True,
        )

    def _check_scanned_pages(self, check_code: str, analysis: dict[str, int]) -> ValidationIssue:
        candidate_count = analysis.get("scanned_page_candidate_count", 0)
        return self._issue(
            rule_id=check_code,
            severity=Severity.MEDIUM,
            message=(
                f"{candidate_count} page(s) appear scanned or image-heavy with little selectable text"
                if candidate_count
                else "No scanned-page candidates detected"
            ),
            recommendation=(
                "Run OCR or replace scanned pages with searchable text"
                if candidate_count
                else "Document contains searchable text on page images"
            ),
            status=ValidationStatus.WARNING if candidate_count else ValidationStatus.PASS,
            auto_fixable=True,
        )

    def _check_image_only_page(self, check_code: str, analysis: dict[str, int]) -> ValidationIssue:
        image_only_count = analysis.get("image_only_candidate_count", 0)
        return self._issue(
            rule_id=check_code,
            severity=Severity.MEDIUM,
            message=(
                f"{image_only_count} image-only page candidate(s) detected"
                if image_only_count
                else "No image-only page candidates detected"
            ),
            recommendation=(
                "Check pages for missing selectable text and run OCR if needed"
                if image_only_count
                else "Page text appears selectable or searchable"
            ),
            status=ValidationStatus.WARNING if image_only_count else ValidationStatus.PASS,
            auto_fixable=True,
        )

    def _check_text_density(self, check_code: str, analysis: dict[str, int]) -> ValidationIssue:
        density_count = analysis.get("text_density_candidate_count", 0)
        return self._issue(
            rule_id=check_code,
            severity=Severity.MEDIUM,
            message=(
                f"{density_count} page(s) show dense text layout or tight margins"
                if density_count
                else "No dense text layout detected"
            ),
            recommendation=(
                "Review dense text blocks and page margins for readability"
                if density_count
                else "Text layout appears reasonably spaced"
            ),
            status=ValidationStatus.WARNING if density_count else ValidationStatus.PASS,
            auto_fixable=False,
        )

    def _check_font_consistency(self, check_code: str, analysis: dict[str, int]) -> ValidationIssue:
        font_variant_count = analysis.get("font_variant_count", 0)
        return self._issue(
            rule_id=check_code,
            severity=Severity.MEDIUM,
            message=(
                f"{font_variant_count} page(s) have large font family variation"
                if font_variant_count
                else "Font usage appears consistent"
            ),
            recommendation=(
                "Consider reducing font families to improve readability and visual consistency"
                if font_variant_count
                else "Font usage is within a consistent range"
            ),
            status=ValidationStatus.WARNING if font_variant_count else ValidationStatus.PASS,
            auto_fixable=False,
        )

    def _check_page_rotation(self, check_code: str, analysis: dict[str, int]) -> ValidationIssue:
        rotated_count = analysis.get("rotated_page_count", 0)
        return self._issue(
            rule_id=check_code,
            severity=Severity.MEDIUM,
            message=(
                f"{rotated_count} rotated page(s) detected"
                if rotated_count
                else "No rotated pages detected"
            ),
            recommendation=(
                "Verify page rotation metadata and fix orientation for readability"
                if rotated_count
                else "Page orientation appears normal"
            ),
            status=ValidationStatus.WARNING if rotated_count else ValidationStatus.PASS,
            auto_fixable=False,
        )

    def _check_colored_text_usage(self, check_code: str, analysis: dict[str, int]) -> ValidationIssue:
        color_count = analysis.get("color_only_text_count", 0)
        return self._issue(
            rule_id=check_code,
            severity=Severity.LOW,
            message=(
                f"Informational colored text usage detected: {color_count} text runs"
                if color_count
                else "No informational colored text usage detected"
            ),
            recommendation=(
                "Ensure color is not the only indicator for meaning; add icons, labels, or text indicators as needed"
                if color_count
                else "Colored text usage appears acceptable"
            ),
            status=ValidationStatus.INFO if color_count else ValidationStatus.PASS,
            auto_fixable=False,
        )

    def _check_light_colored_text(self, check_code: str, analysis: dict[str, int]) -> ValidationIssue:
        image_overlay_count = analysis.get("image_background_text_count", 0)
        light_colored_count = analysis.get("light_colored_text_count", 0)
        if image_overlay_count or light_colored_count:
            return self._issue(
                rule_id=check_code,
                severity=Severity.MEDIUM,
                message=(
                    f"{image_overlay_count} text runs over images and {light_colored_count} light-colored text runs detected"
                ),
                recommendation=(
                    "Review image overlay text and light-colored text styling; true contrast analysis is required for foreground/background validation"
                ),
                status=ValidationStatus.WARNING,
                auto_fixable=True,
            )

        return self._issue(
            rule_id=check_code,
            severity=Severity.LOW,
            message="No image-overlay or light-colored text issues detected",
            recommendation="Visual text styling appears acceptable",
            status=ValidationStatus.PASS,
        )
