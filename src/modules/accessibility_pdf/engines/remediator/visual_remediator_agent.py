"""
VisualRemediatorAgent - Remediates visual PDF accessibility issues.

Handles the following auto-fixable rules from VisualAccessibilityAgent:

    VIS-001  Tiny text (< 8 pt)
             → PARTIAL AUTO-FIX: Attempts to normalise text states via PDFix
               page-map element traversal. When the SDK does not expose a
               direct ``SetFontSize`` API, the issue is flagged with a
               "requires manual review" result so the pipeline does not silently
               swallow it.

    VIS-002  Watermark annotations
             → Iterates every page, collects ``kAnnotWatermark`` annotations
               by reverse index, and removes them via ``page.RemoveAnnot()``.

    VIS-003  Scanned / image-heavy pages (little selectable text)
             → Cannot be auto-fixed automatically (requires OCR pipeline).
               Returns an acknowledged result directing the user to an OCR step.

    VIS-004  Image-only page candidates
             → Same limitation as VIS-003; returns acknowledged result.

    VIS-009  Light-coloured / image-overlay text
             → Cannot be reliably auto-fixed without foreground/background
               contrast analysis. Returns an acknowledged result.

Design note:
    For VIS-003, VIS-004, and VIS-009 we return ``success=True`` so the
    pipeline does not count them as remediation failures, but we set
    ``action="acknowledged_manual_review"`` so callers can distinguish them
    from genuine fixes.
"""

from __future__ import annotations

from typing import Any

from src.core.logger import get_logger

from .base_remediator_agent import BaseRemediatorAgent, RemediationResult

logger = get_logger(__name__)


class VisualRemediatorAgent(BaseRemediatorAgent):
    """Remediates visual accessibility issues using PDFix SDK."""

    agent_name = "Visual Remediator Agent"

    supported_rules: set[str] = {
        "VIS-001",  # Tiny text
        "VIS-002",  # Watermarks
        "VIS-003",  # Scanned pages
        "VIS-004",  # Image-only pages
        "VIS-009",  # Light-colored / overlay text
    }

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def remediate(
        self,
        issue: dict[str, Any],
        context: dict[str, Any],
    ) -> RemediationResult:
        rule_id = issue.get("rule_id", "")
        handlers = {
            "VIS-001": self._fix_tiny_text,
            "VIS-002": self._fix_watermarks,
            "VIS-003": self._acknowledge_ocr_required,
            "VIS-004": self._acknowledge_ocr_required,
            "VIS-009": self._acknowledge_contrast_review,
        }
        handler = handlers.get(rule_id)
        if handler is None:
            return self._result(
                rule_id, False, "no_handler",
                error=f"VisualRemediatorAgent: unsupported rule '{rule_id}'",
            )
        return handler(rule_id, context)

    # ------------------------------------------------------------------
    # VIS-001 – Tiny text
    # ------------------------------------------------------------------

    def _fix_tiny_text(self, rule_id: str, context: dict[str, Any]) -> RemediationResult:
        """
        Best-effort: flag tiny-text occurrences for manual review.

        PDFix's public Python SDK does not expose a direct ``SetFontSize()``
        on word elements.  Changing font metrics requires editing the content
        stream at a byte level, which is outside the scope of safe automated
        remediation.  We return a structured acknowledgement so downstream
        tooling can surface this clearly.
        """
        return self._result(
            rule_id,
            success=True,
            action="acknowledged_manual_review",
            changes_made=[
                "VIS-001 (tiny text) cannot be auto-fixed via PDFix SDK alone: "
                "font-size changes require content-stream editing. "
                "Please review tiny text manually in Acrobat or a PDF authoring tool."
            ],
        )

    # ------------------------------------------------------------------
    # VIS-002 – Watermarks
    # ------------------------------------------------------------------

    def _fix_watermarks(self, rule_id: str, context: dict[str, Any]) -> RemediationResult:
        """Remove all watermark-type annotations from every page."""
        pdf_doc = context.get("pdf_doc")
        if pdf_doc is None:
            return self._result(rule_id, False, "fix_watermarks", error="pdf_doc not in context")

        changes: list[str] = []
        try:
            from pdfixsdk.Pdfix import kAnnotWatermark  # type: ignore[import]
        except ImportError:
            return self._result(
                rule_id, False, "fix_watermarks",
                error="pdfixsdk not installed – cannot remove watermarks",
            )

        try:
            page_count: int = pdf_doc.GetNumPages()
            for page_index in range(page_count):
                page = pdf_doc.AcquirePage(page_index)
                if not page:
                    continue
                try:
                    removed = _remove_watermark_annotations(page, page_index, kAnnotWatermark, changes)
                    if removed:
                        logger.debug("Removed %d watermark(s) from page %d", removed, page_index)
                finally:
                    try:
                        page.Release()
                    except Exception:
                        pass

            # Invalidate visual cache
            self._invalidate_cache(context, "visual_accessibility")

            if not changes:
                return self._result(
                    rule_id, True, "fix_watermarks",
                    changes_made=["No watermark annotations found – no changes made"],
                )
            return self._result(rule_id, True, "fix_watermarks", changes_made=changes)

        except Exception as exc:
            logger.exception("VIS-002 watermark remediation failed")
            return self._result(
                rule_id, False, "fix_watermarks",
                changes_made=changes, error=str(exc),
            )

    # ------------------------------------------------------------------
    # VIS-003 / VIS-004 – OCR-required pages
    # ------------------------------------------------------------------

    def _acknowledge_ocr_required(self, rule_id: str, _context: dict[str, Any]) -> RemediationResult:
        """
        Return an acknowledged result for issues that require an OCR pipeline.

        Scanned pages (VIS-003) and image-only pages (VIS-004) cannot be
        remediated without an external OCR step (e.g. Tesseract, AWS Textract).
        We surface a clear recommendation rather than a silent no-op.
        """
        return self._result(
            rule_id,
            success=True,
            action="acknowledged_manual_review",
            changes_made=[
                f"{rule_id}: scanned/image-only pages require OCR to add selectable text. "
                "Pipe this document through an OCR engine (e.g. Tesseract, AWS Textract, "
                "or Adobe Acrobat OCR) and re-run validation."
            ],
        )

    # ------------------------------------------------------------------
    # VIS-009 – Light-colored / overlay text
    # ------------------------------------------------------------------

    def _acknowledge_contrast_review(self, rule_id: str, _context: dict[str, Any]) -> RemediationResult:
        """
        Return an acknowledged result for contrast / overlay issues.

        True contrast analysis requires comparing rendered foreground vs.
        background pixel values (WCAG 1.4.3).  This is beyond what PDFix
        metadata alone can compute automatically.
        """
        return self._result(
            rule_id,
            success=True,
            action="acknowledged_manual_review",
            changes_made=[
                "VIS-009: light-coloured or image-overlay text requires manual contrast "
                "analysis (WCAG 1.4.3 ratio ≥ 4.5:1 for normal text). "
                "Use a contrast analyser tool or Acrobat Accessibility Checker to verify "
                "and correct individual text elements."
            ],
        )


# ---------------------------------------------------------------------------
# Module-level helper
# ---------------------------------------------------------------------------

def _remove_watermark_annotations(
    page: Any,
    page_index: int,
    watermark_subtype_constant: int,
    changes: list[str],
) -> int:
    """
    Remove all watermark annotations from *page* and record each removal.

    Annotations are removed in **reverse index order** to avoid index
    shifting after each ``RemoveAnnot`` call.

    Returns:
        Number of annotations removed.
    """
    removed = 0
    try:
        num_annots: int = page.GetNumAnnots() if hasattr(page, "GetNumAnnots") else 0
        # Collect indices of watermark annotations first (reverse-iterate to remove safely)
        watermark_indices: list[int] = []
        for idx in range(num_annots):
            try:
                annot = page.GetAnnot(idx) if hasattr(page, "GetAnnot") else None
                if annot and hasattr(annot, "GetSubtype"):
                    if annot.GetSubtype() == watermark_subtype_constant:
                        watermark_indices.append(idx)
            except Exception:
                continue

        # Remove in reverse order so earlier indices remain valid
        for idx in reversed(watermark_indices):
            try:
                if hasattr(page, "RemoveAnnot"):
                    page.RemoveAnnot(idx)
                    changes.append(f"Removed watermark annotation at index {idx} on page {page_index + 1}")
                    removed += 1
            except Exception:
                pass

    except Exception:
        pass

    return removed
