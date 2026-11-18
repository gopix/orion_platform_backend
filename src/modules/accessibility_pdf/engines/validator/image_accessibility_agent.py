"""
ImageAccessibilityAgent - Validates PDF image accessibility using PDFix metadata.

Checks include:
- IMG-001: All images must have an accessible name — either /Alt attribute OR a
           sibling/child Caption element (PDF/UA allows either as the accessible name source).
- IMG-002: Alt text (when present) must be descriptive — not empty, not just a
           generic placeholder like "image" or "figure".

Accessible name priority order (PDF/UA §7.3):
    1. /Alt attribute on the Figure element
    2. /ActualText attribute on the Figure element
    3. Caption element that is a sibling of Figure (inside the same parent container)
    4. Caption element that is a child of the Figure element

PDFix-based validation using:
    pdf_doc.GetStructTree()
    element.GetType() == "Figure"
    element.GetAlt()
    element.GetActualText()   (if available)
    element.GetPageNumber()
    element.GetId()

No external ML/CV dependencies - pure PDFix metadata + rule-based validation.
"""

from __future__ import annotations
from typing import Any

from src.modules.accessibility_pdf.models.validation_issue import (
    Severity,
    ValidationIssue,
    ValidationStatus,
)
from .accessibility_agent_framework import BaseAccessibilityValidatorAgent
from src.modules.accessibility_pdf.engines.alt_placeholder import is_placeholder_alt


class ImageAccessibilityAgent(BaseAccessibilityValidatorAgent):
    """Validates image accessibility in documents using PDFix metadata."""

    agent_code = "IMAGE_ACCESSIBILITY_AGENT"
    agent_name = "Image Accessibility Agent"
    category = "Image Accessibility"

    supported_checks = {
        "IMG-001",
        "IMG-002",
    }

    @staticmethod
    def _issue(
        rule_id: str,
        severity: Severity,
        message: str,
        recommendation: str,
        status: ValidationStatus,
        auto_fixable: bool | None = None,
    ) -> ValidationIssue:
        return ValidationIssue(
            agent_name=ImageAccessibilityAgent.agent_name,
            rule_id=rule_id,
            category="Image Accessibility",
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

        # Extract images once per PDF to avoid repeated tree traversals
        cache = context.setdefault("_cache", {})
        image_cache = cache.setdefault("images_by_pdf", {})
        pdf_path = context.get("pdf_doc_path", "")
        if pdf_path not in image_cache:
            struct_tree = pdf_doc.GetStructTree()
            images = self._extract_images(struct_tree) if struct_tree else []
            image_cache[pdf_path] = images
        else:
            images = image_cache[pdf_path]

        check_handlers = {
            "IMG-001": self._check_missing_alt_text,
            "IMG-002": self._check_alt_text_quality,
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
            return handler(pdf_doc, check_code, images)
        except Exception as exc:
            return self._issue(
                rule_id=check_code,
                severity=Severity.HIGH,
                message=f"Check execution error: {str(exc)}",
                recommendation="Review the error and retry the check",
                status=ValidationStatus.FAIL,
            )

    # -------------------------------------------------------------------------
    # IMG-001 — accessible name presence
    # -------------------------------------------------------------------------

    @staticmethod
    def _check_missing_alt_text(pdf_doc, check_code: str, images: list[dict]) -> ValidationIssue:
        """
        Check that every Figure element has an accessible name.

        A Figure is considered accessible if ANY of the following is present:
          • /Alt attribute (non-None, non-empty)
          • /ActualText attribute (non-None, non-empty)
          • sibling or child Caption element with extractable text

        This matches PAC / PDF/UA §7.3 which allows Caption to substitute for /Alt.
        """
        if not images:
            return ImageAccessibilityAgent._issue(
                rule_id=check_code,
                severity=Severity.MEDIUM,
                message="No images found in document",
                recommendation="If document contains images, ensure they are properly tagged",
                status=ValidationStatus.PASS,
            )

        no_accessible_name: list[dict] = []
        caption_only: list[dict] = []       # accessible via caption, not /Alt

        for img in images:
            alt         = (img.get("alt") or "").strip()
            actual_text = (img.get("actual_text") or "").strip()
            caption     = (img.get("caption") or "").strip()

            has_alt         = bool(alt)
            has_actual_text = bool(actual_text)
            has_caption     = bool(caption)

            if not has_alt and not has_actual_text and not has_caption:
                no_accessible_name.append(img)
            elif not has_alt and not has_actual_text and has_caption:
                caption_only.append(img)

        total = len(images)
        missing = len(no_accessible_name)

        if missing == 0:
            detail = (
                f"All {total} image(s) have accessible names"
                if not caption_only
                else (
                    f"All {total} image(s) have accessible names "
                    f"({len(caption_only)} via Caption element only — "
                    f"consider also adding /Alt for maximum compatibility)"
                )
            )
            return ImageAccessibilityAgent._issue(
                rule_id=check_code,
                severity=Severity.CRITICAL,
                message=detail,
                recommendation="All images have accessible names",
                status=ValidationStatus.PASS,
            )

        return ImageAccessibilityAgent._issue(
            rule_id=check_code,
            severity=Severity.CRITICAL,
            message=(
                f"{missing} of {total} image(s) have no accessible name "
                f"(no /Alt, no /ActualText, and no Caption element)"
            ),
            recommendation=(
                "Add an /Alt attribute or a Caption sibling/child element "
                "to every Figure structure element"
            ),
            status=ValidationStatus.FAIL,
            auto_fixable=True,
        )

    # -------------------------------------------------------------------------
    # IMG-002 — alt text quality
    # -------------------------------------------------------------------------

    @staticmethod
    def _check_alt_text_quality(pdf_doc, check_code: str, images: list[dict]) -> ValidationIssue:
        """
        Check that /Alt text (when present) is descriptive.

        Images that are accessible only via Caption are skipped here — their
        caption quality is not evaluated (captions are visible body text and
        assumed to be authored meaningfully).

        Failures:
          • /Alt present but empty or whitespace-only
          • /Alt is a generic single-word placeholder (image, photo, figure, …)
        """
        if not images:
            return ImageAccessibilityAgent._issue(
                rule_id=check_code,
                severity=Severity.MEDIUM,
                message="No images found in document",
                recommendation="If document contains images, ensure they are properly tagged",
                status=ValidationStatus.PASS,
            )

        # Placeholder detection lives in engines/alt_placeholder.py so that this
        # check and the pipeline that WRITES the placeholder share one
        # definition.  They used to disagree: this method tested
        # `alt.lower() in {"image", "photo", …}`, which does not match
        # "[TO BE DESCRIBED]" — the marker alt_text_sanitizer emits when
        # alt-text generation fails.  IMG-002 therefore PASSED on figures whose
        # /Alt was the pipeline's own unresolved placeholder, and the report
        # told the caller the alt text was fine.
        poor_alt: list[tuple[dict, str]] = []

        for img in images:
            alt     = img.get("alt")       # None means /Alt not set at all
            caption = (img.get("caption") or "").strip()

            # No /Alt — accessibility comes from Caption (or will fail IMG-001).
            # Either way, IMG-002 is not the right check to report here.
            if alt is None:
                continue

            is_bad, reason = is_placeholder_alt(alt)
            if is_bad:
                poor_alt.append((img, reason))

        total          = len(images)
        # Images where alt was evaluated (those with /Alt set)
        evaluated      = sum(1 for img in images if img.get("alt") is not None)
        poor_count     = len(poor_alt)
        caption_skipped = total - evaluated

        if poor_count == 0:
            note = (
                f" ({caption_skipped} image(s) use Caption as accessible name — not evaluated here)"
                if caption_skipped else ""
            )
            return ImageAccessibilityAgent._issue(
                rule_id=check_code,
                severity=Severity.HIGH,
                message=f"All {evaluated} image(s) with /Alt have descriptive text{note}",
                recommendation="All /Alt attributes are descriptive",
                status=ValidationStatus.PASS,
            )

        return ImageAccessibilityAgent._issue(
            rule_id=check_code,
            severity=Severity.HIGH,
            message=(
                f"{poor_count} of {evaluated} image(s) with /Alt have non-descriptive text: "
                + "; ".join(reason for _, reason in poor_alt[:3])
                + (" …" if poor_count > 3 else "")
            ),
            recommendation=(
                "Replace empty, generic or placeholder /Alt text with a meaningful "
                "description of each image's content and purpose. An unresolved "
                "'[TO BE DESCRIBED]' marker means alt-text generation did not "
                "complete — check the alt_vision_suggester step for API errors "
                "and re-run rather than shipping the placeholder."
            ),
            status=ValidationStatus.FAIL,
            auto_fixable=True,
        )

    # -------------------------------------------------------------------------
    # Structure tree traversal
    # -------------------------------------------------------------------------

    @staticmethod
    def _get_element_text(element) -> str:
        """
        Extract readable text from a struct element.

        Priority order matters:
          1. GetText()        — reads the element's actual rendered text from the
                                content stream (via MCID). This is the correct method
                                for content-bearing elements like Caption, P, Span.
          2. GetActualText()  — /ActualText attribute override (e.g. on Figure, Formula)
          3. GetAlt()         — /Alt attribute (decorative/non-text elements)
          4. GetValue()       — /V attribute (form fields)
          5. GetTitle()       — /T attribute (rarely used for text)

        Caption elements hold their text in the content stream, NOT in /Alt or /Title,
        so GetText() must come first — otherwise Caption text is silently missed.
        """
        for method_name in ("GetText", "GetActualText", "GetAlt", "GetValue", "GetTitle"):
            if hasattr(element, method_name):
                try:
                    text = getattr(element, method_name)()
                    if text and text.strip():
                        return text.strip()
                except Exception:
                    pass
        return ""

    @staticmethod
    def _get_caption_from_children(figure_element) -> str:
        """
        Look for a Caption child inside a Figure element (Pattern 2).
        Returns its text content if found.
        """
        try:
            num = figure_element.GetNumChildren() if hasattr(figure_element, "GetNumChildren") else 0
            for i in range(num):
                child = figure_element.GetChildObject(i) if hasattr(figure_element, "GetChildObject") else None
                if not child:
                    continue
                elem_type = child.GetType() if hasattr(child, "GetType") else ""
                if elem_type == "Caption":
                    text = ImageAccessibilityAgent._get_element_text(child)
                    if text:
                        return text
        except Exception:
            pass
        return ""

    @staticmethod
    def _extract_images(struct_tree) -> list[dict]:
        """
        Extract all Figure elements from the structure tree in a single traversal.

        For each Figure the dict contains:
            id          — struct element ID
            page        — 0-based page index (None if unavailable)
            type        — always "Figure"
            alt         — /Alt attribute value (None if not set)
            actual_text — /ActualText attribute value (None if not set)
            is_figure   — True
            caption     — text from Caption element (sibling or child), "" if none

        Caption lookup (PDF/UA §7.3 allows Caption to provide the accessible name):
            Pattern 1 — Caption is a sibling of Figure inside the same parent
            Pattern 2 — Caption is a direct child of the Figure element
        """
        images: list[dict] = []

        def _children(node) -> list:
            """Return the direct children of a struct node."""
            try:
                n = node.GetNumChildren() if hasattr(node, "GetNumChildren") else 0
                result = []
                for i in range(n):
                    child = node.GetChildObject(i) if hasattr(node, "GetChildObject") else None
                    if child:
                        result.append(child)
                return result
            except Exception:
                return []

        def _elem_type(node) -> str:
            try:
                return node.GetType() if hasattr(node, "GetType") else ""
            except Exception:
                return ""

        def traverse(node, depth: int = 0) -> None:
            children = _children(node)
            if not children:
                return

            # Collect any Caption siblings once for this parent level
            sibling_caption_text = ""
            for child in children:
                if _elem_type(child) == "Caption":
                    text = ImageAccessibilityAgent._get_element_text(child)
                    if text:
                        sibling_caption_text = text
                        break

            for child in children:
                et = _elem_type(child)

                if et == "Figure":
                    try:
                        alt = child.GetAlt() if hasattr(child, "GetAlt") else None
                        actual_text = None
                        if hasattr(child, "GetActualText"):
                            try:
                                actual_text = child.GetActualText()
                            except Exception:
                                pass

                        # Caption: prefer sibling (Pattern 1), fall back to child (Pattern 2)
                        caption = sibling_caption_text or \
                                  ImageAccessibilityAgent._get_caption_from_children(child)

                        images.append({
                            "id":          child.GetId() if hasattr(child, "GetId") else "",
                            "page":        child.GetPageNumber() if hasattr(child, "GetPageNumber") else None,
                            "type":        et,
                            "alt":         alt,
                            "actual_text": actual_text,
                            "is_figure":   True,
                            "caption":     caption,
                        })
                    except Exception:
                        pass

                # Always recurse — Figures can be nested inside Sect, Div, etc.
                traverse(child, depth + 1)

        try:
            traverse(struct_tree)
        except Exception:
            pass

        return images
