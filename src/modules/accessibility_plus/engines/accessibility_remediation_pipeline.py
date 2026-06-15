"""
AccessibilityRemediationPipeline
=================================
End-to-end pipeline that:

1. **Validates** the PDF with ``AccessibilityEnginePipeline``.
2. **Remediates** every ``auto_fixable`` issue via ``RemediatorService``.
3. **Saves** the modified PDF to a ``_remediated`` path (only when changes
   were successfully applied).
4. **Re-validates** to measure improvement.

Flow
----
::

    AccessibilityEnginePipeline.run()   ← initial validation
           ↓  issues where auto_fixable=True
    RemediatorService.remediate()       ← per-issue fix (in-place on pdf_doc)
           ↓  (all fixes applied)
    _save_remediated_pdf()              ← pdf_doc.Save(remediated_path, kSaveFull)
    _clear_caches()                     ← drop all validator caches
    AccessibilityEnginePipeline.run()   ← re-validation on same pdf_doc


Context requirements
--------------------
The caller must populate ``context`` before calling ``run()``:

    context = {
        "pdf_doc":       <open PDFix PdfDoc object>,
        "pdf_doc_path":  "/path/to/document.pdf",   # str
        "document_name": "My Document",             # optional str
        "total_pages":   12,                         # optional int
    }

The PDF document is modified **in-place** by the remediators.  ``pdf_doc``
remains open after the pipeline finishes.  The caller is responsible for
closing it.

Return value
------------
::

    {
        "validation_result":    dict,              # initial AccessibilityEnginePipeline output
        "remediation_results":  list[dict],        # one entry per auto_fixable issue
        "revalidation_result":  dict,              # post-fix AccessibilityEnginePipeline output
        "remediated_pdf_path":  str | None,        # path to saved remediated file (if saved)
        "summary": {
            "issues_attempted":  int,
            "issues_fixed":      int,
            "issues_failed":     int,
            "save_success":      bool,
        },
    }
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from time import perf_counter
from typing import Any

from src.core.logger import get_logger
from .accesibility_engine_pipeline import AccessibilityEnginePipeline
from .remediator.remediator_service import RemediatorService
from .remediator.base_remediator_agent import RemediationResult

logger = get_logger(__name__)


class AccessibilityRemediationPipeline:
    """Validates → remediates → re-validates a PDF document."""

    def __init__(self) -> None:
        self.validator_pipeline = AccessibilityEnginePipeline()
        self._remediator_service = RemediatorService()

    # ------------------------------------------------------------------
    # Public entry-point
    # ------------------------------------------------------------------

    def run(
        self,
        organization_id: int | None,
        project_id: str | None,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Execute the full validate → remediate → re-validate cycle.

        Args:
            organization_id: Org context forwarded to the validator pipeline.
            project_id:      Project context forwarded to the validator pipeline.
            context:         Shared context dict (must contain ``pdf_doc``).

        Returns:
            Combined result dict (see module docstring for schema).
        """
        start = perf_counter()
        context.setdefault("_cache", {})

        pdf_path = context.get("pdf_doc_path") or context.get("document_name") or "unknown"
        logger.info(
            "Remediation pipeline started | org=%s project=%s doc=%s",
            organization_id, project_id, pdf_path,
        )

        # ── Step 1: Initial validation ────────────────────────────────
        validation_result = self.validator_pipeline.run(
            organization_id=organization_id,
            project_id=project_id,
            context=context,
        )

        auto_fixable_issues = [
            issue for issue in validation_result.get("issues", [])
            if issue.get("auto_fixable") and issue.get("status") != "PASS"
        ]

        logger.info(
            "Initial validation done | total_issues=%s auto_fixable=%s",
            validation_result.get("total_issues", 0),
            len(auto_fixable_issues),
        )

        # ── Step 2: Remediate ─────────────────────────────────────────
        remediation_results: list[dict[str, Any]] = []
        issues_fixed = 0
        issues_failed = 0

        for issue in auto_fixable_issues:
            result: RemediationResult = self._remediate_issue(issue, context)
            result_dict = asdict(result)
            remediation_results.append(result_dict)

            if result.success:
                issues_fixed += 1
            else:
                issues_failed += 1
                logger.warning(
                    "Remediation failed | rule_id=%s error=%s",
                    result.rule_id, result.error,
                )

        # ── Step 3: Save remediated PDF (only if at least one fix applied) ──
        remediated_pdf_path: str | None = None
        save_success = False

        if issues_fixed > 0:
            remediated_pdf_path, save_success = self._save_remediated_pdf(context)
            if save_success:
                logger.info("Remediated PDF saved to: %s", remediated_pdf_path)
            else:
                logger.warning("Failed to save remediated PDF")

        # ── Step 4: Clear caches then re-validate ────────────────────
        self._clear_caches(context)

        revalidation_result = self.validator_pipeline.run(
            organization_id=organization_id,
            project_id=project_id,
            context=context,
        )

        elapsed_ms = int((perf_counter() - start) * 1000)
        logger.info(
            "Remediation pipeline finished | doc=%s fixed=%s failed=%s "
            "initial_issues=%s revalidation_issues=%s duration_ms=%s",
            pdf_path,
            issues_fixed,
            issues_failed,
            validation_result.get("total_issues", 0),
            revalidation_result.get("total_issues", 0),
            elapsed_ms,
        )

        return {
            "validation_result": validation_result,
            "remediation_results": remediation_results,
            "revalidation_result": revalidation_result,
            "remediated_pdf_path": remediated_pdf_path,
            "summary": {
                "issues_attempted": len(auto_fixable_issues),
                "issues_fixed": issues_fixed,
                "issues_failed": issues_failed,
                "save_success": save_success,
                "total_duration_ms": elapsed_ms,
            },
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _remediate_issue(
        self,
        issue: dict[str, Any],
        context: dict[str, Any],
    ) -> RemediationResult:
        """
        Route a single auto-fixable issue to the correct remediator agent.

        Never raises – all exceptions are caught by ``RemediatorService``.
        """
        return self._remediator_service.remediate(issue, context)

    def _save_remediated_pdf(
        self,
        context: dict[str, Any],
    ) -> tuple[str | None, bool]:
        """
        Persist the in-memory PDFix document to a ``_remediated`` output file.

        Returns:
            (remediated_path_str, success_bool)
        """
        pdf_doc = context.get("pdf_doc")
        if pdf_doc is None:
            logger.warning("_save_remediated_pdf: pdf_doc not in context – skipping save")
            return None, False

        original_path = context.get("pdf_doc_path") or ""
        if not original_path:
            logger.warning("_save_remediated_pdf: pdf_doc_path not in context – skipping save")
            return None, False

        try:
            from pdfixsdk.Pdfix import kSaveFull  # type: ignore[import]

            p = Path(original_path)
            remediated_path = p.parent / f"{p.stem}_remediated{p.suffix}"

            ok = pdf_doc.Save(str(remediated_path), kSaveFull)
            if not ok:
                logger.error(
                    "_save_remediated_pdf: pdf_doc.Save() returned False for '%s'",
                    remediated_path,
                )
                return None, False

            _apply_display_doc_title(str(remediated_path))

            context["_remediated_pdf_path"] = str(remediated_path)
            return str(remediated_path), True

        except ImportError:
            logger.error("_save_remediated_pdf: pdfixsdk not installed")
            return None, False
        except Exception as exc:
            logger.exception("_save_remediated_pdf: unexpected error")
            return None, False

    @staticmethod
    def _clear_caches(context: dict[str, Any]) -> None:
        """
        Drop all validator caches so re-validation traverses the updated document.

        After remediations (especially ``DOC_IS_TAGGED`` which adds a new
        structure tree) cached data from the initial validation run is stale.
        """
        context["_cache"] = {}


# ---------------------------------------------------------------------------
# Module-level helper: set DisplayDocTitle via pypdf (PDFix has no API for it)
# ---------------------------------------------------------------------------

def _apply_display_doc_title(pdf_path: str) -> None:
    """
    Open the saved PDF with pypdf and write /ViewerPreferences /DisplayDocTitle true.

    Adobe Acrobat's "Title" accessibility check requires THREE conditions:
      1. Info /Title          - set by PDFix SetInfo()
      2. XMP dc:title         - set by PDFix SetMetadata()
      3. /DisplayDocTitle     - PDFix SDK 9.0.0 has no Python API for this,
                                so we patch it here with pypdf post-save.
    """
    try:
        from pypdf import PdfReader, PdfWriter
        from pypdf.generic import BooleanObject, DictionaryObject, NameObject

        reader = PdfReader(pdf_path)
        writer = PdfWriter()
        writer.clone_document_from_reader(reader)

        root = writer._root_object
        vp_key = NameObject("/ViewerPreferences")
        if vp_key not in root:
            root[vp_key] = DictionaryObject()
        root[vp_key][NameObject("/DisplayDocTitle")] = BooleanObject(True)

        with open(pdf_path, "wb") as fh:
            writer.write(fh)

        logger.info("_apply_display_doc_title: set /DisplayDocTitle true in '%s'", pdf_path)
    except Exception as exc:
        logger.warning("_apply_display_doc_title: failed for '%s': %s", pdf_path, exc)
