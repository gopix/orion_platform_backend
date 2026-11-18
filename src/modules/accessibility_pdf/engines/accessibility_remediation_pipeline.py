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

        # ── Update pdf_doc_path so pdfplumber-based validators (heading, link)
        # read from the REMEDIATED file during revalidation, not the original upload.
        # This ensures post-processing fixes (heading tags, link annotations) are
        # visible in the revalidation results.
        if remediated_pdf_path and _os.path.exists(remediated_pdf_path):
            context["pdf_doc_path"] = remediated_pdf_path
            _dlog(f"[PIPELINE] revalidation path updated -> {remediated_pdf_path}")
            # Reopen PDFix doc from the remediated file so in-memory validators
            # (heading structure, link annotations) see post-processed changes.
            try:
                from pdfixsdk.Pdfix import GetPdfix  # type: ignore[import]
                _pdfix_inst = GetPdfix()
                if _pdfix_inst is not None:
                    _old_doc = context.get("pdf_doc")
                    _new_doc = _pdfix_inst.OpenDoc(remediated_pdf_path, "")
                    if _new_doc is not None:
                        context["pdf_doc"] = _new_doc
                        if hasattr(_new_doc, "GetNumPages"):
                            context["total_pages"] = _new_doc.GetNumPages()
                        _dlog("[PIPELINE] PDFix doc reopened from remediated file for revalidation")
                        if _old_doc is not None:
                            try:
                                _old_doc.Close()
                            except Exception:
                                pass
                    else:
                        _dlog("[PIPELINE] WARNING: OpenDoc returned None — keeping original doc")
            except ImportError:
                _dlog("[PIPELINE] WARNING: pdfixsdk not available — keeping original doc")
            except Exception as _reopen_exc:
                _dlog(f"[PIPELINE] WARNING: could not reopen PDFix doc: {_reopen_exc}")

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
                # ── Document-level stats (all FAILs, not just auto-fixable ones) ──
                # initial_issues_found = ALL FAIL rules detected before remediation
                # issues_remaining     = ALL FAIL rules still present after remediation
                # NOTE: result_summary.issues_detected counts only auto-fixable FAILs
                #       (i.e. what Orion was responsible for fixing) — different scope.
                "initial_issues_found": initial_fail_count,
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
        as a subprocess (HDR-001 heading fix, LINK-001 link fix,\n        COLOR-001/COLOR-002 contrast fix).
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
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120
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

        # Confirm DOC_PDFUA_DECLARATION outcome: _set_display_doc_title already
        # injected pdfuaid:part=1 into the XMP — verify it landed in the file.
        if context.get("_pdfua_fix_scheduled"):
            try:
                _pdf_bytes_check = Path(str(remediated_path)).read_bytes()
                _pdfua_ok = b"pdfuaid:part" in _pdf_bytes_check
                scheduled_outcomes["DOC_PDFUA_DECLARATION"] = _pdfua_ok
                _dlog(f"[PIPELINE]   DOC_PDFUA_DECLARATION XMP verify -> {_pdfua_ok}")
            except Exception as _pdfua_exc:
                scheduled_outcomes["DOC_PDFUA_DECLARATION"] = False
                _dlog(f"[PIPELINE]   DOC_PDFUA_DECLARATION XMP verify FAILED: {_pdfua_exc}")

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
        _contrast_ok = False
        try:
            from .contrast_fixer import fix_text_contrast
            contrast_stats = fix_text_contrast(
                str(remediated_path),
                known_text_colors=context.get("_contrast_known_text_colors"),
            )
            _dlog(f"[PIPELINE]   fix_text_contrast -> changes={contrast_stats['total_changes']}")
            _contrast_ok = True
        except Exception as ce:
            import traceback
            _dlog(f"[PIPELINE]   fix_text_contrast ERROR: {ce}")
            _dlog(traceback.format_exc())
        # Record actual outcome for COLOR-001 / COLOR-002 scheduled fixes
        # (scheduled by ColorRemediatorAgent via context flag).
        if context.get("_contrast_fix_scheduled"):
            scheduled_outcomes["COLOR-001"] = _contrast_ok
            scheduled_outcomes["COLOR-002"] = _contrast_ok
            _dlog(f"[PIPELINE]   COLOR-001/COLOR-002 scheduled outcome -> {_contrast_ok}")

        # Step 4 — fix missing Link annotations + <Link> structure elements (PDF/UA)
        _dlog("[PIPELINE]   calling run_link_fix.py ...")
        try:
            _link_runner = str(Path(__file__).parent / "run_link_fix.py")
            _link_proc = _subp.run(
                [_sys.executable, _link_runner, str(remediated_path)],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60
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
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60
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
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60
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

        # Step 7 — fix invalid heading parent types (HDR-005 / PAC "Invalid use of Hn")
        _dlog("[PIPELINE]   calling run_heading_parent_fix.py ...")
        try:
            _hpfix_runner = str(Path(__file__).parent / "run_heading_parent_fix.py")
            _hpfix_proc = _subp.run(
                [_sys.executable, _hpfix_runner, str(remediated_path)],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60
            )
            _dlog(f"[PIPELINE]   run_heading_parent_fix returncode={_hpfix_proc.returncode}")
            _dlog(f"[PIPELINE]   run_heading_parent_fix stdout={_hpfix_proc.stdout.strip()!r}")
            if _hpfix_proc.stderr.strip():
                _dlog(f"[PIPELINE]   run_heading_parent_fix stderr={_hpfix_proc.stderr.strip()!r}")
            scheduled_outcomes["HDR-005"] = (_hpfix_proc.returncode == 0)
        except Exception as hpe:
            import traceback
            _dlog(f"[PIPELINE]   run_heading_parent_fix ERROR: {hpe}")
            _dlog(traceback.format_exc())
            scheduled_outcomes["HDR-005"] = False

        # Step 8 — merge line-split paragraphs (QA: "unnecessary paragraph
        # breaks"). PDFix AddTags() emits one <P> per visual line; consolidate
        # sibling <P> fragments that belong to one logical paragraph so screen
        # readers do not announce each line as its own paragraph.
        _dlog("[PIPELINE]   calling paragraph_merge_fixer.py ...")
        try:
            _pm_runner = str(Path(__file__).parent / "paragraph_merge_fixer.py")
            _pm_tmp = str(remediated_path) + "_pm.pdf"
            _pm_proc = _subp.run(
                [_sys.executable, _pm_runner, str(remediated_path), _pm_tmp],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120
            )
            _dlog(f"[PIPELINE]   paragraph_merge_fixer returncode={_pm_proc.returncode}")
            _dlog(f"[PIPELINE]   paragraph_merge_fixer stdout={_pm_proc.stdout.strip()!r}")
            if _pm_proc.stderr.strip():
                _dlog(f"[PIPELINE]   paragraph_merge_fixer stderr={_pm_proc.stderr.strip()!r}")
            if _pm_proc.returncode == 0 and _os.path.exists(_pm_tmp) and _os.path.getsize(_pm_tmp) > 0:
                _os.replace(_pm_tmp, str(remediated_path))
            else:
                if _os.path.exists(_pm_tmp):
                    try:
                        _os.unlink(_pm_tmp)
                    except OSError:
                        pass
        except Exception as pme:
            import traceback
            _dlog(f"[PIPELINE]   paragraph_merge_fixer ERROR: {pme}")
            _dlog(traceback.format_exc())

        # ══════════════════════════════════════════════════════════════════
        # Steps 9-13 — structure-quality fixers (pure pikepdf, run in-process)
        #
        # Steps 1-8 make PAC green on syntax. These fix what PAC CANNOT see
        # (reading order, heading semantics, Alt quality) and then repair the
        # structural bookkeeping that editing /K always breaks.
        #
        # ORDER IS LOAD-BEARING:
        #   9  reading_order      - must precede the heading filter, whose
        #                           same-baseline tests assume page order
        #   10 heading_filter     - rejects non-headings, merges Lbl+title
        #   11 alt_sanitizer      - repairs /Alt, lifts text out of Figures
        #   12 alt_apply          - applies human/vision decisions (optional)
        #   13 orphan_sweeper     - MANDATORY, ALWAYS LAST. Any step above can
        #                           orphan marked content; this is what keeps
        #                           PAC's "Content" checkpoint green.
        # ══════════════════════════════════════════════════════════════════
        def _stage(label, fn, *args, **kwargs):
            """
            Run one fixer to a temp file; swap in only on success.

            On Windows os.replace() raises WinError 5 if the destination is
            still open by any handle, so force a GC first and fall back to a
            byte copy. A silently-skipped stage here is worse than a crash:
            the file looks remediated and is not.
            """
            import gc as _gc, shutil as _shutil, time as _time
            _tmp = str(remediated_path) + f"_{label}.pdf"
            try:
                fn(str(remediated_path), _tmp, *args, **kwargs)
                if not (_os.path.exists(_tmp) and _os.path.getsize(_tmp) > 0):
                    _dlog(f"[PIPELINE]   {label} produced no output — skipped")
                    return False
                _gc.collect()
                for _attempt in range(3):
                    try:
                        _os.replace(_tmp, str(remediated_path))
                        _dlog(f"[PIPELINE]   {label} OK")
                        return True
                    except OSError as _oe:
                        _dlog(f"[PIPELINE]   {label} replace attempt {_attempt+1} failed: {_oe}")
                        _gc.collect()
                        _time.sleep(0.3)
                # last resort: copy the bytes over the destination in place
                _shutil.copyfile(_tmp, str(remediated_path))
                _os.unlink(_tmp)
                _dlog(f"[PIPELINE]   {label} OK (via copy fallback)")
                return True
            except Exception as _e:
                import traceback
                _dlog(f"[PIPELINE]   {label} ERROR: {_e}")
                _dlog(traceback.format_exc())
            if _os.path.exists(_tmp):
                try:
                    _os.unlink(_tmp)
                except OSError:
                    pass
            return False

        try:
            from .reading_order_fixer import fix as _fix_reading_order
            from .heading_eligibility_filter import run as _filter_headings
            from .alt_text_sanitizer import run as _sanitize_alt
            from .alt_apply import run as _apply_alt
            from .orphan_sweeper import run as _sweep_orphans
            from .validate import validate as _validate_struct

            # Step 9 — logical reading order
            _dlog("[PIPELINE]   Step 9: reading_order_fixer ...")
            _stage("readorder", _fix_reading_order, within_page=True, report=False)

            # Step 10 — heading eligibility + re-levelling
            _dlog("[PIPELINE]   Step 10: heading_eligibility_filter ...")
            _stage("headfilter", _filter_headings, report=False)

            # Step 11 — Alt text: caption-derive, artifact decorative furniture,
            # lift trapped text out of Figures. Never invents a description;
            # what it cannot derive is listed in alt_needs.json.
            _alt_needs = str(Path(str(remediated_path)).with_suffix("")) + "_alt_needs.json"
            _dlog("[PIPELINE]   Step 11: alt_text_sanitizer ...")
            _stage("altsan", _sanitize_alt, report=False, report_json=_alt_needs)

            _needs_human = []
            if _os.path.exists(_alt_needs):
                try:
                    import json as _json
                    with open(_alt_needs, encoding="utf-8") as _fh:
                        _needs_human = _json.load(_fh).get("needs_human", [])
                except Exception:
                    _needs_human = []
            context["alt_needs_human"] = _needs_human
            context["alt_needs_json_path"] = _alt_needs if _needs_human else None
            _dlog(f"[PIPELINE]   images needing a written description: {len(_needs_human)}")

            # Step 11.5 — auto-generate Alt for the "no alt, no caption" figures
            # with Claude vision, so Step 12 has real decisions to apply instead
            # of the pipeline shipping "[TO BE DESCRIBED]". Runs only when the
            # sanitizer flagged figures AND no human/external decisions file was
            # already supplied (a human file always wins). Non-fatal by design:
            # any failure here just falls through to a SKIPPED Step 12, and the
            # Alt gate below still blocks delivery on leftover placeholders.
            if _needs_human and not context.get("alt_decisions_path"):
                try:
                    from .alt_vision_suggester import suggest as _vision_suggest_alt
                    _alt_decisions_auto = (
                        str(Path(str(remediated_path)).with_suffix(""))
                        + "_decisions.json")
                    _dlog(f"[PIPELINE]   Step 11.5: alt_vision_suggester "
                          f"({len(_needs_human)} figures) ...")
                    _vr = _vision_suggest_alt(
                        str(remediated_path), _alt_needs, _alt_decisions_auto)
                    _dlog(f"[PIPELINE]   Step 11.5: vision resolved "
                          f"{_vr.get('resolved', 0)}/{_vr.get('of', 0)} "
                          f"(skipped {len(_vr.get('skipped', []))})")
                    # Cache effectiveness + LLM cost for this run, so both are
                    # visible in pipeline_debug.log without reading stderr.
                    _sv = _vr.get("savings", {}) or {}
                    _ca = _vr.get("cache", {}) or {}
                    _co = _vr.get("cost", {}) or {}
                    _dlog(f"[PIPELINE]   Step 11.5: CACHE "
                          f"enabled={_ca.get('enabled')} hits={_ca.get('hits', 0)} "
                          f"misses={_ca.get('misses', 0)} writes={_ca.get('writes', 0)} "
                          f"| calls_avoided={_sv.get('calls_avoided', 0)} "
                          f"(decorative={_sv.get('decorative', 0)}, "
                          f"caption={_sv.get('caption', 0)}, cache={_sv.get('cache', 0)})")
                    _dlog(f"[PIPELINE]   Step 11.5: LLM COST "
                          f"billed_calls={_co.get('billed_calls', 0)} "
                          f"in_tok={_co.get('input_tokens', 0)} "
                          f"out_tok={_co.get('output_tokens', 0)} "
                          f"=> ${_co.get('usd', 0.0):.4f}")
                    if _vr.get("skipped"):
                        _rz = {}
                        for _s in _vr["skipped"]:
                            _w = _s.get("why", "?")
                            _rz[_w] = _rz.get(_w, 0) + 1
                        _dlog(f"[PIPELINE]   Step 11.5: skip reasons {_rz}")
                    if _vr.get("resolved"):
                        context["alt_decisions_path"] = _alt_decisions_auto
                        context["alt_decisions_source"] = "vision"
                except Exception as _vex:
                    _dlog(f"[PIPELINE]   Step 11.5: vision suggester SKIPPED: {_vex}")

            # Step 12 — apply Alt decisions, if a decisions file was supplied.
            # context["alt_decisions_path"] is per-document: written by a human
            # or by a vision model from alt_needs.json. Absent -> skipped, and
            # those figures keep the "[TO BE DESCRIBED]" marker.
            _alt_decisions = context.get("alt_decisions_path")
            if _alt_decisions and _os.path.exists(str(_alt_decisions)):
                _dlog(f"[PIPELINE]   Step 12: alt_apply <- {_alt_decisions}")
                _stage("altapply", _apply_alt, str(_alt_decisions), report=False)
            else:
                _dlog("[PIPELINE]   Step 12: alt_apply SKIPPED (no decisions file)")

            # Step 13 — orphan sweep. MANDATORY. MUST BE LAST.
            _dlog("[PIPELINE]   Step 13: orphan_sweeper ...")
            _stage("orphans", _sweep_orphans, report=False)

            # Alt gate (ALT-001) — never deliver a figure still tagged
            # "[TO BE DESCRIBED]" or left with empty Alt. This is the safety net
            # that makes the placeholder a non-shippable state rather than a
            # silent pass: if vision (11.5) and human decisions (12) both left
            # something unresolved, delivery is blocked here.
            try:
                import pikepdf as _pk, re as _re
                _PH = _re.compile(r"to be described|^\s*$", _re.I)

                def _count_placeholders(node, seen):
                    try:
                        og = node.objgen
                        key = og if (og and og[0]) else id(node)
                    except Exception:
                        key = id(node)
                    if key in seen:
                        return 0
                    seen.add(key)
                    c = 0
                    if str(node.get("/S")) == "/Figure":
                        a = node.get("/Alt")
                        if a is None or _PH.search(str(a)):
                            c = 1
                    k = node.get("/K")
                    if k is not None:
                        for it in (k if isinstance(k, _pk.Array) else [k]):
                            if isinstance(it, _pk.Dictionary):
                                c += _count_placeholders(it, seen)
                    return c

                with _pk.open(str(remediated_path)) as _p:
                    _st = _p.Root.get("/StructTreeRoot")
                    _alt_left = _count_placeholders(_st, set()) if _st is not None else 0
            except Exception as _ae:
                _dlog(f"[PIPELINE]   alt gate ERROR: {_ae}")
                _alt_left = -1
            context["alt_placeholders_remaining"] = _alt_left
            scheduled_outcomes["ALT-001"] = (_alt_left == 0)
            _dlog(f"[PIPELINE]   ALT PLACEHOLDERS REMAINING: {_alt_left}")
            if _alt_left != 0:
                _dlog("[PIPELINE]   *** DO NOT DELIVER — figures still lack real Alt ***")

            # Final structural gate — the checks PAC actually runs.
            try:
                _struct_ok = (_validate_struct(str(remediated_path)) == 0)
            except Exception as _ve:
                _dlog(f"[PIPELINE]   validate ERROR: {_ve}")
                _struct_ok = False
            context["structure_validation_passed"] = _struct_ok
            scheduled_outcomes["STRUCT-001"] = _struct_ok
            _dlog(f"[PIPELINE]   STRUCTURE VALIDATION: {'CLEAN' if _struct_ok else 'FAILS'}")
            if not _struct_ok:
                _dlog("[PIPELINE]   *** DO NOT DELIVER — structure validation failed ***")

        except ImportError as _ie:
            _dlog(f"[PIPELINE]   structure fixers not installed: {_ie}")
        except Exception as _se:
            import traceback
            _dlog(f"[PIPELINE]   structure fixer stage ERROR: {_se}")
            _dlog(traceback.format_exc())

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

# ---------------------------------------------------------------------------
# Public background-job entry point (called by the router's BackgroundTasks)
# ---------------------------------------------------------------------------

def _os_env_flag(name: str, default: bool = True) -> bool:
    """Read a boolean-ish env var. '0','false','no','off' -> False."""
    import os as _os
    val = _os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() not in ("0", "false", "no", "off", "")


def _strip_pdf_suffix(path: str) -> str:
    """Strip a known pipeline stage suffix (or .pdf) to get the base name."""
    for _s in ("_pop.pdf", "_ra.pdf", "_ct.pdf", "_fa.pdf", "_alt.pdf", "_ann.pdf",
               "_art.pdf", "_mcc.pdf", "_mcr.pdf", "_cmt.pdf", "_clean.pdf",
               ".enc.pdf", ".pdf"):
        if path.endswith(_s):
            return path[:-len(_s)]
    return path


def run_pipeline_job(
    job_id: str,
    file_bytes: bytes,
    filename: str,
    organization_id,
    project_id,
    job_store: dict,
) -> None:
    """
    Full end-to-end remediation job.  Runs in a background thread so the
    HTTP response (202 Accepted) is returned immediately to the caller.

    Stages
    ------
    1. PDFix init + open PDF
    2. AccessibilityRemediationPipeline.run()
       (internally: validate → remediate → save → font encoding → link/heading/artifact fixes → revalidate)
    3. Badge overlay removal          (badge_remover.py)
    4. Tagged-annotation fix          (tagged_annotations_fixer.py)
    5. Alt-text generation via Claude (run_fix_alt_text.py)
    5.5 Figure content-association fix (figure_association_fixer.py)
    5.7 Running header/footer artifacting (running_artifact_fixer.py)
    5.8 Tagged-content-in-artifact cleanup (tagged_figure_popout_fixer.py)
    5.965 List label extraction        (list_label_fixer.py, after 5.96)
    5.967 Running-header artifacting   (running_header_artifacter.py, after 5.965)
    5.968 Inline formatting spans      (inline_span_fixer.py, after 5.967)
    6. Persist result in job_store

    (Text-contrast / WCAG 1.4.3 is handled in-process by
    contrast_fixer.fix_text_contrast() inside _save_remediated_pdf.)
    """
    _enc_log = str(Path(__file__).parent.parent.parent.parent.parent / "encoding_fix.log")

    def _log(msg: str) -> None:
        _dlog(msg)
        try:
            with open(_enc_log, "a", encoding="utf-8") as _f:
                _f.write(msg + "\n")
        except Exception:
            pass

    tmp_path = None
    pdf_doc = None
    context: dict = {}   # initialised early so finally block can read context["pdf_doc"]

    try:
        job_store[job_id]["status"] = "running"
        _log(f"[JOB] {job_id} started — {filename}")

        # ── 1. PDFix init ─────────────────────────────────────────────
        from .pdfix_service import PDFixService
        _pdfix_svc = PDFixService()
        pdfix_module = _pdfix_svc._load_pdfix_module()
        pdfix = pdfix_module.GetPdfix()
        if not pdfix:
            raise ValueError("Unable to initialize PDFix SDK")

        import tempfile as _tmp
        with _tmp.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        pdf_doc = pdfix.OpenDoc(tmp_path, "")
        if not pdf_doc:
            raise ValueError("Failed to open PDF document with PDFix")

        context: dict = {
            "pdf_doc": pdf_doc,
            "pdf_doc_path": tmp_path,
            "document_name": filename,
            "total_pages": pdf_doc.GetNumPages() if hasattr(pdf_doc, "GetNumPages") else 0,
            "file_size_bytes": len(file_bytes),
        }

        # ── 2. Core pipeline (validate → remediate → post-process → revalidate) ──
        _log(f"[JOB] {job_id} running core pipeline ...")
        pipeline = AccessibilityRemediationPipeline()
        pipeline_result = pipeline.run(
            organization_id=organization_id,
            project_id=project_id,
            context=context,
        )
        remediated_pdf_path = pipeline_result.get("remediated_pdf_path")
        _log(f"[JOB] {job_id} pipeline done. path={remediated_pdf_path!r}")

        # ── 3. Badge overlay removal ──────────────────────────────────
        if remediated_pdf_path and Path(remediated_pdf_path).exists():
            import subprocess as _sp, os as _os
            _badge = str(Path(__file__).parent / "badge_remover.py")
            if Path(_badge).exists():
                _env = dict(_os.environ)
                _env["PYTHONIOENCODING"] = "utf-8"
                _base = str(remediated_pdf_path)
                for _s in ("_ann.pdf", "_alt.pdf", ".enc.pdf", ".pdf"):
                    if _base.endswith(_s):
                        _base = _base[:-len(_s)]
                        break
                _out = _base + "_clean.pdf"
                _r = _sp.run([_sys.executable, _badge, remediated_pdf_path, _out],
                             capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=120, env=_env)
                _log(f"[JOB] badge_remover rc={_r.returncode}")
                if _r.returncode == 0 and Path(_out).exists() and Path(_out).stat().st_size > 0:
                    remediated_pdf_path = _out

        # ── 3.5 Review-comment removal ────────────────────────────────
        # Strip proofreader markup (Text/Ink/Caret/StrikeOut/Popup, etc.)
        # BEFORE annotation tagging: editorial comments must not ship in
        # a published accessible PDF, and removing them (plus their
        # struct-tree references) directly clears Acrobat's
        # "Tagged annotations" failures they cause.
        # Disable with env ORION_REMOVE_REVIEW_COMMENTS=0.
        import os as _os_cmt
        if (remediated_pdf_path and Path(remediated_pdf_path).exists()
                and _os_cmt.environ.get("ORION_REMOVE_REVIEW_COMMENTS", "1") != "0"):
            import subprocess as _spc
            _cmt = str(Path(__file__).parent / "review_comment_remover.py")
            if Path(_cmt).exists():
                _envc = dict(_os_cmt.environ)
                _envc["PYTHONIOENCODING"] = "utf-8"
                _basec = str(remediated_pdf_path)
                for _sc in ("_clean.pdf", "_alt.pdf", ".enc.pdf", ".pdf"):
                    if _basec.endswith(_sc):
                        _basec = _basec[:-len(_sc)]
                        break
                _outc = _basec + "_cmt.pdf"
                _rc = _spc.run([_sys.executable, _cmt, remediated_pdf_path, _outc],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=120, env=_envc)
                _log(f"[JOB] review_comment_remover rc={_rc.returncode}")
                if _rc.returncode == 0 and Path(_outc).exists() and Path(_outc).stat().st_size > 0:
                    remediated_pdf_path = _outc
                elif _rc.returncode != 0:
                    _log(f"[JOB] review_comment_remover stderr={_rc.stderr[-500:]!r}")

        # ── 3.6 Duplicate-MCR fix ─────────────────────────────────────
        # PDFix AddTags() can emit multiple /MCR kids claiming the same
        # (page, MCID) — Adobe's checker tolerates it, but PAC aborts with
        # "MCID N already present".  Deduplicate claims and drop the junk
        # placeholder <Figure> elements left empty.
        if remediated_pdf_path and Path(remediated_pdf_path).exists():
            import subprocess as _spm, os as _osm
            _mcr = str(Path(__file__).parent / "duplicate_mcr_fixer.py")
            if Path(_mcr).exists():
                _envm = dict(_osm.environ)
                _envm["PYTHONIOENCODING"] = "utf-8"
                _basem = str(remediated_pdf_path)
                for _sm in ("_cmt.pdf", "_clean.pdf", "_alt.pdf", ".enc.pdf", ".pdf"):
                    if _basem.endswith(_sm):
                        _basem = _basem[:-len(_sm)]
                        break
                _outm = _basem + "_mcr.pdf"
                _rm = _spm.run([_sys.executable, _mcr, remediated_pdf_path, _outm],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=120, env=_envm)
                _log(f"[JOB] duplicate_mcr_fixer rc={_rm.returncode}")
                if _rm.returncode == 0 and Path(_outm).exists() and Path(_outm).stat().st_size > 0:
                    remediated_pdf_path = _outm
                elif _rm.returncode != 0:
                    _log(f"[JOB] duplicate_mcr_fixer stderr={_rm.stderr[-500:]!r}")

        # ── 3.7 Content-stream MCID fix ───────────────────────────────
        # PDFix AddTags() can emit COLLIDING MCIDs inside one page's
        # content stream (e.g. "/P <</MCID 1>>" and "/Figure <</MCID 1>>").
        # PAC aborts with "MCID N already present"; Adobe doesn't notice.
        # Renumber sequences uniquely, re-point the structure tree, and
        # prune phantom claims to MCIDs that don't exist in the content.
        if remediated_pdf_path and Path(remediated_pdf_path).exists():
            import subprocess as _spcc, os as _oscc
            _mcc = str(Path(__file__).parent / "content_mcid_fixer.py")
            if Path(_mcc).exists():
                _envcc = dict(_oscc.environ)
                _envcc["PYTHONIOENCODING"] = "utf-8"
                _basecc = str(remediated_pdf_path)
                for _scc in ("_mcr.pdf", "_cmt.pdf", "_clean.pdf", "_alt.pdf", ".enc.pdf", ".pdf"):
                    if _basecc.endswith(_scc):
                        _basecc = _basecc[:-len(_scc)]
                        break
                _outcc = _basecc + "_mcc.pdf"
                _rcc = _spcc.run([_sys.executable, _mcc, remediated_pdf_path, _outcc],
                                 capture_output=True, text=True, encoding="utf-8",
                                 errors="replace", timeout=180, env=_envcc)
                _log(f"[JOB] content_mcid_fixer rc={_rcc.returncode}")
                if _rcc.returncode == 0 and Path(_outcc).exists() and Path(_outcc).stat().st_size > 0:
                    remediated_pdf_path = _outcc
                elif _rcc.returncode != 0:
                    _log(f"[JOB] content_mcid_fixer stderr={_rcc.stderr[-500:]!r}")

        # ── 3.8 Untagged-content artifact fix ─────────────────────────
        # PDF/UA: every painting op must be real (tagged) content or an
        # artifact.  Convert orphan MCID sequences to /Artifact BMC and
        # wrap bare painting runs — clears PAC "Path/Text object not
        # tagged" errors.  Runs AFTER content_mcid_fixer so structure-tree
        # claims are consistent.
        if remediated_pdf_path and Path(remediated_pdf_path).exists():
            import subprocess as _spart, os as _osart
            _art = str(Path(__file__).parent / "untagged_content_fixer.py")
            if Path(_art).exists():
                _envart = dict(_osart.environ)
                _envart["PYTHONIOENCODING"] = "utf-8"
                _baseart = str(remediated_pdf_path)
                for _sart in ("_nau.pdf", "_mcc.pdf", "_mcr.pdf", "_cmt.pdf", "_clean.pdf", "_alt.pdf", ".enc.pdf", ".pdf"):
                    if _baseart.endswith(_sart):
                        _baseart = _baseart[:-len(_sart)]
                        break
                _outart = _baseart + "_art.pdf"
                _rart = _spart.run([_sys.executable, _art, remediated_pdf_path, _outart],
                                   capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", timeout=300, env=_envart)
                _log(f"[JOB] untagged_content_fixer rc={_rart.returncode}")
                if _rart.returncode == 0 and Path(_outart).exists() and Path(_outart).stat().st_size > 0:
                    remediated_pdf_path = _outart
                elif _rart.returncode != 0:
                    _log(f"[JOB] untagged_content_fixer stderr={_rart.stderr[-500:]!r}")

        # ── 4. Tagged-annotation fix ──────────────────────────────────
        if remediated_pdf_path and Path(remediated_pdf_path).exists():
            import subprocess as _sp2, os as _os2
            _ann = str(Path(__file__).parent / "tagged_annotations_fixer.py")
            if Path(_ann).exists():
                _env2 = dict(_os2.environ)
                _env2["PYTHONIOENCODING"] = "utf-8"
                _base2 = str(remediated_pdf_path)
                for _s2 in ("_cmt.pdf", "_clean.pdf", "_alt.pdf", ".enc.pdf", ".pdf"):
                    if _base2.endswith(_s2):
                        _base2 = _base2[:-len(_s2)]
                        break
                _out2 = _base2 + "_ann.pdf"
                _r2 = _sp2.run([_sys.executable, _ann, remediated_pdf_path, _out2],
                               capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=120, env=_env2)
                _log(f"[JOB] tagged_annotations_fixer rc={_r2.returncode}")
                if _r2.returncode == 0 and Path(_out2).exists() and Path(_out2).stat().st_size > 0:
                    remediated_pdf_path = _out2

        # ── 5. Alt-text generation (Claude vision) ────────────────────
        if remediated_pdf_path and Path(remediated_pdf_path).exists():
            import subprocess as _sp3, os as _os3
            _alt = str(Path(__file__).parent / "run_fix_alt_text.py")
            _base3 = str(remediated_pdf_path)
            _out3 = (
                _base3[:-len("_ann.pdf")] + "_alt.pdf" if _base3.endswith("_ann.pdf") else
                _base3[:-len("_clean.pdf")] + "_alt.pdf" if _base3.endswith("_clean.pdf") else
                _base3[:-4] + "_alt.pdf" if _base3.endswith(".pdf") else
                _base3 + "_alt.pdf"
            )
            _env3 = dict(_os3.environ)
            _env3["PYTHONIOENCODING"] = "utf-8"
            # Load API key from .env if not in environment
            if not _env3.get("ANTHROPIC_API_KEY"):
                try:
                    _dotenv = Path(__file__).resolve().parent.parent.parent.parent.parent / ".env"
                    if _dotenv.exists():
                        for _line in _dotenv.read_text(encoding="utf-8").splitlines():
                            _line = _line.strip()
                            if not _line or _line.startswith("#"):
                                continue
                            if "orion-" in _line.lower() and "key" in _line.lower():
                                for _sep in ("=", ":"):
                                    if _sep in _line:
                                        _v = _line.split(_sep, 1)[1].strip().strip('"').strip("'")
                                        if _v:
                                            _env3["ANTHROPIC_API_KEY"] = _v
                                        break
                except Exception:
                    pass
            _r3 = _sp3.run([_sys.executable, _alt, remediated_pdf_path, _out3],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=180, env=_env3)
            _log(f"[JOB] run_fix_alt_text rc={_r3.returncode}")
            if _r3.returncode == 0 and Path(_out3).exists() and Path(_out3).stat().st_size > 0:
                remediated_pdf_path = _out3

        # ── 5.5 Figure content-association fix ────────────────────────
        # Adobe: "Associated with content - Failed".  Alt-text generation
        # (and PDFix AddTags) can leave <Figure> tags that carry /Alt and a
        # /BBox but were never linked to the image painted on the page.
        # Match each orphan figure to its image (by BBox vs. the image's
        # actual painted position), wrap the paint op in /Figure BDC..EMC,
        # and wire up /K + ParentTree both ways.  Runs AFTER alt-text so it
        # associates the figures that step produced/left untouched.
        if remediated_pdf_path and Path(remediated_pdf_path).exists():
            import subprocess as _spfa, os as _osfa
            _fa = str(Path(__file__).parent / "figure_association_fixer.py")
            if Path(_fa).exists():
                _envfa = dict(_osfa.environ)
                _envfa["PYTHONIOENCODING"] = "utf-8"
                _basefa = str(remediated_pdf_path)
                for _sfa in ("_alt.pdf", "_ann.pdf", "_art.pdf", "_mcc.pdf",
                             "_mcr.pdf", "_cmt.pdf", "_clean.pdf", ".enc.pdf", ".pdf"):
                    if _basefa.endswith(_sfa):
                        _basefa = _basefa[:-len(_sfa)]
                        break
                _outfa = _basefa + "_fa.pdf"
                _rfa = _spfa.run([_sys.executable, _fa, remediated_pdf_path, _outfa],
                                 capture_output=True, text=True, encoding="utf-8",
                                 errors="replace", timeout=180, env=_envfa)
                _log(f"[JOB] figure_association_fixer rc={_rfa.returncode}")
                if _rfa.returncode == 0 and Path(_outfa).exists() and Path(_outfa).stat().st_size > 0:
                    remediated_pdf_path = _outfa
                elif _rfa.returncode != 0:
                    _log(f"[JOB] figure_association_fixer stderr={_rfa.stderr[-500:]!r}")

        # Note: text-contrast (WCAG 1.4.3) is handled earlier and in-process by
        # fix_text_contrast() inside _save_remediated_pdf (COLOR-001/002), so no
        # separate subprocess step is needed here.

        # ── 5.7 Running header/footer artifacting ─────────────────────
        # Marks the running footer (page-title + page-number banner text) as
        # /Artifact.  Correct PDF/UA treatment for pagination furniture and
        # exempts it from 1.4.3 with zero visual change.  Gated behind
        # ORION_ARTIFACT_RUNNING (default "1").
        if (remediated_pdf_path and Path(remediated_pdf_path).exists()
                and _os_env_flag("ORION_ARTIFACT_RUNNING", default=True)):
            import subprocess as _spra, os as _osra
            _ra = str(Path(__file__).parent / "running_artifact_fixer.py")
            if Path(_ra).exists():
                _envra = dict(_osra.environ)
                _envra["PYTHONIOENCODING"] = "utf-8"
                _basera = _strip_pdf_suffix(str(remediated_pdf_path))
                _outra = _basera + "_ra.pdf"
                _rra = _spra.run([_sys.executable, _ra, remediated_pdf_path, _outra],
                                 capture_output=True, text=True, encoding="utf-8",
                                 errors="replace", timeout=180, env=_envra)
                _log(f"[JOB] running_artifact_fixer rc={_rra.returncode}")
                if _rra.returncode == 0 and Path(_outra).exists() and Path(_outra).stat().st_size > 0:
                    remediated_pdf_path = _outra
                elif _rra.returncode != 0:
                    _log(f"[JOB] running_artifact_fixer stderr={_rra.stderr[-500:]!r}")

        # ── 5.8 Tagged-content-in-artifact cleanup (PDF/UA) ───────────
        # Pops any tagged block (a Figure/P with an MCID) that ended up nested
        # inside an /Artifact out to the top level. This is the fix that clears
        # PAC's PDF/UA "Tagged content present inside an artifact" errors.
        # Runs LAST so it cleans up whatever any upstream step (PDFix AddTags,
        # artifact_fixer, figure_association_fixer, running_artifact_fixer)
        # produced. Needs only pikepdf (no PyMuPDF/numpy).
        if remediated_pdf_path and Path(remediated_pdf_path).exists():
            import subprocess as _sppop, os as _ospop
            _pop = str(Path(__file__).parent / "tagged_figure_popout_fixer.py")
            if Path(_pop).exists():
                _envpop = dict(_ospop.environ)
                _envpop["PYTHONIOENCODING"] = "utf-8"
                _basepop = _strip_pdf_suffix(str(remediated_pdf_path))
                _outpop = _basepop + "_pop.pdf"
                _rpop = _sppop.run([_sys.executable, _pop, remediated_pdf_path, _outpop],
                                   capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", timeout=180, env=_envpop)
                _log(f"[JOB] tagged_figure_popout_fixer rc={_rpop.returncode}")
                if _rpop.returncode == 0 and Path(_outpop).exists() and Path(_outpop).stat().st_size > 0:
                    remediated_pdf_path = _outpop
                elif _rpop.returncode != 0:
                    _log(f"[JOB] tagged_figure_popout_fixer stderr={_rpop.stderr[-500:]!r}")

        # ── 5.9 Nested-artifact unwrap (MUST BE LAST) ─────────────────
        # PDF/UA forbids an artifact inside tagged content: content is
        # either real (tagged) or an artifact, never both.  Several earlier
        # steps (notably running_artifact_fixer) re-wrap already-tagged text
        # in /Artifact, which BOTH hides the text from screen readers AND
        # produces PAC's "Artifact present inside tagged content" errors.
        #
        # This step strips those nested /Artifact wrappers.  It MUST run
        # last: any fixer scheduled after it can re-introduce the nesting
        # and silently undo the repair.  Top-level artifacts (running
        # header, page numbers, decorative paint) have no tagged ancestor
        # and are never touched.
        if remediated_pdf_path and Path(remediated_pdf_path).exists():
            import subprocess as _spnau, os as _osnau
            _nau = str(Path(__file__).parent / "nested_artifact_unwrapper.py")
            if Path(_nau).exists():
                _envnau = dict(_osnau.environ)
                _envnau["PYTHONIOENCODING"] = "utf-8"
                _basenau = _strip_pdf_suffix(str(remediated_pdf_path))
                _outnau = _basenau + "_nau.pdf"
                _rnau = _spnau.run([_sys.executable, _nau, remediated_pdf_path, _outnau],
                                   capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", timeout=300, env=_envnau)
                _log(f"[JOB] nested_artifact_unwrapper rc={_rnau.returncode}")
                if _rnau.stdout:
                    _log(f"[JOB] nested_artifact_unwrapper out={_rnau.stdout.strip()[:300]}")
                if _rnau.returncode == 0 and Path(_outnau).exists() and Path(_outnau).stat().st_size > 0:
                    remediated_pdf_path = _outnau
                elif _rnau.returncode != 0:
                    _log(f"[JOB] nested_artifact_unwrapper stderr={_rnau.stderr[-500:]!r}")

        # ── 5.92 Heading hierarchy normalization ──────────────────────
        # PDFix marks the repeating page banner as <H1> on every page and
        # leaves the real section headings tagged as <P>: the outline a
        # screen-reader user navigates by is therefore useless (many H1s,
        # most of them empty, no H2/H3).  This step drops empty headings,
        # promotes genuine headings (detected by font/size, not hardcoded
        # text), assigns levels by size rank, and artifacts the repeated
        # running-header heading.
        #
        # MUST run AFTER nested_artifact_unwrapper: heading text that is
        # still wrapped in /Artifact is invisible to the detector and would
        # be silently skipped.
        if remediated_pdf_path and Path(remediated_pdf_path).exists():
            import subprocess as _sphn, os as _oshn
            _hn = str(Path(__file__).parent / "heading_normalizer.py")
            if Path(_hn).exists():
                _envhn = dict(_oshn.environ)
                _envhn["PYTHONIOENCODING"] = "utf-8"
                _basehn = _strip_pdf_suffix(str(remediated_pdf_path))
                _outhn = _basehn + "_hdr.pdf"
                _rhn = _sphn.run([_sys.executable, _hn, remediated_pdf_path, _outhn],
                                 capture_output=True, text=True, encoding="utf-8",
                                 errors="replace", timeout=300, env=_envhn)
                _log(f"[JOB] heading_normalizer rc={_rhn.returncode}")
                if _rhn.stdout:
                    _log(f"[JOB] heading_normalizer out={_rhn.stdout.strip()[:300]}")
                if _rhn.returncode == 0 and Path(_outhn).exists() and Path(_outhn).stat().st_size > 0:
                    remediated_pdf_path = _outhn
                elif _rhn.returncode != 0:
                    _log(f"[JOB] heading_normalizer stderr={_rhn.stderr[-500:]!r}")

        # ── 5.93 Link text association ────────────────────────────────
        # PDFix links the annotation to a <Link> element but often leaves the
        # element with no CONTENT, so a screen reader announces an anonymous
        # link.  Automated checkers do not catch this (the /OBJR is present),
        # which is exactly the kind of gap only a manual/AT review finds.
        # This step locates the link's glyphs via the annotation /Rect and
        # moves them inside the <Link>.  Runs after heading_normalizer so the
        # text is reachable and the tree is settled.
        if remediated_pdf_path and Path(remediated_pdf_path).exists():
            import subprocess as _splt, os as _oslt
            _lt = str(Path(__file__).parent / "link_text_fixer.py")
            if Path(_lt).exists():
                _envlt = dict(_oslt.environ)
                _envlt["PYTHONIOENCODING"] = "utf-8"
                _outlt = _strip_pdf_suffix(str(remediated_pdf_path)) + "_lnk.pdf"
                _rlt = _splt.run([_sys.executable, _lt, remediated_pdf_path, _outlt],
                                 capture_output=True, text=True, encoding="utf-8",
                                 errors="replace", timeout=300, env=_envlt)
                _log(f"[JOB] link_text_fixer rc={_rlt.returncode}")
                if _rlt.stdout:
                    _log(f"[JOB] link_text_fixer out={_rlt.stdout.strip()[:300]}")
                if _rlt.returncode == 0 and Path(_outlt).exists() and Path(_outlt).stat().st_size > 0:
                    remediated_pdf_path = _outlt
                elif _rlt.returncode != 0:
                    _log(f"[JOB] link_text_fixer stderr={_rlt.stderr[-500:]!r}")

        # ── 5.94 Empty tag cleanup ────────────────────────────────────
        # Drop structure elements that reference no content at all.  Runs late
        # so it also sweeps shells left behind by the preceding fixers.
        if remediated_pdf_path and Path(remediated_pdf_path).exists():
            import subprocess as _spet, os as _oset
            _et = str(Path(__file__).parent / "empty_tag_cleaner.py")
            if Path(_et).exists():
                _envet = dict(_oset.environ)
                _envet["PYTHONIOENCODING"] = "utf-8"
                _outet = _strip_pdf_suffix(str(remediated_pdf_path)) + "_etc.pdf"
                _ret = _spet.run([_sys.executable, _et, remediated_pdf_path, _outet],
                                 capture_output=True, text=True, encoding="utf-8",
                                 errors="replace", timeout=180, env=_envet)
                _log(f"[JOB] empty_tag_cleaner rc={_ret.returncode}")
                if _ret.stdout:
                    _log(f"[JOB] empty_tag_cleaner out={_ret.stdout.strip()[:300]}")
                if _ret.returncode == 0 and Path(_outet).exists() and Path(_outet).stat().st_size > 0:
                    remediated_pdf_path = _outet
                elif _ret.returncode != 0:
                    _log(f"[JOB] empty_tag_cleaner stderr={_ret.stderr[-500:]!r}")

        # ── 5.95 Structure-tree parent pointer repair ─────────────────
        # Every StructElem's /P must point at the element that actually
        # contains it in /K.  Fixers that MOVE children between parents
        # (paragraph_merge_fixer merging <P> siblings, heading/figure
        # re-parenting) can leave a stale /P aimed at an element that has
        # since been detached from the tree.  PAC reports this as
        # "Structure element refers to a diffrent parent than the actual
        # parent" under BOTH "Parents of structure elements" and "Logical
        # structure syntax" (so 2 bad elements => 4 errors).
        #
        # Runs near-last so it repairs whatever the preceding steps moved.
        # Touches only /P back-pointers; content streams are untouched.
        if remediated_pdf_path and Path(remediated_pdf_path).exists():
            import subprocess as _spsp, os as _ossp
            _spf = str(Path(__file__).parent / "struct_parent_fixer.py")
            if Path(_spf).exists():
                _envsp = dict(_ossp.environ)
                _envsp["PYTHONIOENCODING"] = "utf-8"
                _basesp = _strip_pdf_suffix(str(remediated_pdf_path))
                _outsp = _basesp + "_spf.pdf"
                _rsp = _spsp.run([_sys.executable, _spf, remediated_pdf_path, _outsp],
                                 capture_output=True, text=True, encoding="utf-8",
                                 errors="replace", timeout=180, env=_envsp)
                _log(f"[JOB] struct_parent_fixer rc={_rsp.returncode}")
                if _rsp.stdout:
                    _log(f"[JOB] struct_parent_fixer out={_rsp.stdout.strip()[:300]}")
                if _rsp.returncode == 0 and Path(_outsp).exists() and Path(_outsp).stat().st_size > 0:
                    remediated_pdf_path = _outsp
                elif _rsp.returncode != 0:
                    _log(f"[JOB] struct_parent_fixer stderr={_rsp.stderr[-500:]!r}")

        # ── 5.96 Final structure repair (MUST BE THE LAST STRUCTURE STAGE) ──
        # Every fixer above operates on an INTERMEDIATE file, and several of
        # them run before the step that creates the defect they clear:
        #
        #   * run_heading_parent_fix (step 7 of _save_remediated_pdf) executes
        #     long BEFORE heading_normalizer (5.92) produces the headings, so
        #     the 28 <Hn> elements sitting inside <NonStruct> were never
        #     re-parented   -> PAC HDR-005 "Invalid use of Hn structure element"
        #   * heading_normalizer assigns levels by SIZE RANK, so every heading
        #     sharing the largest size became <H1>  -> 11 H1s, HDR-002 FAIL
        #   * PDFix AddTags swallows whole callout boxes into <Figure>, and the
        #     artifact steps leave real body copy inside /Artifact  -> the QA
        #     tester's "Editable text tagged as Figure" and "readable content
        #     ... marked as Artifact"
        #
        # This stage runs on the file that is actually DELIVERED and repairs all
        # of it in one pikepdf pass, then rebuilds /ParentTree from scratch so
        # no earlier stage can leave a stale pointer behind.
        if remediated_pdf_path and Path(remediated_pdf_path).exists():
            import subprocess as _spfsr, os as _osfsr
            _fsr = str(Path(__file__).parent / "final_structure_repair.py")
            if Path(_fsr).exists():
                _envfsr = dict(_osfsr.environ)
                _envfsr["PYTHONIOENCODING"] = "utf-8"
                _outfsr = _strip_pdf_suffix(str(remediated_pdf_path)) + "_fsr.pdf"
                _rfsr = _spfsr.run([_sys.executable, _fsr, remediated_pdf_path, _outfsr],
                                   capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", timeout=300, env=_envfsr)
                _log(f"[JOB] final_structure_repair rc={_rfsr.returncode}")
                if _rfsr.stdout:
                    _log(f"[JOB] final_structure_repair out={_rfsr.stdout.strip()[:400]}")
                if _rfsr.returncode == 0 and Path(_outfsr).exists() and Path(_outfsr).stat().st_size > 0:
                    remediated_pdf_path = _outfsr
                elif _rfsr.returncode != 0:
                    _log(f"[JOB] final_structure_repair stderr={_rfsr.stderr[-500:]!r}")

        # ── 5.965 List label (<Lbl>) extraction ───────────────────────
        # PDFix emits a list item's bullet and its body text as ONE marked
        # content sequence, so whichever element claims that sequence swallows
        # the bullet — usually the <Link>, whose accessible name then reads
        # "<bullet>HB 2107" instead of "HB 2107"; sometimes the <LBody>.  This
        # step splits the sequence at the symbol-font boundary and gives the
        # bullet its own <Lbl>, which is what Word emitted in the first place.
        #
        # MUST RUN AFTER final_structure_repair (5.96), not before it.  FSR is
        # where the L -> LI -> LBody tree is actually settled; run earlier, this
        # step finds almost nothing to attach a label to.  Measured on the
        # 2023-Legislative-Summary sample: 2 labels recovered when it ran at
        # 5.935, 51 when it runs here.  It rewrites content streams and struct
        # elements, so it also re-asserts /ListNumbering and rebuilds the
        # ParentTree itself rather than relying on a later pass.
        if remediated_pdf_path and Path(remediated_pdf_path).exists():
            import subprocess as _spll, os as _osll
            _ll = str(Path(__file__).parent / "list_label_fixer.py")
            if Path(_ll).exists():
                _envll = dict(_osll.environ)
                _envll["PYTHONIOENCODING"] = "utf-8"
                _outll = _strip_pdf_suffix(str(remediated_pdf_path)) + "_lbl.pdf"
                _rll = _spll.run([_sys.executable, _ll, remediated_pdf_path, _outll],
                                 capture_output=True, text=True, encoding="utf-8",
                                 errors="replace", timeout=300, env=_envll)
                _log(f"[JOB] list_label_fixer rc={_rll.returncode}")
                if _rll.stdout:
                    _log(f"[JOB] list_label_fixer out={_rll.stdout.strip()[:300]}")
                if _rll.returncode == 0 and Path(_outll).exists() and Path(_outll).stat().st_size > 0:
                    remediated_pdf_path = _outll
                elif _rll.returncode != 0:
                    _log(f"[JOB] list_label_fixer stderr={_rll.stderr[-500:]!r}")

        # ── 5.967 Running-header artifacting ──────────────────────────
        # heading_normalizer (5.92) artifacts repeated banners, but only when
        # every one of the banner's marked-content sequences is top-level —
        # artifacting a NESTED sequence in place would leave tagged content
        # inside an artifact, a different PDF/UA violation. When it cannot, it
        # demotes the banner to <P>, which is safe but keeps the document title
        # in the logical tree, so a screen reader announces it on every page.
        #
        # This step runs on the settled tree (after 5.96) and handles both
        # shapes: top-level banners are retagged in place, nested ones are cut
        # out by closing the enclosing sequence, emitting the artifact, and
        # reopening with a FRESH MCID (never a reuse — PDF 32000-1 §14.7.4.2
        # requires MCIDs to be unique within a content stream). Halves that
        # paint nothing are dropped rather than left as inkless MCIDs, which
        # would show up as phantom MCIDs in validate.py.
        if remediated_pdf_path and Path(remediated_pdf_path).exists():
            import subprocess as _sprh, os as _osrh
            _rh = str(Path(__file__).parent / "running_header_artifacter.py")
            if Path(_rh).exists():
                _envrh = dict(_osrh.environ)
                _envrh["PYTHONIOENCODING"] = "utf-8"
                _outrh = _strip_pdf_suffix(str(remediated_pdf_path)) + "_rhd.pdf"
                _rrh = _sprh.run([_sys.executable, _rh, remediated_pdf_path, _outrh],
                                 capture_output=True, text=True, encoding="utf-8",
                                 errors="replace", timeout=300, env=_envrh)
                _log(f"[JOB] running_header_artifacter rc={_rrh.returncode}")
                if _rrh.stdout:
                    _log(f"[JOB] running_header_artifacter out={_rrh.stdout.strip()[:300]}")
                if _rrh.returncode == 0 and Path(_outrh).exists() and Path(_outrh).stat().st_size > 0:
                    remediated_pdf_path = _outrh
                elif _rrh.returncode != 0:
                    _log(f"[JOB] running_header_artifacter stderr={_rrh.stderr[-500:]!r}")

        # ── 5.968 Inline formatting spans ─────────────────────────────
        # PDFix emits one marked-content sequence per paragraph, so a bold
        # lead-in and the regular text after it share a single MCID and there is
        # nothing for a <Span> to point at.  This splits the sequence at the
        # font boundary and wraps the formatting run in its own <Span>, which is
        # what a Word export produces.
        #
        # Honest scoping: <Span> carries no accessibility semantics by itself —
        # PDF/UA does not require it and no screen reader announces "bold".  It
        # is a fidelity improvement and a place to hang /Lang or /ActualText on
        # a sub-paragraph run later.  It deliberately does NOT reproduce the
        # <StyleSpan>/<ParagraphSpan> wrappers a Word export also leaves behind
        # (in the reference file, 43 of 55 wrap nothing but an already-tagged
        # <Link>), since those add elements without adding meaning.
        #
        # Runs after 5.96 for the same reason as 5.965/5.967: it needs the
        # settled tree.
        if remediated_pdf_path and Path(remediated_pdf_path).exists():
            import subprocess as _spis, os as _osis
            _is = str(Path(__file__).parent / "inline_span_fixer.py")
            if Path(_is).exists():
                _envis = dict(_osis.environ)
                _envis["PYTHONIOENCODING"] = "utf-8"
                _outis = _strip_pdf_suffix(str(remediated_pdf_path)) + "_spn.pdf"
                _ris = _spis.run([_sys.executable, _is, remediated_pdf_path, _outis],
                                 capture_output=True, text=True, encoding="utf-8",
                                 errors="replace", timeout=300, env=_envis)
                _log(f"[JOB] inline_span_fixer rc={_ris.returncode}")
                if _ris.stdout:
                    _log(f"[JOB] inline_span_fixer out={_ris.stdout.strip()[:300]}")
                if _ris.returncode == 0 and Path(_outis).exists() and Path(_outis).stat().st_size > 0:
                    remediated_pdf_path = _outis
                elif _ris.returncode != 0:
                    _log(f"[JOB] inline_span_fixer stderr={_ris.stderr[-500:]!r}")

        # ── 5.97 Final contrast pass (WCAG 1.4.3) ─────────────────────
        # contrast_fixer also runs in-process inside _save_remediated_pdf, but
        # that is BEFORE badge_remover / the artifact stages rewrite content
        # streams. Re-running it here on the delivered file is idempotent (a
        # colour that already passes is left alone) and guarantees the shipped
        # PDF is the one that was actually checked.
        if remediated_pdf_path and Path(remediated_pdf_path).exists():
            try:
                from .contrast_fixer import fix_text_contrast as _ftc
                _cstats = _ftc(str(remediated_pdf_path),
                               known_text_colors=context.get("_contrast_known_text_colors"))
                _log(f"[JOB] final contrast pass changes={_cstats.get('total_changes')} "
                     f"manual_review={_cstats.get('skipped_bg_colors')}")
            except Exception as _ce:
                _log(f"[JOB] final contrast pass ERROR: {_ce}")

        # ── 5.97 Strip visible PDFix trial watermark stamp ────────────
        # PDFix stamps a grey circle Form XObject (Alt="Trial version of
        # PDFix SDK | www.pdfix.net") onto the page content at Save() -- a
        # VISIBLE defect that covers real text on ~4 pages. Remove it here,
        # before the producer-metadata fix and before final validation.
        # Non-fatal and idempotent (safe if already clean).
        if remediated_pdf_path and Path(remediated_pdf_path).exists():
            try:
                from .pdfix_watermark_stripper import strip_watermark
                _wm = strip_watermark(str(remediated_pdf_path))
                _log(f"[JOB] watermark_stripper pages={_wm.get('pages')} "
                     f"blocks_removed={_wm.get('artifact_blocks_removed')}")
            except Exception as _we:
                _log(f"[JOB] watermark_stripper ERROR: {_we}")

        # ── 5.98 Strip PDFix trial marker from Producer metadata ──────
        # The PDFix SDK stamps "Trial version of PDFix SDK | www.pdfix.net"
        # into /Producer at its Save() (inside _save_remediated_pdf). Every
        # pikepdf save after that only carries the string forward -- nothing
        # re-stamps it -- so clearing it HERE, as the last mutation before the
        # read-only final validation, guarantees the delivered file is clean.
        # Metadata is cosmetic: a failure here must never fail the job, and the
        # call is idempotent (safe if Producer is already clean).
        if remediated_pdf_path and Path(remediated_pdf_path).exists():
            try:
                from .producer_metadata_fixer import strip_producer
                _pr = strip_producer(str(remediated_pdf_path),
                                     producer="Orion Accessibility Engine")
                _log(f"[JOB] producer_metadata_fixer docinfo={_pr.get('docinfo')} "
                     f"xmp={_pr.get('xmp')} old={_pr.get('old')!r}")
            except Exception as _pe:
                _log(f"[JOB] producer_metadata_fixer ERROR: {_pe}")

        # ── 5.99 Semantic QA linter (report-only) ─────────────────────
        # PAC/veraPDF verify STRUCTURE (Alt exists, heading nesting legal) but
        # cannot see that an Alt says "h C a p t e r 2", that a heading is a
        # numbered list item, or that text is mojibake. The linter runs those
        # semantic checks on the FINAL delivered file and writes <stem>_qa.json
        # and <stem>_qa.html next to it. REPORT-ONLY: it never mutates the PDF,
        # so it is always safe to run. Disable with ORION_QA_LINT=0.
        context["qa_report_paths"] = {}
        if (remediated_pdf_path and Path(remediated_pdf_path).exists()
                and _os.environ.get("ORION_QA_LINT", "1").strip().lower()
                not in ("0", "false", "no", "off")):
            try:
                from .accessibility_linter import lint as _qa_lint, write_reports as _qa_write
                _qa_stem = str(Path(str(remediated_pdf_path)).with_suffix(""))
                _qa_json = _qa_stem + "_qa.json"
                _qa_html = _qa_stem + "_qa.html"
                _qa_res = _qa_lint(str(remediated_pdf_path))
                _qa_write(_qa_res, _qa_json, _qa_html)
                _qs = _qa_res.get("summary", {})
                context["qa_report_paths"] = {"json": _qa_json, "html": _qa_html}
                _log(f"[JOB] qa_linter errors={_qs.get('errors', 0)} "
                     f"warnings={_qs.get('warnings', 0)} info={_qs.get('info', 0)} "
                     f"autofixable={_qs.get('autofixable', 0)} "
                     f"by_category={_qs.get('by_category', {})} -> {_qa_html}")
            except Exception as _qe:
                _log(f"[JOB] qa_linter ERROR: {_qe}")

        # ── 6. Persist result in job_store ────────────────────────────
        summary = pipeline_result.get("summary", {})
        initial = pipeline_result.get("validation_result", {})
        revalidation = pipeline_result.get("revalidation_result", {})

        # The revalidation above was captured INSIDE pipeline.run(), i.e. BEFORE
        # steps 3-5 (badge_remover ... heading_normalizer ... struct_parent_fixer)
        # had run.  Those stages materially change the structure tree -- e.g.
        # heading_normalizer collapses the 8 per-page banner <H1>s that Word
        # emits down to a single document <H1>.  Reporting the pre-post-process
        # snapshot therefore describes a file the user never receives: the
        # dashboard claimed "8 H1 headings (expected exactly 1)" while the
        # delivered PDF actually contained exactly 1.
        #
        # Re-validate the FINAL artefact so the report describes the file that
        # is actually downloaded. If this pass fails for any reason we fall back
        # to the earlier snapshot rather than losing the report entirely.
        if remediated_pdf_path and Path(remediated_pdf_path).exists():
            try:
                _log(f"[JOB] {job_id} final validation on delivered file ...")
                _final_ctx = dict(context)
                _final_ctx["pdf_doc_path"] = str(remediated_pdf_path)
                _final_ctx.pop("_cache", None)      # never reuse a stale scan
                _final_doc = None
                try:
                    from pdfixsdk.Pdfix import GetPdfix
                    _pdfix = GetPdfix()
                    _final_doc = _pdfix.OpenDoc(str(remediated_pdf_path), "")
                except Exception as _e:
                    _log(f"[JOB] final validation: PDFix reopen failed ({_e})")
                if _final_doc:
                    _final_ctx["pdf_doc"] = _final_doc

                _final = AccessibilityRemediationPipeline().validator_pipeline.run(
                    organization_id=organization_id,
                    project_id=project_id,
                    context=_final_ctx,
                )
                if _final and _final.get("issues") is not None:
                    revalidation = _final
                    _log(f"[JOB] {job_id} final validation done | "
                         f"total_issues={_final.get('total_issues', 0)}")
                if _final_doc:
                    try:
                        _final_doc.Close()
                    except Exception:
                        pass
            except Exception as _e:
                _log(f"[JOB] final validation failed, keeping earlier snapshot: {_e}")

       

        def _build_issues(init, reval, rem_results):
            detected = [
                {"rule_id": i.get("rule_id"), "severity": i.get("severity"),
                 "category": i.get("category"), "agent": i.get("agent_name"),
                 "message": i.get("message"), "recommendation": i.get("recommendation"),
                 "auto_fixable": i.get("auto_fixable", False)}
                for i in init.get("issues", []) if i.get("status") == "FAIL"
            ]

            # Build remaining from revalidation first — this is the ground truth.
            remaining = [
                {"rule_id": i.get("rule_id"), "severity": i.get("severity"),
                 "category": i.get("category"), "agent": i.get("agent_name"),
                 "message": i.get("message"), "recommendation": i.get("recommendation")}
                for i in reval.get("issues", []) if i.get("status") == "FAIL"
            ]
            remaining_rule_ids = {r["rule_id"] for r in remaining}

            # Reconcile: a rule is only truly "fixed" if revalidation no longer flags it.
            fixed, failed_to_fix = [], []
            for r in rem_results:
                rule_id = r.get("rule_id")
                if r.get("success") and rule_id not in remaining_rule_ids:
                    fixed.append({"rule_id": rule_id, "agent": r.get("agent_name"),
                                  "action": r.get("action"), "changes_made": r.get("changes_made", [])})
                elif r.get("success") and rule_id in remaining_rule_ids:
                    # Fix was applied but revalidation still reports the issue — treat as not fixed.
                    failed_to_fix.append({
                        "rule_id": rule_id, "agent": r.get("agent_name"),
                        "action": r.get("action"),
                        "error": "Fix was applied but issue persists after revalidation",
                    })
                else:
                    failed_to_fix.append({"rule_id": rule_id, "agent": r.get("agent_name"),
                                          "action": r.get("action"), "error": r.get("error")})

            return {"detected": detected, "fixed": fixed,
                    "failed_to_fix": failed_to_fix, "remaining": remaining}

        job_store[job_id].update({
            "status": "completed",
            "filename": filename,
            "remediated_pdf_path": remediated_pdf_path,
            "summary": summary,
            "validation_result": initial,
            "revalidation_result": revalidation,
            "remediation_results": pipeline_result.get("remediation_results", []),
            "issues": _build_issues(initial, revalidation, pipeline_result.get("remediation_results", [])),
            "error": None,
        })
        _log(f"[JOB] {job_id} COMPLETED — fixed={summary.get('issues_fixed', 0)}")

    except Exception as exc:
        import traceback
        _log(f"[JOB] {job_id} FAILED: {exc}\n{traceback.format_exc()}")
        job_store[job_id].update({"status": "failed", "error": str(exc)})

    finally:
        # The pipeline internally closes the original pdf_doc and reopens a new one
        # from the remediated file, storing it in context["pdf_doc"].
        # Closing the original pdf_doc here would double-close it -> PDFix segfault.
        # Close whichever doc is currently live in context instead.
        doc_to_close = context.get("pdf_doc")
        if doc_to_close:
            try:
                doc_to_close.Close()
            except Exception:
                pass
        if tmp_path:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass
