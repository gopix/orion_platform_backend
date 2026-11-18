"""
accessibility_router.py – FastAPI router for Orion Accessibility Plus module.

All pipeline/remediation logic lives in accessibility_remediation_pipeline.py.
This file handles HTTP only: parse request, queue job, return response.

POST /orion-remediate-pdf          Start job -> 202 with job_id
GET  /remediation-status/{job_id}  Poll; full JSON when completed
GET  /remediation-report/{job_id}  Full validation + remediation report
GET  /download-remediated-pdf/{job_id}  Download fixed PDF
"""

import uuid
import sys as _sys
import tempfile

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, Response
import io
import csv
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.logger import get_logger
from src.core.response import APIResponse, build_response
from src.modules.accessibility_pdf.engines.accesibility_engine_pipeline import (
    AccessibilityEnginePipeline,
)
from src.modules.accessibility_pdf.engines.accessibility_remediation_pipeline import (
    run_pipeline_job,
)
from src.modules.accessibility_pdf.engines.report_builder import RemediationReportBuilder
from src.modules.accessibility_pdf.engines.audit_template_engine import AccessiblilityAudit
from src.modules.accessibility_pdf.engines.pdfix_service import PDFixService
from src.modules.accessibility_pdf.engines.VeraPDF import VeraPDF
from src.modules.accessibility_pdf.models.master_accessibility_model import (
    MasterAccessibilityModel,
)

from src.modules.accessibility_pdf.engines.accessibility_remediation_pipeline import (
    run_pipeline_job, _dlog,          # <-- import the logger too
)



router = APIRouter()
logger = get_logger(__name__)

accessibility_audit_engine = AccessiblilityAudit()
vera_pdf_engine = VeraPDF()
pdfix_service = PDFixService()

# In-memory job store keyed by job_id.
# Replace with Redis / DB for multi-worker / persistent deployments.
_job_store: dict[str, dict[str, Any]] = {}


def _capture_accessibility_mis_record(db: Session, file_name: str, file_type: str, user_id: int | None = None) -> None:
    """Persist remediation execution metadata into accessibility_mis.

    If `user_id` is provided, use it; otherwise pick a default user from the DB.
    """
    try:
        if user_id is None:
            user_id = db.execute(text("SELECT id FROM users ORDER BY id LIMIT 1")).scalar_one_or_none()

        if not user_id:
            logger.warning("No user found; skipping accessibility_mis capture")
            return

        db.execute(
            text(
                "INSERT INTO accessibility_mis (user_id, file_executed, file_type) "
                "VALUES (:user_id, :file_executed, :file_type)"
            ),
            {"user_id": user_id, "file_executed": file_name, "file_type": file_type},
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to capture accessibility_mis record")


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

@router.post("/master_accessibility_check", status_code=status.HTTP_200_OK,
             response_model=MasterChecksUpsertResponse)
async def upsert_master_accessibility_check_json(payload: MasterAccessibilityChecksBulkRequest):
    try:
        rows = [row.model_dump() if hasattr(row, "model_dump") else row.dict() for row in payload.rows]
        result = accessibility_audit_engine.upsert_master_checks_json(rows)
        return MasterChecksUpsertResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to process JSON rows") from exc


@router.get("/master_accessibility_check", status_code=status.HTTP_200_OK,
            response_model=MasterAccessibilityChecksListResponse)
def get_all_master_accessibility_checks(db: Session = Depends(get_db)):
    try:
        checks = db.query(MasterAccessibilityModel).order_by(MasterAccessibilityModel.check_id.asc()).all()
        return MasterAccessibilityChecksListResponse(
            total=len(checks),
            checks=[MasterAccessibilityCheckResponse(**c.to_dict()) for c in checks],
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to fetch master accessibility checks") from exc


@router.post("/master_accessibility_check/upload", status_code=status.HTTP_200_OK,
             response_model=MasterChecksUpsertResponse)
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


@router.post("/master_accessibility_check/clone", status_code=status.HTTP_200_OK,
             response_model=CloneMasterChecksResponse)
async def clone_master_accessibility_checks(payload: CloneMasterChecksRequest):
    try:
        payload_data = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
        result = accessibility_audit_engine.clone_master_checks(payload_data)
        return CloneMasterChecksResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to clone master accessibility checks") from exc


@router.get("/master_accessibility_check/OrganizationWiseTemplate/{organization_id}",
            status_code=status.HTTP_200_OK, response_model=APIResponse)
async def fetch_organization_wise_accessibility_checks(organization_id: int):
    try:
        result = accessibility_audit_engine.fetch_organization_wise_checks(organization_id)
        return build_response(response_code=status.HTTP_200_OK,
                              message="Organization wise accessibility checks fetched successfully",
                              data=result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500,
                            detail="Failed to fetch organization wise accessibility checks") from exc


# ---------------------------------------------------------------------------
# VeraPDF validation
# ---------------------------------------------------------------------------

@router.post("/validate-pdf", status_code=status.HTTP_200_OK, response_model=APIResponse)
async def validate_pdf(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="File name is required")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only .pdf files are supported")
    file_bytes = await file.read()
    try:
        result = vera_pdf_engine.validate_pdf(file_bytes=file_bytes, filename=file.filename)
        return build_response(response_code=status.HTTP_200_OK,
                              message="PDF validated successfully", data=result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to validate PDF: {exc}") from exc


# ---------------------------------------------------------------------------
# Orion agent-based validation (read-only, no fixes)
# ---------------------------------------------------------------------------

@router.post("/orion-validate-pdf", status_code=status.HTTP_200_OK, response_model=APIResponse)
async def orion_validate_pdf(file: UploadFile = File(...),
                              organization_id: int | None = None,
                              project_id: str | None = None):
    if not file.filename:
        raise HTTPException(status_code=400, detail="File name is required")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only .pdf files are supported")
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    pdfix_module = pdfix_service._load_pdfix_module()
    pdfix = pdfix_module.GetPdfix()
    if not pdfix:
        raise HTTPException(status_code=500, detail="Unable to initialize PDFix SDK")

    tmp_path = None
    pdf_doc = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        pdf_doc = pdfix.OpenDoc(tmp_path, "")
        if not pdf_doc:
            raise ValueError("Failed to open PDF document with PDFix")
        context: dict[str, Any] = {
            "pdf_doc": pdf_doc, "pdf_doc_path": tmp_path,
            "document_name": file.filename,
            "total_pages": pdf_doc.GetNumPages() if hasattr(pdf_doc, "GetNumPages") else 0,
            "file_size_bytes": len(file_bytes),
        }
        pipeline = AccessibilityEnginePipeline()
        result = pipeline.run(organization_id=organization_id, project_id=project_id, context=context)
        return build_response(response_code=status.HTTP_200_OK,
                              message="PDF validated successfully", data=result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("orion-validate-pdf failed")
        raise HTTPException(status_code=500, detail=f"Failed to validate PDF: {exc}") from exc
    finally:
        if pdf_doc:
            try: pdf_doc.Close()
            except Exception: pass
        if tmp_path:
            try: Path(tmp_path).unlink(missing_ok=True)
            except Exception: pass


# ---------------------------------------------------------------------------
# POST /orion-remediate-pdf  -- queues job, capture details in accessibility-mis table,returns 202 immediately
# ---------------------------------------------------------------------------

@router.post("/orion-remediate-pdf", status_code=status.HTTP_202_ACCEPTED,
             response_model=APIResponse)
async def orion_remediate_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    organization_id: int | None = None,
    project_id: str | None = None,
    user_id: int | None = None,
    db: Session = Depends(get_db),
):
    """
    Start PDF remediation (non-blocking). Returns 202 Accepted immediately.

    Workflow:
      1. POST here -> receive job_id
      2. GET /remediation-status/{job_id} -- poll every few seconds.
         - status "pending" / "running" -> keep polling
         - status "completed" -> full result is in the response (issues, summary, download_url)
         - status "failed"    -> error message is in the response
      3. GET /download-remediated-pdf/{job_id} -> download fixed PDF
    """
    _dlog(f"[ROUTE] orion-remediate-pdf HIT | file={getattr(file, 'filename', None)} org={organization_id}")
    
    if not file.filename:
        raise HTTPException(status_code=400, detail="File name is required")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only .pdf files are supported")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    file_type = Path(file.filename).suffix.lstrip(".") or "pdf"
    _capture_accessibility_mis_record(db, file.filename, file_type, user_id=user_id)

    job_id = uuid.uuid4().hex
    _job_store[job_id] = {
        "job_id": job_id, "status": "pending", "filename": file.filename,
        "remediated_pdf_path": None, "summary": None, "validation_result": None,
        "revalidation_result": None, "remediation_results": [], "issues": None,
        "error": None, "created_at": datetime.utcnow().isoformat(),
    }

    # All pipeline logic lives in accessibility_remediation_pipeline.run_pipeline_job()
    background_tasks.add_task(
        run_pipeline_job, job_id, file_bytes, file.filename,
        organization_id, project_id, _job_store,
    )

    logger.info("orion-remediate-pdf queued | job=%s file=%s bytes=%s",
                job_id, file.filename, len(file_bytes))

    return build_response(
        response_code=status.HTTP_202_ACCEPTED,
        message="Remediation started. Poll status_url until status is completed.",
        data={
            "job_id": job_id,
            "status": "pending",
            "status_url": f"/api/v1/accessibility/remediation-status/{job_id}",
            "download_url": f"/api/v1/accessibility/download-remediated-pdf/{job_id}",
            "report_url": f"/api/v1/accessibility/remediation-report/{job_id}",
            "qa_report_url": f"/api/v1/accessibility/download-qa-report/{job_id}",
        },
    )


# ---------------------------------------------------------------------------
# GET /remediation-status/{job_id}
# ---------------------------------------------------------------------------

@router.get("/remediation-status/{job_id}", response_model=APIResponse)
async def remediation_status(job_id: str):
    """
    Poll this endpoint until status == "completed".

    Response by status
    ------------------
    pending / running  -> job_id, status, status_url, hint
    completed          -> same shape as remediation-report:
                          document, result_summary, agent_results, download_url
    failed             -> job_id, status, error, status_url
    """
    job = _job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404,
                            detail=f"No remediation job found for job_id='{job_id}'")

    job_status = job["status"]

    data: dict[str, Any] = {
        "job_id":     job["job_id"],
        "status":     job_status,
        "created_at": job.get("created_at"),
    }

    if job_status == "completed":
        issues              = job.get("issues") or {}
        validation_result   = job.get("validation_result") or {}
        revalidation_result = job.get("revalidation_result") or {}

        result_summary = RemediationReportBuilder.compute_result_summary(
            issues, pipeline_summary=job.get("summary") or {}
        )
        agent_results_view = RemediationReportBuilder.build_agent_results_view(
            initial_agent_results      = validation_result.get("agent_results", []),
            revalidation_agent_results = revalidation_result.get("agent_results", []),
        )

        data.update({
            "document": {
                "name":        validation_result.get("document_name"),
                "total_pages": validation_result.get("total_pages"),
            },
            "result_summary": result_summary,
            "agent_results":  agent_results_view,
            "download_url":   f"/api/v1/accessibility/download-remediated-pdf/{job_id}",
            "qa_report_url":  f"/api/v1/accessibility/download-qa-report/{job_id}",
        })
        msg = "Remediation completed successfully."

    elif job_status == "failed":
        data["error"]      = job.get("error")
        data["status_url"] = f"/api/v1/accessibility/remediation-status/{job_id}"
        msg = f"Remediation failed: {job.get('error') or 'unknown error'}"

    else:
        data["status_url"] = f"/api/v1/accessibility/remediation-status/{job_id}"
        data["hint"]       = "Job is in progress. Poll status_url every 3-5 seconds."
        msg = f"Remediation is {job_status}. Poll status_url for updates."

    return build_response(response_code=status.HTTP_200_OK, message=msg, data=data)


@router.get("/dashboard/{job_id}", response_model=APIResponse)
async def accessibility_dashboard(job_id: str):
    """
    Four headline KPIs for a completed remediation job — designed for
    summary cards / dashboard widgets.

    curl http://localhost:8000/api/v1/accessibility/dashboard/{job_id}

    Returns:
        dashboard.accessibility_score  — weighted PASS ratio (0–100)
        dashboard.pdfua_compliance     — % of PDF/UA rules that PASS
        dashboard.wcag_risk            — None | Low | Medium | High
        dashboard.critical_issues      — count of CRITICAL checks still FAIL/WARNING
    """
    job = _job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404,
                            detail=f"No job found for job_id='{job_id}'")

    if job["status"] != "completed":
        return build_response(
            response_code=status.HTTP_200_OK,
            message=f"Job is {job['status']} — dashboard available after completion",
            data={"job_id": job_id, "status": job["status"]},
        )

    validation = job.get("validation_result") or {}
    issues     = job.get("issues") or {}

    return build_response(
        response_code=status.HTTP_200_OK,
        message="Dashboard metrics computed successfully",
        data={
            "job_id":     job_id,
            "status":     job["status"],
            "created_at": job.get("created_at"),
            "document": {
                "name":        validation.get("document_name"),
                "total_pages": validation.get("total_pages"),
            },
            "dashboard":      RemediationReportBuilder.compute_dashboard(job),
            "result_summary": RemediationReportBuilder.compute_result_summary(
                issues, pipeline_summary=job.get("summary") or {}
            ),
        },
    )


# ---------------------------------------------------------------------------
# GET /remediation-report/{job_id}
# ---------------------------------------------------------------------------

@router.get("/remediation-report/{job_id}", response_model=APIResponse)
async def remediation_report(job_id: str):
    """
    Clean, frontend-ready remediation report.

    Response shape
    --------------
    job_id, status, created_at
    document        — document name and page count
    result_summary  — single block: overall_status, counts, timing
    agent_results   — per-agent list; each agent has agent_status + checks[];
                      each check has final_status + remediation_outcome so the
                      frontend can immediately see which issues were fixed vs
                      which still need manual attention.

    remediation_outcome values
    --------------------------
    fixed                  — Orion auto-fixed this; it is now PASS
    failed_to_fix          — Orion attempted but the check is still FAIL
    manual_review_required — not auto-fixable; requires manual intervention
    no_issue               — was already PASS before remediation
    """
    job = _job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404,
                            detail=f"No remediation job found for job_id='{job_id}'")

    is_done = job["status"] == "completed"
    issues  = job.get("issues") or {}

    result_summary   = RemediationReportBuilder.compute_result_summary(issues, pipeline_summary=job.get("summary") or {}) if is_done else None
    validation_result    = job.get("validation_result") or {}
    revalidation_result  = job.get("revalidation_result") or {}

    agent_results_view = RemediationReportBuilder.build_agent_results_view(
        initial_agent_results       = validation_result.get("agent_results", []),
        revalidation_agent_results  = revalidation_result.get("agent_results", []),
    ) if is_done else []

    return build_response(
        response_code=status.HTTP_200_OK,
        message="Remediation report fetched successfully",
        data={
            "job_id":    job["job_id"],
            "status":    job["status"],
            "created_at": job.get("created_at"),
            "document": {
                "name":        validation_result.get("document_name"),
                "total_pages": validation_result.get("total_pages"),
            },
            "result_summary": result_summary,
            "agent_results":  agent_results_view,
        },
    )


# ---------------------------------------------------------------------------
# GET /download-remediated-pdf/{job_id}
# ---------------------------------------------------------------------------

@router.get("/download-remediated-pdf/{job_id}")
async def download_remediated_pdf(job_id: str):
    job = _job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Remediation job not found")
    if job.get("status") in ("pending", "running"):
        raise HTTPException(
            status_code=409,
            detail=f"Job is still {job['status']}. Poll /remediation-status/{job_id} first.",
        )
    pdf_path = job.get("remediated_pdf_path")
    if not pdf_path or not Path(pdf_path).exists():
        raise HTTPException(status_code=404, detail="Remediated PDF not found on disk.")

    stem = Path(job.get("filename", "document.pdf")).stem
    serve_path = pdf_path
    try:
        import subprocess as _sp
        _script = str(Path(__file__).parent.parent / "engines" / "run_fix_encoding.py")
        _patched = pdf_path[:-4] + ".tounicode.pdf"
        _proc = _sp.run(
            [_sys.executable, _script, pdf_path, _patched],
            capture_output=True, text=True, timeout=120,
        )
        if _proc.returncode == 0 and Path(_patched).exists() and Path(_patched).stat().st_size > 0:
            serve_path = _patched
    except Exception as exc:
        logger.warning("download: run_fix_encoding failed: %s", exc)

    return FileResponse(path=serve_path, media_type="application/pdf",
                        filename=f"{stem}_remediated.pdf")


# ---------------------------------------------------------------------------
# GET /download-qa-report/{job_id}
# ---------------------------------------------------------------------------


@router.get(
    "/download-qa-report/{job_id}",
    response_class=FileResponse,
)
async def download_qa_report(job_id: str, format: Literal["html", "json"] = "html"):
    """Download the semantic QA-linter report for a completed job.

    The linter (accessibility_linter) is report-only: it flags issues PAC/veraPDF
    cannot see — garbled/placeholder Alt, headings that are really list items,
    mojibake, advisory spelling — and writes <stem>_qa.html / <stem>_qa.json next
    to the remediated PDF. Use ?format=html (default, human-readable) or
    ?format=json (machine-readable findings).
    """
    job = _job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Remediation job not found")
    if job.get("status") in ("pending", "running"):
        raise HTTPException(
            status_code=409,
            detail=f"Job is still {job['status']}. Poll /remediation-status/{job_id} first.",
        )
    pdf_path = job.get("remediated_pdf_path")
    if not pdf_path:
        raise HTTPException(status_code=404,
                            detail="Remediated PDF not found; no QA report available.")
    # Report is written next to the delivered PDF: <stem>_qa.{html,json}
    stem = pdf_path[:-4] if pdf_path.lower().endswith(".pdf") else pdf_path
    report_path = stem + ("_qa.json" if format == "json" else "_qa.html")
    if not Path(report_path).exists():
        raise HTTPException(
            status_code=404,
            detail="QA report not found (linter may be disabled via ORION_QA_LINT=0).",
        )
    fname_stem = Path(job.get("filename", "document.pdf")).stem
    filename = f"{fname_stem}_qa.json" if format == "json" else f"{fname_stem}_qa.html"
    media_type = "application/json" if format == "json" else "text/html"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
    }

    return FileResponse(
        path=report_path,
        media_type=media_type,
        filename=filename,
        headers=headers,
    )


# ---------------------------------------------------------------------------
# GET /accessibility-audit-template/{organization_id}
# ---------------------------------------------------------------------------


@router.get("/accessibility-audit-template/{organization_id}", response_model=APIResponse)
def get_accessibility_audit_template(organization_id: int, db: Session = Depends(get_db)):
    """Return accessibility MIS rows for an organization with user/role/org metadata."""
    try:
        sql = text(
            """
            SELECT a.id, u.user_name, u.email as user_email, o.organization_name,
                   r.role_name as role, a.file_executed, a.file_type, a.execution_time
            FROM accessibility_mis a
            JOIN users u ON a.user_id = u.id
            LEFT JOIN organizations o ON u.organization_id = o.id
            LEFT JOIN roles r ON u.role_id = r.role_id
            WHERE o.id = :organization_id
            ORDER BY a.execution_time DESC
            """
        )

        rows = db.execute(sql, {"organization_id": organization_id}).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            result.append({
                "id": row[0],
                "user_name": row[1],
                "user_email": row[2],
                "organization_name": row[3],
                "role": row[4],
                "file_executed": row[5],
                "file_type": row[6],
                "execution_time": row[7].isoformat() if row[7] is not None else None,
            })

        return build_response(
            response_code=status.HTTP_200_OK,
            message="Accessibility audit template fetched successfully",
            data=result,
        )

    except Exception as exc:
        logger.exception("Failed to fetch accessibility audit template")
        raise HTTPException(status_code=500, detail=f"Failed to fetch accessibility audit template: {exc}") from exc


@router.get(
    "/accessibility-audit-template/{organization_id}/csv",
    response_class=FileResponse,
    responses={
        200: {
            "content": {
                "application/octet-stream": {
                    "schema": {"type": "string", "format": "binary"}
                }
            },
            "description": "Accessibility audit template CSV download",
        }
    },
)
def export_accessibility_audit_template_csv(
    organization_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Return a CSV file of accessibility MIS rows for the organization."""
    try:
        sql = text(
            """
            SELECT a.id, u.user_name, u.email as user_email, o.organization_name,
                   r.role_name as role, a.file_executed, a.file_type, a.execution_time
            FROM accessibility_mis a
            JOIN users u ON a.user_id = u.id
            LEFT JOIN organizations o ON u.organization_id = o.id
            LEFT JOIN roles r ON u.role_id = r.role_id
            WHERE o.id = :organization_id
            ORDER BY a.execution_time DESC
            """
        )

        rows = db.execute(sql, {"organization_id": organization_id}).fetchall()

        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="w", encoding="utf-8") as tmp:
            writer = csv.writer(tmp)
            writer.writerow([
                "id", "user_name", "user_email", "organization_name",
                "role", "file_executed", "file_type", "execution_time",
            ])

            for row in rows:
                exec_time = row[7].isoformat() if row[7] is not None else ""
                writer.writerow([row[0], row[1], row[2], row[3], row[4], row[5], row[6], exec_time])

            tmp_path = tmp.name

        background_tasks.add_task(lambda path: Path(path).unlink(missing_ok=True), tmp_path)
        filename = f"accessibility_audit_{organization_id}.csv"
        # Use application/octet-stream so Swagger shows a download link
        # and browsers prompt to save the file rather than render it inline.
        return FileResponse(path=tmp_path, media_type="application/octet-stream", filename=filename)
    
  
    except Exception as exc:
        logger.exception("Failed to export accessibility audit template CSV")
        raise HTTPException(status_code=500, detail=f"Failed to export CSV: {exc}") from exc


