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

        # Only attempt issues that are auto-fixable AND actually failing
        auto_fixable_issues = [
            issue for issue in validation_result.get("issues", [])
            if issue.get("auto_fixable") and issue.get("status") == "FAIL"
        ]
        _dlog(f"[PIPELINE] auto_fixable_issues (FAIL only)={len(auto_fixable_issues)}")

        # Count initial FAILs for accurate issues_detected reporting
        initial_fail_count = sum(
            1 for issue in validation_result.get("issues", [])
            if issue.get("status") == "FAIL"
        )

        remediation_results = []
        issues_fixed = 0
        issues_failed = 0

        # Track which rules were "scheduled" (fix deferred to post-processing)
        # These must be reconciled against actual subprocess outcomes later.
        scheduled_rules: set[str] = set()

        for i, issue in enumerate(auto_fixable_issues):
            _dlog(f"[PIPELINE] remediating {i+1}/{len(auto_fixable_issues)}: {issue.get('rule_id')}")
            result = self._remediator_service.remediate(issue, context)
            remediation_results.append(asdict(result))
            if result.success:
                # If the action is a "schedule_*" action, defer the success verdict
                # until post-processing confirms the subprocess succeeded.
                if result.action and result.action.startswith("schedule_"):
                    scheduled_rules.add(result.rule_id)
                    _dlog(f"[PIPELINE]   -> SCHEDULED (pending post-processing)")
                else:
                    issues_fixed += 1
                    _dlog(f"[PIPELINE]   -> FIXED")
            else:
                issues_failed += 1
                _dlog(f"[PIPELINE]   -> FAILED: {result.error}")

        _dlog(f"[PIPELINE] pre-save counts: fixed={issues_fixed} scheduled={len(scheduled_rules)} failed={issues_failed}")
        _dlog("[PIPELINE] calling _save_remediated_pdf ...")

        # _save_remediated_pdf now returns a 4-tuple; the last element is a dict
        # mapping rule_id → bool for each scheduled fix that ran as a subprocess.
        remediated_pdf_path, save_success, font_stats, scheduled_outcomes = _save_remediated_pdf(context)
        _dlog(f"[PIPELINE] _save_remediated_pdf -> path={remediated_pdf_path} success={save_success} "
              f"font_stats={font_stats} scheduled_outcomes={scheduled_outcomes}")

        # Reconcile scheduled fixes against actual subprocess outcomes
        for rem_result in remediation_results:
            rule_id = rem_result.get("rule_id", "")
            if rule_id not in scheduled_rules:
                continue
            actual_success = scheduled_outcomes.get(rule_id, False)
            if actual_success:
                issues_fixed += 1
                rem_result["changes_made"] = rem_result.get("changes_made", []) + [
                    "Post-processing step completed successfully."
                ]
                _dlog(f"[PIPELINE]   scheduled fix {rule_id} -> confirmed FIXED")
            else:
                issues_failed += 1
                rem_result["success"] = False
                rem_result["error"] = (
                    rem_result.get("error")
                    or "Post-processing subprocess did not complete successfully."
                )
                _dlog(f"[PIPELINE]   scheduled fix {rule_id} -> confirmed FAILED")

        _dlog(f"[PIPELINE] final counts: fixed={issues_fixed} failed={issues_failed}")

        context["_cache"] = {}
        _dlog("[PIPELINE] re-validating ...")

        revalidation_result = self.validator_pipeline.run(
            organization_id=organization_id,
            project_id=project_id,
            context=context,
        )
        _dlog(f"[PIPELINE] revalidation done | total_issues={revalidation_result.get('total_issues', 0)}")

        # Compute accurate remaining-failures count from revalidation
        revalidation_fail_count = sum(
            1 for issue in revalidation_result.get("issues", [])
            if issue.get("status") == "FAIL"
        )

        elapsed_ms = int((perf_counter() - start) * 1000)
        _dlog(f"[PIPELINE] COMPLETE in {elapsed_ms}ms")

        return {
            "validation_result": validation_result,
            "remediation_results": remediation_results,
            "revalidation_result": revalidation_result,
            "remediated_pdf_path": remediated_pdf_path,
            "summary": {
                # ── Attempt-level stats (covers only auto-fixable FAILs attempted) ──
                "issues_attempted": len(auto_fixable_issues),
                "issues_fixed": issues_fixed,
                "issues_failed": issues_failed,
                # ── Document-level stats (comparable between pre and post) ──
                # issues_detected  = number of FAIL rules before remediation
                # issues_remaining = number of FAIL rules after remediation
                "issues_detected": initial_fail_count,
                "issues_remaining": revalidation_fail_count,
                # ── Infrastructure ──
                "save_success": save_success,
                "total_duration_ms": elapsed_ms,
                "font_encoding": font_stats,
            },
        }

    def _remediate_issue(self, issue, context):
        return self._remediator_service.remediate(issue, context)


def _save_remediated_pdf(context):
    """Save remediated PDF and run all post-processing fixers.

    Returns:
        (remediated_path | None, save_success, font_stats, scheduled_outcomes)

        scheduled_outcomes maps rule_id → bool for each fix that ran
        as a subprocess (HDR-001 for heading fix, LINK-001 for link fix).
    """
    _dlog("[PIPELINE] _save_remediated_pdf() ENTERED")

    pdf_doc = context.get("pdf_doc")
    _dlog(f"[PIPELINE]   pdf_doc={pdf_doc}")
    if pdf_doc is None:
        _dlog("[PIPELINE]   ERROR: pdf_doc is None")
        return None, False, {}, {}

    original_path = context.get("pdf_doc_path") or ""
    _dlog(f"[PIPELINE]   original_path={original_path}")
    if not original_path:
        _dlog("[PIPELINE]   ERROR: original_path empty")
        return None, False, {}, {}

    scheduled_outcomes: dict[str, bool] = {}

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
                return None, False, {}, {}

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

            # ── Parse actual fonts_patched count from subprocess stdout ──────
            fonts_patched_count = 0
            if _proc.returncode == 0 and _os.path.exists(str(remediated_path)):
                for line in _proc.stdout.splitlines():
                    # The fixer prints lines like "Patched N fonts" or "fonts_patched=N"
                    import re as _re
                    m = _re.search(r"(?:patched|fonts_patched)[=:\s]+(\d+)", line, _re.IGNORECASE)
                    if m:
                        fonts_patched_count = int(m.group(1))
                        break
                tu = {"fonts_patched": fonts_patched_count, "save_success": True}
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

        # Step 4 — fix missing Link annotations + <Link> structure elements (PDF/UA)
        _dlog("[PIPELINE]   calling run_link_fix.py ...")
        try:
            _link_runner = str(Path(__file__).parent / "run_link_fix.py")
            _link_proc = _subp.run(
                [_sys.executable, _link_runner, str(remediated_path)],
                capture_output=True, text=True, timeout=60
            )
            _dlog(f"[PIPELINE]   run_link_fix returncode={_link_proc.returncode}")
            _dlog(f"[PIPELINE]   run_link_fix stdout={_link_proc.stdout.strip()!r}")
            if _link_proc.stderr.strip():
                _dlog(f"[PIPELINE]   run_link_fix stderr={_link_proc.stderr.strip()!r}")
            # Record actual outcome for LINK-001 scheduled fix
            scheduled_outcomes["LINK-001"] = (_link_proc.returncode == 0)
        except Exception as le:
            import traceback
            _dlog(f"[PIPELINE]   run_link_fix ERROR: {le}")
            _dlog(traceback.format_exc())
            scheduled_outcomes["LINK-001"] = False

        # Step 5 — fix wrongly-artifacted content (PDF/UA)
        _dlog("[PIPELINE]   calling run_artifact_fix.py ...")
        try:
            _artifact_runner = str(Path(__file__).parent / "run_artifact_fix.py")
            _artifact_proc = _subp.run(
                [_sys.executable, _artifact_runner, str(remediated_path)],
                capture_output=True, text=True, timeout=60
            )
            _dlog(f"[PIPELINE]   run_artifact_fix returncode={_artifact_proc.returncode}")
            _dlog(f"[PIPELINE]   run_artifact_fix stdout={_artifact_proc.stdout.strip()!r}")
            if _artifact_proc.stderr.strip():
                _dlog(f"[PIPELINE]   run_artifact_fix stderr={_artifact_proc.stderr.strip()!r}")
        except Exception as ae:
            import traceback
            _dlog(f"[PIPELINE]   run_artifact_fix ERROR: {ae}")
            _dlog(traceback.format_exc())

        # Step 6 — fix heading tags (PDF/UA Presence of headings)
        _dlog("[PIPELINE]   calling run_heading_fix.py ...")
        try:
            _heading_runner = str(Path(__file__).parent / "run_heading_fix.py")
            _heading_proc = _subp.run(
                [_sys.executable, _heading_runner, str(remediated_path)],
                capture_output=True, text=True, timeout=60
            )
            _dlog(f"[PIPELINE]   run_heading_fix returncode={_heading_proc.returncode}")
            _dlog(f"[PIPELINE]   run_heading_fix stdout={_heading_proc.stdout.strip()!r}")
            if _heading_proc.stderr.strip():
                _dlog(f"[PIPELINE]   run_heading_fix stderr={_heading_proc.stderr.strip()!r}")
            # Record actual outcome for HDR-001 scheduled fix
            scheduled_outcomes["HDR-001"] = (_heading_proc.returncode == 0)
        except Exception as he:
            import traceback
            _dlog(f"[PIPELINE]   run_heading_fix ERROR: {he}")
            _dlog(traceback.format_exc())
            scheduled_outcomes["HDR-001"] = False

        final_size = _os.path.getsize(str(remediated_path)) if _os.path.exists(str(remediated_path)) else "MISSING"
        _dlog(f"[PIPELINE]   final file size={final_size}")

        context["_remediated_pdf_path"] = str(remediated_path)
        _dlog(f"[PIPELINE] SUCCESS -> {remediated_path}")
        return str(remediated_path), True, tu, scheduled_outcomes

    except ImportError as e:
        _dlog(f"[PIPELINE]   ImportError: {e}")
        return None, False, {}, {}
    except Exception as e:
        import traceback
        _dlog(f"[PIPELINE]   EXCEPTION {type(e).__name__}: {e}")
        _dlog(traceback.format_exc())
        return None, False, {}, {}


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
