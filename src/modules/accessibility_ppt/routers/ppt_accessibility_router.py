import uuid
import tempfile

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.logger import get_logger
from src.core.response import APIResponse, build_response
from src.modules.accessibility_pdf.engines.accessibility_remediation_pipeline import _dlog
from src.modules.accessibility_ppt.engine.ppt_accesibility_engine_pipeline import (
    PPTValidationOrchestrator,
)


router = APIRouter()
logger = get_logger(__name__)



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
# In-memory job store + background remediation runner
# ---------------------------------------------------------------------------
_PPT_PREFIX = "/api/v1/ppt-accessibility"
_job_store: dict[str, dict[str, Any]] = {}


def _run_ppt_remediation_job(job_id: str, file_bytes: bytes, filename: str,
                             organization_id: int | None,
                             project_id: str | None) -> None:
    """Background task: run the PPT remediation pipeline and store the report."""
    job = _job_store.get(job_id)
    if job is None:
        return
    tmp_in: str | None = None
    try:
        job["status"] = "running"
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pptx") as fh:
            fh.write(file_bytes)
            tmp_in = fh.name
        out_path = tmp_in[:-5] + "_remediated.pptx"

        from src.modules.accessibility_ppt.engine.ppt_accessibility_remediation_pipeline import (
            PPTRemediationPipeline,
        )
        report = PPTRemediationPipeline().run(
            tmp_in, output_path=out_path,
            organization_id=organization_id, project_id=project_id)
        report["document_name"] = filename

        completed = report.get("status") == "completed"
        job.update({
            "status": "completed" if completed else "failed",
            "report": report,
            "remediated_ppt_path": report.get("remediated_path"),
            "error": None if completed else
                     ("; ".join(report.get("errors") or []) or "remediation failed"),
        })
        logger.info("PPT remediation job %s done | fixed=%s failed=%s",
                    job_id, report.get("summary", {}).get("issues_fixed"),
                    report.get("summary", {}).get("issues_failed"))
    except Exception as exc:
        logger.exception("PPT remediation job %s crashed", job_id)
        job.update({"status": "failed", "error": str(exc)})
    finally:
        if tmp_in:
            try:
                Path(tmp_in).unlink(missing_ok=True)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Orion agent-based validation
# ---------------------------------------------------------------------------

@router.post("/orion-validate-ppt", status_code=status.HTTP_200_OK, response_model=APIResponse)
async def orion_validate_ppt(file: UploadFile = File(...),
                              organization_id: int | None = None,
                              project_id: str | None = None):
    if not file.filename:
        raise HTTPException(status_code=400, detail="File name is required")
    if not file.filename.lower().endswith(".pptx"):
        raise HTTPException(status_code=400, detail="Only .pptx files are supported")
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    # Persist the upload to a temp .pptx so python-pptx / the loader can open it.
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pptx") as fh:
            fh.write(file_bytes)
            tmp_path = fh.name

        result = PPTValidationOrchestrator().validate(
            tmp_path,
            organization_id=organization_id,
            project_id=project_id,
        )
        # Report the uploaded name, not the temp file name.
        result["document_name"] = file.filename
        # Drop the flat "issues" list: every issue (incl. PASS) is already in
        # "agent_results", so the top-level copy is redundant. Counts remain in
        # the summary fields and "accessibility_score".
        result.pop("issues", None)
        return build_response(
            response_code=status.HTTP_200_OK,
            message="PPT validated successfully",
            data=result,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("orion-validate-ppt failed")
        raise HTTPException(status_code=500, detail=f"Failed to validate PPT: {exc}") from exc
    finally:
        if tmp_path:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# POST /orion-remediate-ppt
# ---------------------------------------------------------------------------

@router.post("/orion-remediate-ppt", status_code=status.HTTP_202_ACCEPTED,
             response_model=APIResponse)
async def orion_remediate_ppt(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    organization_id: int | None = None,
    project_id: str | None = None,
    user_id: int | None = None,
    db: Session = Depends(get_db),
):
    """
    Start PPT remediation (non-blocking). Returns 202 Accepted immediately.

    Workflow:
      1. POST here -> receive job_id
      2. GET /remediation-status/{job_id} -- poll every few seconds.
         - status "pending" / "running" -> keep polling
         - status "completed" -> full result is in the response (issues, summary, download_url)
         - status "failed"    -> error message is in the response
      3. GET /download-remediated-ppt/{job_id} -> download fixed PPT
    """
    _dlog(f"[ROUTE] orion-remediate-ppt HIT | file={getattr(file, 'filename', None)} org={organization_id}")
    
    if not file.filename:
        raise HTTPException(status_code=400, detail="File name is required")
    if not file.filename.lower().endswith(".pptx"):
        raise HTTPException(status_code=400,
                            detail="Only .pptx files are supported")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    file_type = (Path(file.filename).suffix.lstrip(".") or "pptx").capitalize()
    _capture_accessibility_mis_record(db, file.filename, file_type, user_id=user_id)

    job_id = uuid.uuid4().hex
    _job_store[job_id] = {
        "job_id": job_id, "status": "pending", "filename": file.filename,
        "remediated_ppt_path": None, "report": None, "error": None,
        "created_at": datetime.utcnow().isoformat(),
    }

    background_tasks.add_task(
        _run_ppt_remediation_job, job_id, file_bytes, file.filename,
        organization_id, project_id,
    )

    logger.info("orion-remediate-ppt queued | job=%s file=%s bytes=%s",
                job_id, file.filename, len(file_bytes))

    return build_response(
        response_code=status.HTTP_202_ACCEPTED,
        message="Remediation started. Poll status_url until status is completed.",
        data={
            "job_id": job_id,
            "status": "pending",
            "status_url": f"{_PPT_PREFIX}/ppt-remediation-status/{job_id}",
            "download_url": f"{_PPT_PREFIX}/download-remediated-ppt/{job_id}",
            "report_url": f"{_PPT_PREFIX}/remediation-report/{job_id}",
        },
    )


# ---------------------------------------------------------------------------
# GET /remediation-status/{job_id}
# ---------------------------------------------------------------------------

@router.get("/ppt-remediation-status/{job_id}", response_model=APIResponse)
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
        report = job.get("report") or {}
        data.update({
            "document": {"name": report.get("document_name")},
            "summary": report.get("summary"),
            "issues_fixed": report.get("issues_fixed"),
            "issues_failed": report.get("issues_failed"),
            "remediation_results": report.get("remediation_results"),
            "download_url": f"{_PPT_PREFIX}/download-remediated-ppt/{job_id}",
        })
        msg = "Remediation completed successfully."

    elif job_status == "failed":
        data["error"]      = job.get("error")
        data["status_url"] = f"{_PPT_PREFIX}/ppt-remediation-status/{job_id}"
        msg = f"Remediation failed: {job.get('error') or 'unknown error'}"

    else:
        data["status_url"] = f"{_PPT_PREFIX}/ppt-remediation-status/{job_id}"
        data["hint"]       = "Job is in progress. Poll status_url every 3-5 seconds."
        msg = f"Remediation is {job_status}. Poll status_url for updates."

    return build_response(response_code=status.HTTP_200_OK, message=msg, data=data)


@router.get("/dashboard/ppt/{job_id}", response_model=APIResponse)
async def ppt_accessibility_dashboard(job_id: str):
    """
    Four headline KPIs for a completed remediation job — designed for
    summary cards / dashboard widgets.

    curl http://localhost:8000/api/v1/accessibility/dashboard/ppt/{job_id}

    Returns:
        dashboard.accessibility_score  — weighted PASS ratio (0–100)
        dashboard.pptua_compliance     — % of PPT/UA rules that PASS
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

    report  = job.get("report") or {}
    summary = report.get("summary") or {}

    return build_response(
        response_code=status.HTTP_200_OK,
        message="Dashboard metrics computed successfully",
        data={
            "job_id":     job_id,
            "status":     job["status"],
            "created_at": job.get("created_at"),
            "document": {"name": report.get("document_name")},
            "dashboard": {
                "accessibility_score_before": summary.get("score_before"),
                "accessibility_score_after":  summary.get("score_after"),
                "issues_fixed":               summary.get("issues_fixed"),
                "issues_remaining":           summary.get("issues_remaining"),
            },
            "summary": summary,
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

    report = job.get("report") or {}
    is_done = job["status"] == "completed"

    return build_response(
        response_code=status.HTTP_200_OK,
        message="Remediation report fetched successfully",
        data={
            "job_id":     job["job_id"],
            "status":     job["status"],
            "created_at": job.get("created_at"),
            "document": {"name": report.get("document_name") or job.get("filename")},
            "summary": report.get("summary") if is_done else None,
            "issues_fixed": report.get("issues_fixed") if is_done else [],
            "issues_failed": report.get("issues_failed") if is_done else [],
            "remediation_results": report.get("remediation_results") if is_done else [],
            "download_url": f"{_PPT_PREFIX}/download-remediated-ppt/{job_id}" if is_done else None,
            "error": job.get("error"),
        },
    )


# ---------------------------------------------------------------------------
# GET /download-remediated-ppt/{job_id}
# ---------------------------------------------------------------------------

@router.get("/download-remediated-ppt/{job_id}")
async def download_remediated_ppt(job_id: str):
    job = _job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Remediation job not found")
    if job.get("status") in ("pending", "running"):
        raise HTTPException(
            status_code=409,
            detail=f"Job is still {job['status']}. Poll /ppt-remediation-status/{job_id} first.",
        )
    ppt_path = job.get("remediated_ppt_path")
    if not ppt_path or not Path(ppt_path).exists():
        raise HTTPException(status_code=404, detail="Remediated PPT not found on disk.")

    stem = Path(job.get("filename", "document.pptx")).stem
    return FileResponse(
        path=ppt_path,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename=f"{stem}_remediated.pptx",
        content_disposition_type="attachment",
    )


