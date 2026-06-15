"""
DocumentRemediatorAgent - Remediates document-level PDF accessibility issues.

Handles the following auto-fixable rules from DocumentAccessibilityAgent:

    DOC_HAS_TITLE         → pdf_doc.SetInfo("Title", ...) + XMP dc:title sync
    DOC_HAS_LANGUAGE      → pdf_doc.SetLang("en-US")          (default when none set)
    DOC_HAS_METADATA      → pdf_doc.SetInfo(key, value)        (fills missing Title/Author/Subject)
    DOC_IS_TAGGED         → pdf_doc.AddTags(PdfTagsParams())   (auto-tags untagged document)
    DOC_PDFUA_DECLARATION → pdf_doc.SetPdfStandard(...)        (enables PDF/UA compliance flag)

All modifications are **in-place** on the open ``pdf_doc`` object.
The caller (``AccessibilityRemediationPipeline``) saves the document after all
remediations are complete.

XMP note (DOC_HAS_TITLE):
    Adobe Acrobat's "Title" accessibility check reads from the XMP metadata
    stream (dc:title), NOT just the Info dictionary /Title key.  PDFix
    SetInfo() updates the Info dict; we additionally patch the raw XMP stream
    so Acrobat's checker sees the value.
"""

from __future__ import annotations

from typing import Any

from src.core.logger import get_logger

from .base_remediator_agent import BaseRemediatorAgent, RemediationResult

logger = get_logger(__name__)


class DocumentRemediatorAgent(BaseRemediatorAgent):
    """Remediates document-level accessibility issues using PDFix SDK."""

    agent_name = "Document Remediator Agent"

    supported_rules: set[str] = {
        "DOC_HAS_TITLE",          # ← added: was missing auto_fixable=True in validator
        "DOC_HAS_LANGUAGE",
        "DOC_HAS_METADATA",
        "DOC_IS_TAGGED",
        "DOC_PDFUA_DECLARATION",
    }

    # Default language applied when the document has none set.
    DEFAULT_LANGUAGE = "en-US"

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
            "DOC_HAS_TITLE": self._fix_title,          # ← added
            "DOC_HAS_LANGUAGE": self._fix_language,
            "DOC_HAS_METADATA": self._fix_metadata,
            "DOC_IS_TAGGED": self._fix_tagging,
            "DOC_PDFUA_DECLARATION": self._fix_pdfua,
        }
        handler = handlers.get(rule_id)
        if handler is None:
            return self._result(
                rule_id, False, "no_handler",
                error=f"DocumentRemediatorAgent: unsupported rule '{rule_id}'",
            )
        return handler(rule_id, context)

    # ------------------------------------------------------------------
    # DOC_HAS_TITLE
    # ------------------------------------------------------------------

    def _fix_title(self, rule_id: str, context: dict[str, Any]) -> RemediationResult:
        """
        Set the document title in both the Info dictionary and the XMP stream.

        Why both?
            Adobe Acrobat's Accessibility Checker "Title" test reads from the
            XMP metadata stream (``dc:title``).  PDFix ``SetInfo("Title", v)``
            updates the Info dictionary (/Title key in the trailer dict), which
            may not automatically synchronise with the XMP stream depending on
            SDK version.  We therefore:
              1. Call ``SetInfo("Title", title)`` – Info dictionary.
              2. Call ``SetMetadata(xmp_bytes)`` – patch ``dc:title`` in the
                 raw XMP XML so Acrobat's checker definitely sees the value.

            If XMP patching fails we still return success (Info dict was set)
            but include a warning so the caller knows Acrobat may still flag it.
        """
        pdf_doc = context.get("pdf_doc")
        if pdf_doc is None:
            return self._result(rule_id, False, "fix_title", error="pdf_doc not in context")

        try:
            changes: list[str] = []

            # ── 1. Info dictionary ────────────────────────────────────
            current_title = (pdf_doc.GetInfo("Title") or "").strip()
            if current_title:
                # Info /Title already set — keep it, still patch XMP
                title = current_title
                changes.append(f"Info /Title already set to '{title}'")
            else:
                # Derive title from document filename or fall back
                raw_name = context.get("document_name") or ""
                title = (
                    raw_name.rsplit(".", 1)[0].replace("_", " ").replace("-", " ").strip()
                    or "Untitled Document"
                )
                pdf_doc.SetInfo("Title", title)
                changes.append(f"Set Info /Title → '{title}'")

            # ── 2. XMP metadata stream — ALWAYS patch, even if Info dict was set ──
            # Adobe Acrobat's Title check reads dc:title from XMP, not the Info dict.
            xmp_warning = _patch_xmp_title(pdf_doc, title)
            if xmp_warning:
                changes.append(f"XMP dc:title warning: {xmp_warning}")
            else:
                changes.append(f"Patched XMP dc:title → '{title}'")

            # ── 3. DisplayDocTitle — handled by pipeline pypdf post-processing ──
            dt_note = _set_display_doc_title(pdf_doc)
            changes.append(f"DisplayDocTitle: {dt_note or 'will be set by pipeline pypdf step'}")

            return self._result(rule_id, True, "fix_title", changes_made=changes)

        except Exception as exc:
            logger.exception("DOC_HAS_TITLE remediation failed")
            return self._result(rule_id, False, "fix_title", error=str(exc))

    # ------------------------------------------------------------------
    # DOC_HAS_LANGUAGE
    # ------------------------------------------------------------------

    def _fix_language(self, rule_id: str, context: dict[str, Any]) -> RemediationResult:
        """Set document language to the default locale when none is present."""
        pdf_doc = context.get("pdf_doc")
        if pdf_doc is None:
            return self._result(rule_id, False, "fix_language", error="pdf_doc not in context")

        try:
            current_lang = pdf_doc.GetLang()
            if current_lang and current_lang.strip():
                return self._result(
                    rule_id, True, "fix_language",
                    changes_made=[f"Language already set to '{current_lang}' – no change needed"],
                )

            pdf_doc.SetLang(self.DEFAULT_LANGUAGE)
            return self._result(
                rule_id, True, "fix_language",
                changes_made=[f"Set document language to '{self.DEFAULT_LANGUAGE}'"],
            )
        except Exception as exc:
            logger.exception("DOC_HAS_LANGUAGE remediation failed")
            return self._result(rule_id, False, "fix_language", error=str(exc))

    # ------------------------------------------------------------------
    # DOC_HAS_METADATA
    # ------------------------------------------------------------------

    def _fix_metadata(self, rule_id: str, context: dict[str, Any]) -> RemediationResult:
        """Fill any missing standard document info fields (Title, Author, Subject)."""
        pdf_doc = context.get("pdf_doc")
        if pdf_doc is None:
            return self._result(rule_id, False, "fix_metadata", error="pdf_doc not in context")

        changes: list[str] = []
        try:
            # Title → prefer document_name from context, fall back to generic value
            if not (pdf_doc.GetInfo("Title") or "").strip():
                title = context.get("document_name") or "Untitled Document"
                pdf_doc.SetInfo("Title", title)
                changes.append(f"Set Title → '{title}'")

            if not (pdf_doc.GetInfo("Author") or "").strip():
                pdf_doc.SetInfo("Author", "Unknown Author")
                changes.append("Set Author → 'Unknown Author'")

            if not (pdf_doc.GetInfo("Subject") or "").strip():
                pdf_doc.SetInfo("Subject", "PDF Document")
                changes.append("Set Subject → 'PDF Document'")

            if not changes:
                return self._result(
                    rule_id, True, "fix_metadata",
                    changes_made=["All metadata fields already populated – no change needed"],
                )
            return self._result(rule_id, True, "fix_metadata", changes_made=changes)

        except Exception as exc:
            logger.exception("DOC_HAS_METADATA remediation failed")
            return self._result(rule_id, False, "fix_metadata", changes_made=changes, error=str(exc))

    # ------------------------------------------------------------------
    # DOC_IS_TAGGED
    # ------------------------------------------------------------------

    def _fix_tagging(self, rule_id: str, context: dict[str, Any]) -> RemediationResult:
        """Auto-tag the document using PDFix ``AddTags`` when no structure tree exists."""
        pdf_doc = context.get("pdf_doc")
        if pdf_doc is None:
            return self._result(rule_id, False, "fix_tagging", error="pdf_doc not in context")

        try:
            # Guard: skip if already tagged
            struct_tree = pdf_doc.GetStructTree()
            if struct_tree:
                return self._result(
                    rule_id, True, "fix_tagging",
                    changes_made=["Document already has a structure tree – no tagging needed"],
                )

            from pdfixsdk.Pdfix import PdfTagsParams  # type: ignore[import]

            tag_params = PdfTagsParams()
            success = bool(pdf_doc.AddTags(tag_params))

            if not success:
                return self._result(
                    rule_id, False, "fix_tagging",
                    error="PDFix AddTags() returned False – document may be encrypted or corrupt",
                )

            # Invalidate all structure-based caches so re-validation re-traverses
            self._invalidate_cache(
                context,
                "headings_by_pdf",
                "images_by_pdf",
                "tables_by_pdf",
                "tree_structure_by_pdf",
                "reading_order_document_mode",
            )

            return self._result(
                rule_id, True, "fix_tagging",
                changes_made=["Applied automatic PDF structure tagging via PDFix AddTags()"],
            )

        except ImportError:
            return self._result(
                rule_id, False, "fix_tagging",
                error="pdfixsdk not installed – cannot add tags",
            )
        except Exception as exc:
            logger.exception("DOC_IS_TAGGED remediation failed")
            return self._result(rule_id, False, "fix_tagging", error=str(exc))

    # ------------------------------------------------------------------
    # DOC_PDFUA_DECLARATION
    # ------------------------------------------------------------------

    def _fix_pdfua(self, rule_id: str, context: dict[str, Any]) -> RemediationResult:
        """Enable the PDF/UA compliance flag in the document standard field."""
        pdf_doc = context.get("pdf_doc")
        if pdf_doc is None:
            return self._result(rule_id, False, "fix_pdfua", error="pdf_doc not in context")

        try:
            from pdfixsdk.Pdfix import kPdfStandardPdfUA  # type: ignore[import]

            current_standard = pdf_doc.GetPdfStandard()
            if current_standard & kPdfStandardPdfUA:
                return self._result(
                    rule_id, True, "fix_pdfua",
                    changes_made=["PDF/UA flag already set – no change needed"],
                )

            pdf_doc.SetPdfStandard(current_standard | kPdfStandardPdfUA)
            return self._result(
                rule_id, True, "fix_pdfua",
                changes_made=["Enabled PDF/UA compliance flag (XMP metadata + PDF standard field)"],
            )

        except ImportError:
            return self._result(
                rule_id, False, "fix_pdfua",
                error="pdfixsdk not installed – cannot set PDF/UA flag",
            )
        except Exception as exc:
            logger.exception("DOC_PDFUA_DECLARATION remediation failed")
            return self._result(rule_id, False, "fix_pdfua", error=str(exc))


# ---------------------------------------------------------------------------
# Module-level XMP helper
# ---------------------------------------------------------------------------

def _patch_xmp_title(pdf_doc: Any, title: str) -> str | None:
    """
    Inject or replace ``dc:title`` in the document's XMP metadata stream.

    Adobe Acrobat reads the title from XMP (``dc:title`` / ``rdf:Alt`` /
    ``rdf:li`` structure), not from the Info dictionary, for its accessibility
    "Title" check.

    Strategy:
        1. Read existing XMP via ``pdf_doc.GetMetadata()``.
        2. If the stream already contains ``<dc:title>``, replace its inner
           ``rdf:li`` text; otherwise insert a minimal ``<dc:title>`` block
           immediately before the closing ``</rdf:Description>`` tag.
        3. Write back via ``pdf_doc.SetMetadata(new_xmp_bytes)``.

    Returns:
        None on success, or a short warning string if XMP could not be patched
        (the Info dictionary fix already applied, so this is non-fatal).
    """
    import re as _re

    try:
        # Read existing XMP bytes
        xmp_bytes: bytes | None = None
        if hasattr(pdf_doc, "GetMetadata"):
            raw = pdf_doc.GetMetadata()
            if isinstance(raw, (bytes, bytearray)):
                xmp_bytes = bytes(raw)
            elif isinstance(raw, str):
                xmp_bytes = raw.encode("utf-8")

        if not xmp_bytes:
            # No existing XMP – build a minimal packet from scratch
            xmp_bytes = _minimal_xmp_packet(title)
            if hasattr(pdf_doc, "SetMetadata"):
                pdf_doc.SetMetadata(xmp_bytes)
            return None

        xmp_str = xmp_bytes.decode("utf-8", errors="replace")

        escaped_title = (
            title
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

        dc_title_block = (
            f'<dc:title><rdf:Alt><rdf:li xml:lang="x-default">'
            f'{escaped_title}</rdf:li></rdf:Alt></dc:title>'
        )

        if "<dc:title>" in xmp_str:
            # Replace existing dc:title block (handles both inline and multiline)
            xmp_str = _re.sub(
                r"<dc:title>.*?</dc:title>",
                dc_title_block,
                xmp_str,
                flags=_re.DOTALL,
            )
        elif "</rdf:Description>" in xmp_str:
            # Strategy 2: open/close rdf:Description — insert dc:title before closing tag
            xmp_str = xmp_str.replace(
                "</rdf:Description>",
                f"  {dc_title_block}\n</rdf:Description>",
                1,
            )
        elif "</rdf:RDF>" in xmp_str:
            # Strategy 3: self-closing <rdf:Description ... /> — no closing tag to find.
            # Inject a brand-new rdf:Description block before </rdf:RDF>.
            new_desc = (
                '\n<rdf:Description rdf:about=""'
                ' xmlns:dc="http://purl.org/dc/elements/1.1/">'
                f'\n  {dc_title_block}'
                '\n</rdf:Description>\n'
            )
            xmp_str = xmp_str.replace("</rdf:RDF>", f"{new_desc}</rdf:RDF>", 1)
        else:
            # Strategy 4: XMP is so malformed we can't find any anchor — rebuild
            xmp_str = _minimal_xmp_packet(title).decode("utf-8")

        new_xmp_bytes = xmp_str.encode("utf-8")
        if hasattr(pdf_doc, "SetMetadata"):
            pdf_doc.SetMetadata(new_xmp_bytes)
            return None
        else:
            return "pdf_doc.SetMetadata() not available – XMP not updated"

    except Exception as exc:
        return f"XMP patch failed ({exc}); Info /Title was still set"


def _minimal_xmp_packet(title: str) -> bytes:
    """Return a bare-minimum XMP packet containing dc:title."""
    escaped = (
        title
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    packet = (
        '<?xpacket begin="\xef\xbb\xbf" id="W5M0MpCehiHzreSzNTczkc9d"?>'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f'<dc:title><rdf:Alt><rdf:li xml:lang="x-default">{escaped}</rdf:li></rdf:Alt></dc:title>'
        '</rdf:Description>'
        '</rdf:RDF>'
        '</x:xmpmeta>'
        '<?xpacket end="w"?>'
    )
    return packet.encode("utf-8")

def _set_display_doc_title(pdf_doc: Any) -> str | None:
    """
    Attempt to set /ViewerPreferences /DisplayDocTitle via PDFix SDK.

    PDFix SDK 9.0.0 has no Python constant for this preference, so this
    function always returns a note — the pipeline applies the fix via
    pypdf AFTER saving (``_apply_display_doc_title`` in the pipeline).
    """
    # PDFix 9.0.0: dir(Pdfix) yields [] for 'viewer'/'display' constants.
    return "will be set by pipeline pypdf post-save step"
