"""
accessibility_router.py – FastAPI router for Orion Accessibility Plus module.

Endpoint summary
----------------
POST /master_accessibility_check               upsert master checks (JSON)
GET  /master_accessibility_check               list all master checks
POST /master_accessibility_check/upload        upsert from Excel
POST /master_accessibility_check/clone         clone master checks to org/project
GET  /master_accessibility_check/OrganizationWiseTemplate/{org_id}

POST /validate-pdf                             VeraPDF validation
POST /orion-validate-pdf                       Orion agent-based validation
POST /orion-remediate-pdf                      Orion full remediation pipeline  ← see below

GET  /remediation-status/{job_id}              poll remediation job status
GET  /download-remediated-pdf/{job_id}         download remediated PDF

/orion-remediate-pdf uses AccessibilityRemediationPipeline (NOT RemediatorService).
RemediatorService is internal plumbing consumed by the pipeline; the API layer
must never call it directly because it only handles a single pre-validated issue
and knows nothing about files, PDFix lifecycle, save, or job tracking.
"""

import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.logger import get_logger
from src.core.response import APIResponse, build_response
from src.modules.accessibility_plus.engines.accesibility_engine_pipeline import (
    AccessibilityEnginePipeline,
)
from src.modules.accessibility_plus.engines.accessibility_remediation_pipeline import (
    AccessibilityRemediationPipeline,
)
from src.modules.accessibility_plus.engines.audit_template_engine import AccessiblilityAudit
from src.modules.accessibility_plus.engines.pdfix_service import PDFixService
from src.modules.accessibility_plus.engines.VeraPDF import VeraPDF
from src.modules.accessibility_plus.models.master_accessibility_model import (
    MasterAccessibilityModel,
)


# ---------------------------------------------------------------------------
# Issues node builder
# ---------------------------------------------------------------------------

def _build_issues_node(
    initial: dict,
    revalidation: dict,
    remediation_results: list,
) -> dict:
    """Build a structured 'issues' node for the API response.

    Sections
    --------
    detected      – every FAIL found in the initial validation scan
    fixed         – remediations that succeeded (success=True)
    failed_to_fix – remediations that were attempted but failed (success=False)
    remaining     – every FAIL still present after remediation (from revalidation)
    """

    # ── detected: initial FAILs ──────────────────────────────────────────
    detected = [
        {
            "rule_id":       i.get("rule_id"),
            "severity":      i.get("severity"),
            "category":      i.get("category"),
            "agent":         i.get("agent_name"),
            "message":       i.get("message"),
            "recommendation": i.get("recommendation"),
            "auto_fixable":  i.get("auto_fixable", False),
        }
        for i in initial.get("issues", [])
        if i.get("status") == "FAIL"
    ]

    # ── fixed / failed_to_fix: split remediation results ────────────────
    fixed = []
    failed_to_fix = []
    for r in remediation_results:
        if r.get("success"):
            fixed.append({
                "rule_id":      r.get("rule_id"),
                "agent":        r.get("agent_name"),
                "action":       r.get("action"),
                "changes_made": r.get("changes_made", []),
            })
        else:
            failed_to_fix.append({
                "rule_id": r.get("rule_id"),
                "agent":   r.get("agent_name"),
                "action":  r.get("action"),
                "error":   r.get("error"),
            })

    # ── remaining: revalidation FAILs ────────────────────────────────────
    remaining = [
        {
            "rule_id":        i.get("rule_id"),
            "severity":       i.get("severity"),
            "category":       i.get("category"),
            "agent":          i.get("agent_name"),
            "message":        i.get("message"),
            "recommendation": i.get("recommendation"),
        }
        for i in revalidation.get("issues", [])
        if i.get("status") == "FAIL"
    ]

    return {
        "detected":      detected,
        "fixed":         fixed,
        "failed_to_fix": failed_to_fix,
        "remaining":     remaining,
    }

router = APIRouter()
logger = get_logger(__name__)

# File-based debug logger (works even when Uvicorn swallows stdout)
import sys as _sys
from pathlib import Path as _Path
_RLOG = _Path(__file__).parent.parent.parent.parent.parent / "pipeline_debug.log"

def _rdlog(*args, **kwargs):
    msg = "[ROUTER] " + " ".join(str(a) for a in args)
    try:
        with open(_RLOG, "a", encoding="utf-8") as _f:
            _f.write(msg + "\n")
    except Exception:
        pass
    print(msg, file=_sys.stderr)

_rdlog(f"ROUTER MODULE LOADED — log at {_RLOG}")
# Version marker — write to encoding_fix.log so we can confirm THIS file is loaded
try:
    _marker = _RLOG.parent / "encoding_fix.log"
    with open(str(_marker), "w", encoding="utf-8") as _mf:
        _mf.write(f"[ROUTER] VERSION_8 loaded from: {__file__}\nlog: {_RLOG}\n")
except Exception as _me:
    _rdlog(f"ROUTER marker write failed: {_me}")

accessibility_audit_engine = AccessiblilityAudit()
vera_pdf_engine = VeraPDF()
pdfix_service = PDFixService()

# ---------------------------------------------------------------------------
# In-memory job store  (replace with Redis / DB table for production)
# ---------------------------------------------------------------------------
# Schema per job_id:
#   {
#       "job_id": str,
#       "status": "completed" | "failed",
#       "filename": str,
#       "remediated_pdf_path": str | None,
#       "summary": dict,
#       "validation_result": dict,
#       "revalidation_result": dict,
#       "remediation_results": list,
#       "error": str | None,
#       "created_at": str,
#   }
_job_store: dict[str, dict[str, Any]] = {}


def get_accessibility_pipeline() -> AccessibilityEnginePipeline:
    """Fresh validator-only pipeline instance (always picks up latest config)."""
    return AccessibilityEnginePipeline()


def get_remediation_pipeline() -> AccessibilityRemediationPipeline:
    """Fresh full remediation pipeline instance."""
    return AccessibilityRemediationPipeline()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class MasterChecksUpsertResponse(BaseModel):
    inserted: int
    updated: int
    skipped: int
    total: int


class MasterAccessibilityCheckRequest(BaseModel):
    check_id: int | None = None
    check_code: str
    check_name: str
    description: str | None = None
    category: str
    default_priority: Literal["HIGH", "MEDIUM", "LOW"]
    wcag_reference: str | None = None
    pdfua_reference: str | None = None
    remediation_guidance: str | None = None
    agent_code: str | None = None
    is_active: bool = True


class MasterAccessibilityChecksBulkRequest(BaseModel):
    rows: list[MasterAccessibilityCheckRequest]


class CloneMasterChecksRequest(BaseModel):
    organization_id: int
    project_id: str | None = None


class CloneMasterChecksResponse(BaseModel):
    inserted: int
    updated: int
    total: int


class MasterAccessibilityCheckResponse(BaseModel):
    check_id: int
    check_code: str
    check_name: str
    description: str | None = None
    category: str
    default_priority: Literal["HIGH", "MEDIUM", "LOW"]
    wcag_reference: str | None = None
    pdfua_reference: str | None = None
    remediation_guidance: str | None = None
    agent_code: str | None = None
    is_active: bool
    created_at: datetime | None = None


class MasterAccessibilityChecksListResponse(BaseModel):
    total: int
    checks: list[MasterAccessibilityCheckResponse]


# ---------------------------------------------------------------------------
# Master check endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/master_accessibility_check",
    status_code=status.HTTP_200_OK,
    response_model=MasterChecksUpsertResponse,
)
async def upsert_master_accessibility_check_json(
    payload: MasterAccessibilityChecksBulkRequest,
):
    try:
        rows = [
            row.model_dump() if hasattr(row, "model_dump") else row.dict()
            for row in payload.rows
        ]
        result = accessibility_audit_engine.upsert_master_checks_json(rows)
        return MasterChecksUpsertResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to process JSON rows") from exc


@router.get(
    "/master_accessibility_check",
    status_code=status.HTTP_200_OK,
    response_model=MasterAccessibilityChecksListResponse,
)
def get_all_master_accessibility_checks(db: Session = Depends(get_db)):
    try:
        checks = (
            db.query(MasterAccessibilityModel)
            .order_by(MasterAccessibilityModel.check_id.asc())
            .all()
        )
        return MasterAccessibilityChecksListResponse(
            total=len(checks),
            checks=[MasterAccessibilityCheckResponse(**c.to_dict()) for c in checks],
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail="Failed to fetch master accessibility checks"
        ) from exc


@router.post(
    "/master_accessibility_check/upload",
    status_code=status.HTTP_200_OK,
    response_model=MasterChecksUpsertResponse,
)
async def upload_master_accessibility_check_excel(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="File name is required")
    if not (file.filename.endswith(".xlsx") or file.filename.endswith(".xlsm")):
        raise HTTPException(status_code=400, detail="Only .xlsx/.xlsm files are supported")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        result = accessibility_audit_engine.upload_master_checks_excel(file_bytes)
        return MasterChecksUpsertResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to process Excel file") from exc


@router.post(
    "/master_accessibility_check/clone",
    status_code=status.HTTP_200_OK,
    response_model=CloneMasterChecksResponse,
)
async def clone_master_accessibility_checks(payload: CloneMasterChecksRequest):
    try:
        payload_data = (
            payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
        )
        result = accessibility_audit_engine.clone_master_checks(payload_data)
        return CloneMasterChecksResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail="Failed to clone master accessibility checks"
        ) from exc


@router.get(
    "/master_accessibility_check/OrganizationWiseTemplate/{organization_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse,
)
async def fetch_organization_wise_accessibility_checks(organization_id: int):
    try:
        result = accessibility_audit_engine.fetch_organization_wise_checks(organization_id)
        return build_response(
            response_code=status.HTTP_200_OK,
            message="Organization wise accessibility checks fetched successfully",
            data=result,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Failed to fetch organization wise accessibility checks",
        ) from exc


# ---------------------------------------------------------------------------
# VeraPDF validation
# ---------------------------------------------------------------------------

@router.post(
    "/validate-pdf",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse,
)
async def validate_pdf(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="File name is required")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only .pdf files are supported")

    file_bytes = await file.read()
    try:
        result = vera_pdf_engine.validate_pdf(file_bytes=file_bytes, filename=file.filename)
        return build_response(
            response_code=status.HTTP_200_OK,
            message="PDF validated successfully",
            data=result,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to validate PDF: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Orion agent-based validation (validate only, no fixes)
# ---------------------------------------------------------------------------

@router.post(
    "/orion-validate-pdf",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse,
)
async def orion_validate_pdf(
    file: UploadFile = File(...),
    organization_id: int | None = None,
    project_id: str | None = None,
):
    """Run all accessibility agent checks on the uploaded PDF (read-only)."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="File name is required")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only .pdf files are supported")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    logger.info(
        "orion-validate-pdf | org=%s project=%s file=%s bytes=%s",
        organization_id, project_id, file.filename, len(file_bytes),
    )

    pdfix_module = pdfix_service._load_pdfix_module()
    pdfix = pdfix_module.GetPdfix()
    if not pdfix:
        raise HTTPException(status_code=500, detail="Unable to initialize PDFix SDK")

    tmp_path: str | None = None
    pdf_doc = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        pdf_doc = pdfix.OpenDoc(tmp_path, "")
        if not pdf_doc:
            raise ValueError("Failed to open PDF document with PDFix")

        context: dict[str, Any] = {
            "pdf_doc": pdf_doc,
            "pdf_doc_path": tmp_path,
            "document_name": file.filename,
            "total_pages": pdf_doc.GetNumPages() if hasattr(pdf_doc, "GetNumPages") else 0,
            "file_size_bytes": len(file_bytes),
        }

        pipeline = get_accessibility_pipeline()
        result = pipeline.run(
            organization_id=organization_id,
            project_id=project_id,
            context=context,
        )

        logger.info(
            "orion-validate-pdf done | org=%s project=%s total_issues=%s",
            organization_id, project_id, result.get("total_issues"),
        )
        return build_response(
            response_code=status.HTTP_200_OK,
            message="PDF validated successfully",
            data=result,
        )

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("orion-validate-pdf failed | org=%s project=%s", organization_id, project_id)
        raise HTTPException(status_code=500, detail=f"Failed to validate PDF: {exc}") from exc
    finally:
        if pdf_doc:
            try:
                pdf_doc.Close()
            except Exception:
                pass
        if tmp_path:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Orion remediation pipeline  ← USES AccessibilityRemediationPipeline
# ---------------------------------------------------------------------------

@router.post(
    "/orion-remediate-pdf",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse,
)
async def orion_remediate_pdf(
    file: UploadFile = File(...),
    organization_id: int | None = None,
    project_id: str | None = None,
):
    """
    Validate → auto-remediate → re-validate a PDF document.

    Uses ``AccessibilityRemediationPipeline`` (NOT ``RemediatorService``).

    ``RemediatorService`` is internal plumbing that handles a single
    pre-validated issue dict; it has no file I/O, PDFix lifecycle
    management, or job tracking.  The pipeline is the correct public
    boundary for an API endpoint.

    Returns
    -------
    JSON with:
        job_id              – UUID for polling / download
        status              – "completed" | "failed"
        issues_detected     – count from initial validation
        issues_fixed        – count of successful remediations
        issues_remaining    – count from re-validation
        auto_fixable_count  – how many issues were auto-fixable
        download_url        – GET this to download the remediated PDF
        report_url          – GET this to fetch the full report
        summary             – pipeline summary block
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="File name is required")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only .pdf files are supported")

    _rdlog(" orion-remediate-pdf HIT")
    file_bytes = await file.read()
    _rdlog(f" file read: {len(file_bytes)} bytes")
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    job_id = uuid.uuid4().hex
    _rdlog(f" job_id={job_id}")
    logger.info(
        "orion-remediate-pdf | job=%s org=%s project=%s file=%s bytes=%s",
        job_id, organization_id, project_id, file.filename, len(file_bytes),
    )

    _rdlog(" loading PDFix module ...")
    pdfix_module = pdfix_service._load_pdfix_module()
    _rdlog(f" pdfix_module={pdfix_module}")
    pdfix = pdfix_module.GetPdfix()
    _rdlog(f" pdfix={pdfix}")
    if not pdfix:
        _rdlog(" ERROR: pdfix is None")
        raise HTTPException(status_code=500, detail="Unable to initialize PDFix SDK")

    tmp_path: str | None = None
    pdf_doc = None
    try:
        _rdlog(" writing PDF to temp file ...")
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        _rdlog(f" tmp_path={tmp_path}")

        _rdlog(" opening PDF with PDFix ...")
        pdf_doc = pdfix.OpenDoc(tmp_path, "")
        _rdlog(f" pdf_doc={pdf_doc}")
        if not pdf_doc:
            raise ValueError("Failed to open PDF document with PDFix")

        context: dict[str, Any] = {
            "pdf_doc": pdf_doc,
            "pdf_doc_path": tmp_path,
            "document_name": file.filename,
            "total_pages": pdf_doc.GetNumPages() if hasattr(pdf_doc, "GetNumPages") else 0,
            "file_size_bytes": len(file_bytes),
        }
        _rdlog(f" context ready: tmp_path={tmp_path} pages={context['total_pages']}")

        # ── Run the full pipeline ─────────────────────────────────────
        _rdlog(" creating pipeline ...")
        pipeline = get_remediation_pipeline()
        _rdlog(" calling pipeline.run() ...")
        pipeline_result = pipeline.run(
            organization_id=organization_id,
            project_id=project_id,
            context=context,
        )

        summary = pipeline_result.get("summary", {})
        initial = pipeline_result.get("validation_result", {})
        revalidation = pipeline_result.get("revalidation_result", {})
        remediated_pdf_path = pipeline_result.get("remediated_pdf_path")

        # ── Apply /ToUnicode encoding fix on the intermediary PDF ──────────
        _enc_log = str(Path(__file__).resolve().parent.parent.parent.parent.parent / "encoding_fix.log")
        with open(_enc_log, "a", encoding="utf-8") as _lf:
            _lf.write(f"[REMEDIATE HIT] remediated_pdf_path={remediated_pdf_path!r}\n")
            _lf.write(f"[REMEDIATE HIT] pipeline_result keys={list(pipeline_result.keys()) if pipeline_result else 'NONE'}\n")
            _lf.write(f"[REMEDIATE HIT] exists={Path(remediated_pdf_path).exists() if remediated_pdf_path else 'N/A'}\n")
        if remediated_pdf_path and Path(remediated_pdf_path).exists():
            import subprocess as _sp3, sys as _sys3
            _fixer3 = str(Path(__file__).resolve().parent.parent / "engines" / "font_encoding_fixer.py")
            _enc_out = str(Path(remediated_pdf_path).with_suffix(".enc.pdf"))
            with open(_enc_log, "a", encoding="utf-8") as _lf:
                _lf.write(f"fix start: {_fixer3}\ninput: {remediated_pdf_path}\noutput: {_enc_out}\n")
            _r3 = _sp3.run(
                [_sys3.executable, _fixer3, remediated_pdf_path, _enc_out],
                capture_output=True, text=True, timeout=120
            )
            with open(_enc_log, "a", encoding="utf-8") as _lf:
                _lf.write(f"returncode: {_r3.returncode}\nstdout: {_r3.stdout}\nstderr: {_r3.stderr}\n")
            if _r3.returncode == 0 and Path(_enc_out).exists() and Path(_enc_out).stat().st_size > 0:
                remediated_pdf_path = _enc_out
                pipeline_result["remediated_pdf_path"] = _enc_out
            else:
                with open(_enc_log, "a", encoding="utf-8") as _lf:
                    _lf.write("FALLBACK: serving original\n")

        # ---- Step 2: Remove PDFix visual badge overlays ----------------------
        import subprocess as _sp6, sys as _sys6, os as _os6
        _badge_fixer = str(Path(__file__).resolve().parent.parent / "engines" / "badge_remover.py")
        if Path(_badge_fixer).exists():
            _env6 = dict(_os6.environ)
            _env6["PYTHONIOENCODING"] = "utf-8"
            _badge_in = str(remediated_pdf_path)
            _badge_base = _badge_in
            for _suf6 in ("_ann.pdf", "_alt.pdf", ".enc.pdf", ".pdf"):
                if _badge_base.endswith(_suf6):
                    _badge_base = _badge_base[:-len(_suf6)]
                    break
            _badge_out = _badge_base + "_clean.pdf"
            with open(_enc_log, "a", encoding="utf-8") as _lf:
                _lf.write(f"[BADGE-FIX] input={_badge_in!r} output={_badge_out!r}\n")
            _r6 = _sp6.run(
                [_sys6.executable, _badge_fixer, _badge_in, _badge_out],
                capture_output=True, text=True, timeout=120, env=_env6
            )
            with open(_enc_log, "a", encoding="utf-8") as _lf:
                _lf.write(f"[BADGE-FIX] returncode={_r6.returncode}\n")
                _lf.write(f"[BADGE-FIX] stdout={_r6.stdout}\n")
                if _r6.stderr.strip():
                    _lf.write(f"[BADGE-FIX] stderr={_r6.stderr}\n")
            if _r6.returncode == 0 and Path(_badge_out).exists() and Path(_badge_out).stat().st_size > 0:
                remediated_pdf_path = _badge_out
                pipeline_result["remediated_pdf_path"] = _badge_out
                with open(_enc_log, "a", encoding="utf-8") as _lf:
                    _lf.write(f"[BADGE-FIX] SUCCESS -> {_badge_out}\n")
            else:
                with open(_enc_log, "a", encoding="utf-8") as _lf:
                    _lf.write("[BADGE-FIX] FALLBACK: keeping previous pdf\n")
        else:
            with open(_enc_log, "a", encoding="utf-8") as _lf:
                _lf.write(f"[BADGE-FIX] fixer not found at {_badge_fixer!r} -- skipping\n")

        # ---- Step 3: Fix tagged annotations ---------------------------------
        import subprocess as _sp5, sys as _sys5, os as _os5
        _ann_fixer = str(Path(__file__).resolve().parent.parent / "engines" / "tagged_annotations_fixer.py")
        if Path(_ann_fixer).exists():
            _env5 = dict(_os5.environ)
            _env5["PYTHONIOENCODING"] = "utf-8"
            _ann_in = str(remediated_pdf_path)
            _ann_base = _ann_in
            for _suf5 in ("_clean.pdf", "_alt.pdf", ".enc.pdf", ".pdf"):
                if _ann_base.endswith(_suf5):
                    _ann_base = _ann_base[:-len(_suf5)]
                    break
            _ann_out = _ann_base + "_ann.pdf"
            with open(_enc_log, "a", encoding="utf-8") as _lf:
                _lf.write(f"[ANN-FIX] input={_ann_in!r} output={_ann_out!r}\n")
            _r5 = _sp5.run(
                [_sys5.executable, _ann_fixer, _ann_in, _ann_out],
                capture_output=True, text=True, timeout=120, env=_env5
            )
            with open(_enc_log, "a", encoding="utf-8") as _lf:
                _lf.write(f"[ANN-FIX] returncode={_r5.returncode}\n")
                _lf.write(f"[ANN-FIX] stdout={_r5.stdout}\n")
                if _r5.stderr.strip():
                    _lf.write(f"[ANN-FIX] stderr={_r5.stderr}\n")
            if _r5.returncode == 0 and Path(_ann_out).exists() and Path(_ann_out).stat().st_size > 0:
                remediated_pdf_path = _ann_out
                pipeline_result["remediated_pdf_path"] = _ann_out
                with open(_enc_log, "a", encoding="utf-8") as _lf:
                    _lf.write(f"[ANN-FIX] SUCCESS -> {_ann_out}\n")
            else:
                with open(_enc_log, "a", encoding="utf-8") as _lf:
                    _lf.write("[ANN-FIX] FALLBACK: keeping previous pdf\n")
        else:
            with open(_enc_log, "a", encoding="utf-8") as _lf:
                _lf.write(f"[ANN-FIX] fixer not found at {_ann_fixer!r} -- skipping\n")


        # ── Step 4: Apply Alternate Text fix via Claude vision API (runs LAST — nothing touches structure tree after this) ──
        if remediated_pdf_path and Path(remediated_pdf_path).exists():
            import subprocess as _sp4, sys as _sys4, os as _os4
            _alt_fixer = str(Path(__file__).resolve().parent.parent / "engines" / "run_fix_alt_text.py")
            _alt_base = str(Path(remediated_pdf_path))
            if _alt_base.endswith("_ann.pdf"):
                _alt_out = _alt_base[:-len("_ann.pdf")] + "_alt.pdf"
            elif _alt_base.endswith("_clean.pdf"):
                _alt_out = _alt_base[:-len("_clean.pdf")] + "_alt.pdf"
            elif _alt_base.endswith(".enc.pdf"):
                _alt_out = _alt_base[:-len(".enc.pdf")] + "_alt.pdf"
            elif _alt_base.endswith(".pdf"):
                _alt_out = _alt_base[:-4] + "_alt.pdf"
            else:
                _alt_out = _alt_base + "_alt.pdf"
            _env4 = dict(_os4.environ)
            _env4["PYTHONIOENCODING"] = "utf-8"
            # If api key not in env, try loading from .env file
            # Handles "orion-clude-key" typo and both "=" and ":" separators
            if not _env4.get("orion-claude-key"):
                try:
                    _dotenv_path = Path(__file__).resolve().parent.parent.parent.parent.parent / ".env"
                    if _dotenv_path.exists():
                        for _line in _dotenv_path.read_text(encoding="utf-8").splitlines():
                            _line = _line.strip()
                            if not _line or _line.startswith("#"):
                                continue
                            if "orion-" in _line.lower() and "key" in _line.lower():
                                for _sep in ("=", ":"):
                                    if _sep in _line:
                                        _v = _line.split(_sep, 1)[1].strip().strip('"').strip("'")
                                        if _v:
                                            _env4["orion-claude-key"] = _v
                                            with open(_enc_log, "a", encoding="utf-8") as _lf:
                                                _lf.write(f"[ALT-FIX] api_key loaded from .env\n")
                                        break
                except Exception as _e:
                    with open(_enc_log, "a", encoding="utf-8") as _lf:
                        _lf.write(f"[ALT-FIX] .env read error: {_e}\n")
            with open(_enc_log, "a", encoding="utf-8") as _lf:
                _lf.write(f"[ALT-FIX] input={remediated_pdf_path!r} output={_alt_out!r}\n")
            _r4 = _sp4.run(
                [_sys4.executable, _alt_fixer, remediated_pdf_path, _alt_out],
                capture_output=True, text=True, timeout=180, env=_env4
            )
            with open(_enc_log, "a", encoding="utf-8") as _lf:
                _lf.write(f"[ALT-FIX] returncode={_r4.returncode}\n")
                _lf.write(f"[ALT-FIX] stdout={_r4.stdout}\n")
                if _r4.stderr.strip():
                    _lf.write(f"[ALT-FIX] stderr={_r4.stderr}\n")
            if _r4.returncode == 0 and Path(_alt_out).exists() and Path(_alt_out).stat().st_size > 0:
                remediated_pdf_path = _alt_out
                pipeline_result["remediated_pdf_path"] = _alt_out
                with open(_enc_log, "a", encoding="utf-8") as _lf:
                    _lf.write(f"[ALT-FIX] SUCCESS -> {_alt_out}\n")
            else:
                with open(_enc_log, "a", encoding="utf-8") as _lf:
                    _lf.write("[ALT-FIX] FALLBACK: keeping enc.pdf\n")

        # ── Persist job record so status / download endpoints work ────
        _job_store[job_id] = {
            "job_id": job_id,
            "status": "completed",
            "filename": file.filename,
            "remediated_pdf_path": remediated_pdf_path,
            "summary": summary,
            "validation_result": initial,
            "revalidation_result": revalidation,
            "remediation_results": pipeline_result.get("remediation_results", []),
            "error": None,
            "created_at": datetime.utcnow().isoformat(),
        }

        issues_node = _build_issues_node(
            initial=initial,
            revalidation=revalidation,
            remediation_results=pipeline_result.get("remediation_results", []),
        )

        response_data = {
            "job_id": job_id,
            "status": "completed",
            "issues_detected": summary.get("issues_detected", 0),
            "issues_fixed": summary.get("issues_fixed", 0),
            "issues_remaining": summary.get("issues_remaining", 0),
            "auto_fixable_count": summary.get("issues_attempted", 0),
            "save_success": summary.get("save_success", False),
            "download_url": (
                f"/api/v1/accessibility/download-remediated-pdf/{job_id}"
                if remediated_pdf_path
                else None
            ),
            "report_url": f"/api/v1/accessibility/remediation-report/{job_id}",
            "summary": summary,
            "issues": issues_node,
        }

        logger.info(
            "orion-remediate-pdf done | job=%s fixed=%s remaining=%s saved=%s",
            job_id,
            summary.get("issues_fixed", 0),
            summary.get("issues_remaining", 0),
            summary.get("save_success", False),
        )

        return build_response(
            response_code=status.HTTP_200_OK,
            message="PDF remediated successfully",
            data=response_data,
        )

    except ValueError as exc:
        import traceback
        _rdlog(f" ValueError: {exc}")
        print(traceback.format_exc())
        _job_store[job_id] = {
            "job_id": job_id,
            "status": "failed",
            "error": str(exc),
            "created_at": datetime.utcnow().isoformat(),
        }
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        import traceback
        _rdlog(f" EXCEPTION {type(exc).__name__}: {exc}")
        print(traceback.format_exc())
        _job_store[job_id] = {
            "job_id": job_id,
            "status": "failed",
            "error": str(exc),
            "created_at": datetime.utcnow().isoformat(),
        }
        logger.exception("orion-remediate-pdf failed | job=%s", job_id)
        raise HTTPException(
            status_code=500, detail=f"Failed to remediate PDF: {exc}"
        ) from exc
    finally:
        if pdf_doc:
            try:
                pdf_doc.Close()
            except Exception:
                pass
        # Only clean up the *upload* temp file; the _remediated.pdf is kept
        # for download and must not be deleted here.
        if tmp_path:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Job status / report
# ---------------------------------------------------------------------------

@router.get(
    "/remediation-status/{job_id}",
    response_model=APIResponse,
)
async def remediation_status(job_id: str):
    job = _job_store.get(job_id)
    if not job:
        raise HTTPException(
            status_code=404,
            detail=f"No remediation job found for job_id='{job_id}'",
        )
    return build_response(
        response_code=status.HTTP_200_OK,
        message="Remediation status fetched successfully",
        data={
            "job_id": job["job_id"],
            "status": job["status"],
            "error": job.get("error"),
            "summary": job.get("summary"),
            "created_at": job.get("created_at"),
        },
    )


@router.get(
    "/remediation-report/{job_id}",
    response_model=APIResponse,
)
async def remediation_report(job_id: str):
    """Return full validation + remediation + re-validation report for a job."""
    job = _job_store.get(job_id)
    if not job:
        raise HTTPException(
            status_code=404,
            detail=f"No remediation job found for job_id='{job_id}'",
        )
    return build_response(
        response_code=status.HTTP_200_OK,
        message="Remediation report fetched successfully",
        data={
            "job_id": job["job_id"],
            "status": job["status"],
            "summary": job.get("summary"),
            "validation_result": job.get("validation_result"),
            "remediation_results": job.get("remediation_results"),
            "revalidation_result": job.get("revalidation_result"),
            "created_at": job.get("created_at"),
        },
    )


# ---------------------------------------------------------------------------
# Download remediated PDF
# ---------------------------------------------------------------------------

@router.get("/download-remediated-pdf/{job_id}")
async def download_remediated_pdf(job_id: str):
    job = _job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Remediation job not found")

    pdf_path = job.get("remediated_pdf_path")
    if not pdf_path or not Path(pdf_path).exists():
        raise HTTPException(
            status_code=404,
            detail=(
                "Remediated PDF not found on disk. "
                "Either no fixes were applied or the file was already cleaned up."
            ),
        )

    original_filename = job.get("filename", "document.pdf")
    stem = Path(original_filename).stem
    download_name = f"{stem}_remediated.pdf"

    # ── /ToUnicode fix via subprocess (bypasses __pycache__ / import issues) ──
    serve_path = pdf_path
    _rdlog("[ROUTER] download: launching run_fix_encoding subprocess")
    try:
        import sys as _sys, subprocess as _sp
        _script = str(Path(__file__).parent.parent / "engines" / "run_fix_encoding.py")
        patched_path = str(Path(pdf_path).with_suffix(".tounicode.pdf"))
        _rdlog(f"[ROUTER] download: script={_script!r}  input={pdf_path!r}  output={patched_path!r}")
        _proc = _sp.run(
            [_sys.executable, _script, pdf_path, patched_path],
            capture_output=True, text=True, timeout=120
        )
        _rdlog(f"[ROUTER] download: subprocess returncode={_proc.returncode}")
        _rdlog(f"[ROUTER] download: subprocess stdout={_proc.stdout.strip()!r}")
        if _proc.stderr.strip():
            _rdlog(f"[ROUTER] download: subprocess stderr={_proc.stderr.strip()!r}")
        if _proc.returncode == 0 and Path(patched_path).exists() and Path(patched_path).stat().st_size > 0:
            serve_path = patched_path
            logger.info("download: ToUnicode patched → %s", patched_path)
        else:
            _rdlog("[ROUTER] download: subprocess failed or no output — serving original")
    except Exception as _tu_exc:
        import traceback as _tb
        _rdlog(f"[ROUTER] download: subprocess ERROR: {_tu_exc}\n{_tb.format_exc()}")
        logger.warning("download: inject_tounicode failed: %s", _tu_exc, exc_info=True)
    return FileResponse(
        path=serve_path,
        media_type="application/pdf",
        filename=download_name,
    )
