"""
Document Accessibility Agent - Validates core PDF document accessibility features.

Checks include:
- Title: Document has a meaningful title in BOTH Info dictionary AND XMP stream
- Language: Document language is properly set
- Metadata: Document contains metadata
- Tagged PDF: Document has proper structure tree
- PDF/UA flag: Document is marked as PDF/UA compliant
- Bookmarks: Document has navigation bookmarks

Uses PDFix SDK for validation:
    pdf_doc.GetLang()
    pdf_doc.GetMetadata()
    pdf_doc.GetStructTree()
    pdf_doc.GetInfo("Title")
    pdf_doc.GetPdfStandard()
    pdf_doc.GetBookmarkRoot()

Title check note:
    Adobe Acrobat's Accessibility Checker "Title" test reads dc:title from the
    XMP metadata stream, NOT the Info dictionary /Title key.  A PDF can have a
    perfectly valid /Title in the Info dict and still fail Acrobat's check if
    the XMP stream is absent or lacks <dc:title>.
    Therefore _check_title() validates BOTH sources and fails (auto_fixable=True)
    if either is missing, so the remediator knows to write XMP dc:title.
"""

from __future__ import annotations
from typing import Any
from src.modules.accessibility_plus.models.validation_issue import (
    Severity,
    ValidationIssue,
    ValidationStatus,
)
from .accessibility_agent_framework import BaseAccessibilityValidatorAgent


class DocumentAccessibilityAgent(BaseAccessibilityValidatorAgent):
    """Validates document-level accessibility properties."""

    agent_code = "DOCUMENT_ACCESSIBILITY_AGENT"
    agent_name = "Document Accessibility Agent"
    category = "Document Properties"

    supported_checks = {
        "DOC_HAS_TITLE",
        "DOC_HAS_LANGUAGE",
        "DOC_HAS_METADATA",
        "DOC_IS_TAGGED",
        "DOC_PDFUA_DECLARATION",
        "DOC_HAS_BOOKMARKS",
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
            agent_name=DocumentAccessibilityAgent.agent_name,
            rule_id=rule_id,
            category="Document Properties",
            severity=severity.value,
            page_no=None,
            message=message,
            recommendation=recommendation,
            auto_fixable=auto_fixable,
            status=status.value,
        )

    def run_check(self, check_code: str, context: dict[str, Any]) -> ValidationIssue:
        """
        Execute accessibility check on PDF document.

        Args:
            check_code: Check identifier (e.g., DOC_HAS_TITLE)
            context: Context dict containing:
                - pdf_doc: PDFix PdfDoc object (opened and ready)
                - pdf_doc_path: Path to PDF file
                - organization_id: Organization context
                - project_id: Project context

        Returns:
            ValidationIssue with check results
        """
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

        check_handlers = {
            "DOC_HAS_TITLE": self._check_title,
            "DOC_HAS_LANGUAGE": self._check_language,
            "DOC_HAS_METADATA": self._check_metadata,
            "DOC_IS_TAGGED": self._check_tagged_pdf,
            "DOC_PDFUA_DECLARATION": self._check_pdfua_flag,
            "DOC_HAS_BOOKMARKS": self._check_bookmarks,
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

            return handler(pdf_doc, check_code)
        except Exception as exc:
            return self._issue(
                rule_id=check_code,
                severity=Severity.HIGH,
                message=f"Check execution error: {str(exc)}",
                recommendation="Review the error and retry the check",
                status=ValidationStatus.FAIL,
            )

    @staticmethod
    def _check_title(pdf_doc, check_code: str) -> ValidationIssue:
        """
        Check that the document title satisfies ALL THREE conditions Adobe requires.

        Adobe Acrobat's "Title" accessibility check passes only when:
          1. Info /Title         – non-empty title in the Info dictionary.
          2. XMP dc:title        – title present in the XMP metadata stream.
                                   Acrobat reads from XMP, not the Info dict.
          3. DisplayDocTitle     – /ViewerPreferences /DisplayDocTitle true.
                                   Without this flag the title is never shown
                                   in the window title bar and Acrobat fails
                                   "Title" even when dc:title is in XMP.

        Any missing condition → FAIL, auto_fixable=True so the remediator
        sets all three in one pass.
        """
        try:
            # ── 1. Info dictionary ────────────────────────────────────
            title = (pdf_doc.GetInfo("Title") or "").strip()
            has_info_title = bool(title)

            # ── 2. XMP dc:title ───────────────────────────────────────
            has_xmp_title = _has_xmp_dc_title(pdf_doc)

            # ── 3. ViewerPreferences / DisplayDocTitle ────────────────
            has_display_doc_title = _has_display_doc_title(pdf_doc)

            # ── 4. Evaluate ───────────────────────────────────────────
            all_ok = has_info_title and has_xmp_title and has_display_doc_title

            if all_ok:
                return DocumentAccessibilityAgent._issue(
                    rule_id=check_code,
                    severity=Severity.MEDIUM,
                    message=(
                        f"Document title is fully configured: '{title}' "
                        f"(Info dict + XMP dc:title + DisplayDocTitle)"
                    ),
                    recommendation="Title is correctly set for Adobe accessibility compliance",
                    status=ValidationStatus.PASS,
                    auto_fixable=True,
                )

            # Build a specific message listing what is missing
            missing: list[str] = []
            if not has_info_title:
                missing.append("Info /Title not set")
            if not has_xmp_title:
                missing.append("XMP dc:title missing (Adobe reads from XMP)")
            if not has_display_doc_title:
                missing.append(
                    "ViewerPreferences /DisplayDocTitle not true "
                    "(title won't appear in title bar)"
                )

            title_display = f"'{title}'" if has_info_title else "(none)"
            return DocumentAccessibilityAgent._issue(
                rule_id=check_code,
                severity=Severity.MEDIUM,
                message=(
                    f"Document title {title_display} is incomplete for Adobe accessibility. "
                    f"Missing: {'; '.join(missing)}."
                ),
                recommendation=(
                    "Set Info /Title, add XMP dc:title, and enable "
                    "ViewerPreferences /DisplayDocTitle — all three are required "
                    "for Adobe Acrobat's Title accessibility check to pass."
                ),
                status=ValidationStatus.FAIL,
                auto_fixable=True,
            )

        except Exception as exc:
            return DocumentAccessibilityAgent._issue(
                rule_id=check_code,
                severity=Severity.MEDIUM,
                message=f"Error reading document title: {str(exc)}",
                recommendation="Check PDF integrity and retry",
                status=ValidationStatus.FAIL,
            )

    @staticmethod
    def _check_language(pdf_doc, check_code: str) -> ValidationIssue:
        """Check if document language is set."""
        try:
            lang = pdf_doc.GetLang()
            has_lang = bool(lang and lang.strip())
            return DocumentAccessibilityAgent._issue(
                rule_id=check_code,
                severity=Severity.HIGH,
                message=(
                    f"Document language is set to: {lang}"
                    if has_lang
                    else "Document does not have language defined"
                ),
                recommendation=(
                    "Language is properly set"
                    if has_lang
                    else "Set document language using PDF metadata (e.g., 'en-US')"
                ),
                status=ValidationStatus.PASS if has_lang else ValidationStatus.FAIL,
                auto_fixable=True,
            )
        except Exception as exc:
            return DocumentAccessibilityAgent._issue(
                rule_id=check_code,
                severity=Severity.MEDIUM,
                message=f"Error reading document language: {str(exc)}",
                recommendation="Check PDF integrity and retry",
                status=ValidationStatus.FAIL,
            )

    @staticmethod
    def _check_metadata(pdf_doc, check_code: str) -> ValidationIssue:
        """Check if document has metadata."""
        try:
            metadata_fields = [
                pdf_doc.GetInfo("Title"),
                pdf_doc.GetInfo("Author"),
                pdf_doc.GetInfo("Subject"),
                pdf_doc.GetInfo("Keywords"),
            ]
            has_metadata = any(
                field and str(field).strip()
                for field in metadata_fields
            )
            return DocumentAccessibilityAgent._issue(
                rule_id=check_code,
                severity=Severity.LOW,
                message=(
                    "Document contains metadata in standard info fields"
                    if has_metadata
                    else "Document does not have title/author/subject/keywords metadata"
                ),
                recommendation=(
                    "Metadata is present"
                    if has_metadata
                    else "Add document metadata (title, author, subject, keywords)"
                ),
                status=ValidationStatus.PASS if has_metadata else ValidationStatus.WARNING,
                auto_fixable=True,
            )
        except Exception as exc:
            return DocumentAccessibilityAgent._issue(
                rule_id=check_code,
                severity=Severity.LOW,
                message=f"Error checking document metadata: {str(exc)}",
                recommendation="Check PDF integrity and retry",
                status=ValidationStatus.FAIL,
            )

    @staticmethod
    def _check_tagged_pdf(pdf_doc, check_code: str) -> ValidationIssue:
        """Check if document has proper tagging (structure tree)."""
        try:
            struct_tree = pdf_doc.GetStructTree()
            is_tagged = bool(struct_tree)
            return DocumentAccessibilityAgent._issue(
                rule_id=check_code,
                severity=Severity.CRITICAL,
                message=(
                    "Document is properly tagged with structure tree"
                    if is_tagged
                    else "Document is not tagged (no structure tree found)"
                ),
                recommendation=(
                    "Document has proper tagging"
                    if is_tagged
                    else "Apply automatic tagging using PDFix SDK or manual tagging in Acrobat"
                ),
                status=ValidationStatus.PASS if is_tagged else ValidationStatus.FAIL,
                auto_fixable=True,
            )
        except Exception as exc:
            return DocumentAccessibilityAgent._issue(
                rule_id=check_code,
                severity=Severity.HIGH,
                message=f"Error checking document tagging: {str(exc)}",
                recommendation="Check PDF integrity and retry",
                status=ValidationStatus.FAIL,
            )

    @staticmethod
    def _check_pdfua_flag(pdf_doc, check_code: str) -> ValidationIssue:
        """Check if document is marked as PDF/UA compliant."""
        try:
            from pdfixsdk.Pdfix import kPdfStandardPdfUA

            pdf_standard = pdf_doc.GetPdfStandard()
            is_pdfua = bool(pdf_standard & kPdfStandardPdfUA)

            return DocumentAccessibilityAgent._issue(
                rule_id=check_code,
                severity=Severity.HIGH,
                message=(
                    "Document is marked as PDF/UA compliant"
                    if is_pdfua
                    else "Document is not marked as PDF/UA compliant"
                ),
                recommendation=(
                    "PDF/UA flag is set"
                    if is_pdfua
                    else "Enable PDF/UA standard compliance in document properties"
                ),
                status=ValidationStatus.PASS if is_pdfua else ValidationStatus.FAIL,
                auto_fixable=True,
            )
        except Exception as exc:
            return DocumentAccessibilityAgent._issue(
                rule_id=check_code,
                severity=Severity.MEDIUM,
                message=f"Error checking PDF/UA standard: {str(exc)}",
                recommendation="Check PDF integrity and retry",
                status=ValidationStatus.FAIL,
            )

    @staticmethod
    def _check_bookmarks(pdf_doc, check_code: str) -> ValidationIssue:
        """Check if document has navigation bookmarks."""
        try:
            bookmark_root = pdf_doc.GetBookmarkRoot()
            has_bookmarks = bool(bookmark_root)

            if has_bookmarks:
                try:
                    num_children = bookmark_root.GetNumChildren()
                    has_bookmarks = num_children > 0
                    message = (
                        f"Document has {num_children} bookmarks"
                        if num_children > 0
                        else "Document bookmark structure exists but is empty"
                    )
                    recommendation = (
                        "Bookmarks are present for navigation"
                        if num_children > 0
                        else "Add bookmarks to improve document navigation"
                    )
                    status = (
                        ValidationStatus.PASS
                        if num_children > 0
                        else ValidationStatus.WARNING
                    )
                except Exception:
                    message = "Document has bookmark structure"
                    recommendation = "Bookmark structure exists"
                    status = ValidationStatus.WARNING
            else:
                message = "Document does not have bookmarks"
                recommendation = "Add bookmarks to improve document navigation and accessibility"
                status = ValidationStatus.WARNING

            return DocumentAccessibilityAgent._issue(
                rule_id=check_code,
                severity=Severity.LOW,
                message=message,
                recommendation=recommendation,
                status=status,
            )
        except Exception as exc:
            return DocumentAccessibilityAgent._issue(
                rule_id=check_code,
                severity=Severity.LOW,
                message=f"Error checking document bookmarks: {str(exc)}",
                recommendation="Check PDF integrity and retry",
                status=ValidationStatus.FAIL,
            )


# ---------------------------------------------------------------------------
# Module-level XMP helper (used by _check_title)
# ---------------------------------------------------------------------------

def _has_display_doc_title(pdf_doc: Any) -> bool:
    """
    Return True if /ViewerPreferences /DisplayDocTitle is set to true.

    Adobe Acrobat's "Title" accessibility check requires the document title
    to be displayed in the window title bar.  This is controlled by the
    /DisplayDocTitle boolean in the /ViewerPreferences dictionary of the
    PDF catalog.  When absent or false, Acrobat fails "Title" even if
    dc:title is correctly set in XMP.
    """
    try:
        _DISPLAY_DOC_TITLE_CANDIDATES = [
            "kViewerPrefDisplayDocTitle",
            "kPdfViewerPrefDisplayDocTitle",
            "PdfViewerPrefDisplayDocTitle",
        ]
        for const_name in _DISPLAY_DOC_TITLE_CANDIDATES:
            try:
                from pdfixsdk import Pdfix as _pdfix_module  # type: ignore[import]
                flag = getattr(_pdfix_module, const_name, None)
                if flag is not None:
                    current = pdf_doc.GetViewerPreferences()
                    return bool(current & int(flag))
            except Exception:
                continue
        # If we can't read the flag, assume it's not set (conservative).
        return False
    except Exception:
        return False


def _has_xmp_dc_title(pdf_doc: Any) -> bool:
    """
    Return True if the document's XMP metadata stream contains a <dc:title> element.

    Adobe Acrobat's Accessibility Checker reads the document title from
    XMP dc:title, NOT from the Info dictionary /Title key.  This helper
    lets _check_title() detect the mismatch so the remediator can fix it.

    Returns False (not a crash) if GetMetadata() is unavailable or the XMP
    stream is absent, empty, or malformed — all of which mean Acrobat will
    fail its Title check.
    """
    try:
        if not hasattr(pdf_doc, "GetMetadata"):
            return False

        raw = pdf_doc.GetMetadata()
        if not raw:
            return False

        if isinstance(raw, (bytes, bytearray)):
            xmp_str = raw.decode("utf-8", errors="replace")
        elif isinstance(raw, str):
            xmp_str = raw
        else:
            return False

        return "<dc:title>" in xmp_str

    except Exception:
        return False
