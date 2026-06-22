from __future__ import annotations
import io as _io
import os as _os
import sys as _sys
import tempfile as _tempfile
from dataclasses import asdict
from pathlib import Path
from time import perf_counter

from src.core.logger import get_logger
from .accesibility_engine_pipeline import AccessibilityEnginePipeline
from .remediator.remediator_service import RemediatorService
from .remediator.base_remediator_agent import RemediationResult
from .font_encoding_fixer import inject_tounicode
from pypdf import PdfWriter
from pypdf.generic import BooleanObject, DictionaryObject, NameObject, DecodedStreamObject

logger = get_logger(__name__)

_DEBUG_LOG = Path(__file__).parent.parent.parent.parent.parent / "pipeline_debug.log"

def _dlog(*args):
    msg = " ".join(str(a) for a in args)
    try:
        with open(_DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass
    print(msg, file=_sys.stderr, flush=True)

_dlog(f"[PIPELINE] MODULE LOADED — debug log at {_DEBUG_LOG}")


class AccessibilityRemediationPipeline:

    def __init__(self) -> None:
        _dlog("[PIPELINE] __init__ called")
        self.validator_pipeline = AccessibilityEnginePipeline()
        self._remediator_service = RemediatorService()
        _dlog("[PIPELINE] __init__ done")

    def run(self, organization_id, project_id, context):
        _dlog("[PIPELINE] run() CALLED")
        start = perf_counter()
        context.setdefault("_cache", {})

        pdf_path = context.get("pdf_doc_path") or context.get("document_name") or "unknown"
        _dlog(f"[PIPELINE] doc={pdf_path}")
        logger.info("Remediation pipeline started | org=%s project=%s doc=%s", organization_id, project_id, pdf_path)

        _dlog("[PIPELINE] starting initial validation ...")
        validation_result = self.validator_pipeline.run(
            organization_id=organization_id,
            project_id=project_id,
            context=context,
        )
        _dlog(f"[PIPELINE] initial validation done | total_issues={validation_result.get('total_issues', 0)}")

        auto_fixable_issues = [
            issue for issue in validation_result.get("issues", [])
            if issue.get("auto_fixable") and issue.get("status") != "PASS"
        ]
        _dlog(f"[PIPELINE] auto_fixable_issues={len(auto_fixable_issues)}")

        remediation_results = []
        issues_fixed = 0
        issues_failed = 0

        for i, issue in enumerate(auto_fixable_issues):
            _dlog(f"[PIPELINE] remediating {i+1}/{len(auto_fixable_issues)}: {issue.get('rule_id')}")
            result = self._remediator_service.remediate(issue, context)
            remediation_results.append(asdict(result))
            if result.success:
                issues_fixed += 1
                _dlog(f"[PIPELINE]   -> FIXED")
            else:
                issues_failed += 1
                _dlog(f"[PIPELINE]   -> FAILED: {result.error}")

        _dlog(f"[PIPELINE] remediation done: fixed={issues_fixed} failed={issues_failed}")
        _dlog("[PIPELINE] calling _save_remediated_pdf ...")

        remediated_pdf_path, save_success, font_stats = _save_remediated_pdf(context)
        _dlog(f"[PIPELINE] _save_remediated_pdf -> path={remediated_pdf_path} success={save_success} font_stats={font_stats}")

        context["_cache"] = {}
        _dlog("[PIPELINE] re-validating ...")

        revalidation_result = self.validator_pipeline.run(
            organization_id=organization_id,
            project_id=project_id,
            context=context,
        )
        _dlog(f"[PIPELINE] revalidation done | total_issues={revalidation_result.get('total_issues', 0)}")

        elapsed_ms = int((perf_counter() - start) * 1000)
        _dlog(f"[PIPELINE] COMPLETE in {elapsed_ms}ms")

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
                "font_encoding": font_stats,
            },
        }

    def _remediate_issue(self, issue, context):
        return self._remediator_service.remediate(issue, context)


def _save_remediated_pdf(context):
    _dlog("[PIPELINE] _save_remediated_pdf() ENTERED")

    pdf_doc = context.get("pdf_doc")
    _dlog(f"[PIPELINE]   pdf_doc={pdf_doc}")
    if pdf_doc is None:
        _dlog("[PIPELINE]   ERROR: pdf_doc is None")
        return None, False, {}

    original_path = context.get("pdf_doc_path") or ""
    _dlog(f"[PIPELINE]   original_path={original_path}")
    if not original_path:
        _dlog("[PIPELINE]   ERROR: original_path empty")
        return None, False, {}

    try:
        _dlog("[PIPELINE]   importing kSaveFull ...")
        from pdfixsdk.Pdfix import kSaveFull
        _dlog("[PIPELINE]   kSaveFull imported OK")

        p = Path(original_path)
        remediated_path = p.parent / f"{p.stem}_remediated{p.suffix}"
        _dlog(f"[PIPELINE]   remediated_path={remediated_path}")

        tmp_fd, tmp_path = _tempfile.mkstemp(suffix=".pdf", dir=p.parent)
        _os.close(tmp_fd)
        _dlog(f"[PIPELINE]   tmp_path={tmp_path}")

        try:
            _dlog("[PIPELINE]   calling pdf_doc.Save() ...")
            ok = pdf_doc.Save(tmp_path, kSaveFull)
            _dlog(f"[PIPELINE]   pdf_doc.Save() returned {ok}")
            if not ok:
                _dlog("[PIPELINE]   ERROR: Save returned False")
                return None, False, {}

            tmp_size = _os.path.getsize(tmp_path)
            _dlog(f"[PIPELINE]   tmp file size={tmp_size} bytes")

            import subprocess as _subp, shutil as _sh
            _fixer = str(Path(__file__).parent / "font_encoding_fixer.py")
            _copy_path = tmp_path + "_copy.pdf"
            _dlog(f"[PIPELINE]   copying {tmp_path!r} -> {_copy_path!r}")
            _sh.copy2(tmp_path, _copy_path)
            _dlog(f"[PIPELINE]   running font_encoding_fixer ...")
            _proc = _subp.run(
                [_sys.executable, _fixer, _copy_path, str(remediated_path)],
                capture_output=True, text=True, timeout=120
            )
            _dlog(f"[PIPELINE]   subprocess returncode={_proc.returncode}")
            _dlog(f"[PIPELINE]   subprocess stdout={_proc.stdout.strip()!r}")
            if _proc.stderr.strip():
                _dlog(f"[PIPELINE]   subprocess stderr={_proc.stderr.strip()!r}")
            try:
                _os.unlink(_copy_path)
            except Exception:
                pass
            if _proc.returncode == 0 and _os.path.exists(str(remediated_path)):
                tu = {"fonts_patched": "see stdout", "save_success": True}
                _dlog("[PIPELINE]   encoding fix applied successfully")
            else:
                _dlog("[PIPELINE]   fixer failed — copying original")
                _sh.copy2(tmp_path, str(remediated_path))
                tu = {"fonts_patched": 0, "save_success": True}

        finally:
            try:
                _os.unlink(tmp_path)
                _dlog("[PIPELINE]   temp deleted")
            except OSError as e:
                _dlog(f"[PIPELINE]   WARNING: could not delete temp: {e}")

        # Step 1 — set DisplayDocTitle + inject PDF/UA identifier + dc:title
        _dlog("[PIPELINE]   calling _set_display_doc_title ...")
        _set_display_doc_title(str(remediated_path))
        _dlog("[PIPELINE]   _set_display_doc_title done")

        # Step 2 — embed font programs (pikepdf+fonttools, tag-safe)
        _dlog("[PIPELINE]   calling embed_standard_fonts ...")
        try:
            from .font_encoding_fixer import embed_standard_fonts
            fonts_ok = embed_standard_fonts(str(remediated_path))
            _dlog(f"[PIPELINE]   embed_standard_fonts -> {fonts_ok}")
        except Exception as fe:
            _dlog(f"[PIPELINE]   embed_standard_fonts ERROR: {fe}")

        # Step 3 — fix low-contrast text colours (WCAG 1.4.3)
        _dlog("[PIPELINE]   calling fix_text_contrast ...")
        try:
            from .contrast_fixer import fix_text_contrast
            contrast_stats = fix_text_contrast(str(remediated_path))
            _dlog(f"[PIPELINE]   fix_text_contrast -> changes={contrast_stats['total_changes']}")
        except Exception as ce:
            import traceback
            _dlog(f"[PIPELINE]   fix_text_contrast ERROR: {ce}")
            _dlog(traceback.format_exc())
        final_size = _os.path.getsize(str(remediated_path)) if _os.path.exists(str(remediated_path)) else "MISSING"
        _dlog(f"[PIPELINE]   final file size={final_size}")

        context["_remediated_pdf_path"] = str(remediated_path)
        _dlog(f"[PIPELINE] SUCCESS -> {remediated_path}")
        return str(remediated_path), True, tu

    except ImportError as e:
        _dlog(f"[PIPELINE]   ImportError: {e}")
        return None, False, {}
    except Exception as e:
        import traceback
        _dlog(f"[PIPELINE]   EXCEPTION {type(e).__name__}: {e}")
        _dlog(traceback.format_exc())
        return None, False, {}


def _set_display_doc_title(pdf_path: str) -> None:
    """Set DisplayDocTitle, inject PDF/UA-1 identifier and dc:title into XMP."""
    _dlog(f"[PIPELINE] _set_display_doc_title: {pdf_path}")
    try:
        pdf_bytes = Path(pdf_path).read_bytes()
        writer = PdfWriter(clone_from=_io.BytesIO(pdf_bytes))
        root = writer._root_object

        # DisplayDocTitle
        vp_key = NameObject("/ViewerPreferences")
        if vp_key not in root:
            root[vp_key] = DictionaryObject()
        root[vp_key][NameObject("/DisplayDocTitle")] = BooleanObject(True)

        # Resolve document title: DocInfo /Title → filename fallback
        doc_title = "Untitled Document"
        try:
            info = writer.metadata
            if info and info.get("/Title"):
                doc_title = str(info["/Title"])
            else:
                doc_title = Path(pdf_path).stem.replace("_", " ").replace("-", " ")
        except Exception:
            pass

        # Inject XMP with PDF/UA-1 identifier + dc:title
        xmp_data = (
            "<?xpacket begin='\xef\xbb\xbf' id='W5M0MpCehiHzreSzNTczkc9d'?>\n"
            "<x:xmpmeta xmlns:x='adobe:ns:meta/'>\n"
            "  <rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>\n"
            "    <rdf:Description rdf:about=''\n"
            "        xmlns:pdfuaid='http://www.aiim.org/pdfua/ns/id/'>\n"
            "      <pdfuaid:part>1</pdfuaid:part>\n"
            "    </rdf:Description>\n"
            "    <rdf:Description rdf:about=''\n"
            "        xmlns:dc='http://purl.org/dc/elements/1.1/'>\n"
            "      <dc:title>\n"
            "        <rdf:Alt>\n"
            f"          <rdf:li xml:lang='x-default'>{doc_title}</rdf:li>\n"
            "        </rdf:Alt>\n"
            "      </dc:title>\n"
            "    </rdf:Description>\n"
            "  </rdf:RDF>\n"
            "</x:xmpmeta>\n"
            "<?xpacket end='w'?>"
        )
        xmp_stream = DecodedStreamObject()
        xmp_stream.set_data(xmp_data.encode("utf-8"))
        xmp_stream.update({
            NameObject("/Type"):    NameObject("/Metadata"),
            NameObject("/Subtype"): NameObject("/XML"),
        })
        root[NameObject("/Metadata")] = writer._add_object(xmp_stream)

        with open(pdf_path, "wb") as fh:
            writer.write(fh)
        _dlog("[PIPELINE] _set_display_doc_title: done")
    except Exception as e:
        import traceback
        _dlog(f"[PIPELINE] _set_display_doc_title EXCEPTION: {e}")
        _dlog(traceback.format_exc())
