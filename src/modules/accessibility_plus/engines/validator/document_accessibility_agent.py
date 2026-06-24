"""
Document Accessibility Agent - Validates core PDF document accessibility features.

Checks include:
- Title: Document has a meaningful title
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
        """Check if document has a title set."""
        try:
            title = pdf_doc.GetInfo("Title")
            has_title = bool(title and title.strip())
            return DocumentAccessibilityAgent._issue(
                rule_id=check_code,
                severity=Severity.MEDIUM,
                message=(
                    f"Document has title: '{title}'"
                    if has_title
                    else "Document does not have a title set"
                ),
                recommendation=(
                    "Title is present" 
                    if has_title 
                    else "Add a descriptive title to the PDF document"
                ),
                status=ValidationStatus.PASS if has_title else ValidationStatus.FAIL,
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
        """Check if document is marked as PDF/UA compliant.

        Checks both the internal PDFix standard flag AND the XMP pdfuaid:part
        marker. The XMP marker is the authoritative source per PDF/UA-1 spec
        and is what PAC 2026, Acrobat, and VeraPDF actually verify.
        """
        try:
            import re as _re
            from pdfixsdk.Pdfix import kPdfStandardPdfUA

            is_pdfua = False

            # Method 1: internal PDFix standard flag (fast path)
            try:
                pdf_standard = pdf_doc.GetPdfStandard()
                is_pdfua = bool(pdf_standard & kPdfStandardPdfUA)
            except Exception:
                pass

            # Method 2: XMP pdfuaid:part (authoritative — PAC 2026 / VeraPDF check)
            if not is_pdfua and hasattr(pdf_doc, "GetMetadata"):
                try:
                    raw = pdf_doc.GetMetadata()
                    if raw:
                        xmp_text = (
                            raw.decode("utf-8", errors="replace")
                            if isinstance(raw, (bytes, bytearray))
                            else str(raw)
                        )
                        if _re.search(r"<pdfuaid:part>\s*1\s*</pdfuaid:part>", xmp_text):
                            is_pdfua = True
                except Exception:
                    pass

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