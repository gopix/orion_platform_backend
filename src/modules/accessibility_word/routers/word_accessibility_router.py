import uuid
import tempfile

from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.logger import get_logger
from src.core.response import APIResponse, build_response
from src.modules.accessibility_pdf.engines.accessibility_remediation_pipeline import _dlog
from src.modules.accessibility_word.engine.word_validator.word_validation_orchestrator import WordValidationOrchestrator
from src.modules.accessibility_word.engine.word_remediator.remediation_engine import (
    WordRemediationOrchestrator,
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
_WORD_PREFIX = "/api/v1/word-accessibility"
_job_store: dict[str, dict[str, Any]] = {}


def _run_word_remediation_job(job_id: str,
                              file_bytes: bytes,
                              filename: str,
                              organization_id: int | None,
                              project_id: str | None) -> None:
    """Background task: run the Word remediation pipeline and store the report."""
    job = _job_store.get(job_id)
    if job is None:
        return
    tmp_in: str | None = None
    try:
        job["status"] = "running"
        with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as fh:
            fh.write(file_bytes)
            tmp_in = fh.name
        out_path = tmp_in[:-5] + "_remediated.docx"

        report = WordRemediationOrchestrator().remediate(
            tmp_in, output_path=out_path, document_name=filename,
            organization_id=organization_id, project_id=project_id)

        # completed_with_errors still produced a valid, re-validated copy.
        completed = report.get("status") in ("completed", "completed_with_errors")
        job.update({
            "status": "completed" if completed else "failed",
            "report": report,
            "remediated_docx_path": report.get("remediated_path"),
            "error": None if completed else
                     ("; ".join(report.get("errors") or []) or "remediation failed"),
        })
        logger.info("Word remediation job %s done | fixed=%s failed=%s",
                    job_id, report.get("summary", {}).get("issues_fixed"),
                    report.get("summary", {}).get("issues_failed"))
    except Exception as exc:
        logger.exception("Word remediation job %s crashed", job_id)
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

@router.post("/orion-validate-word", status_code=status.HTTP_200_OK, response_model=APIResponse)
async def orion_validate_word(file: UploadFile = File(...),
                               organization_id: int | None = None,
                               project_id: str | None = None):
    if not file.filename:
        raise HTTPException(status_code=400, detail="File name is required")
    if not file.filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Only .docx files are supported")
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    # Persist the upload to a temp .docx so python-docx / the loader can open it.
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as fh:
            fh.write(file_bytes)
            tmp_path = fh.name

        result = WordValidationOrchestrator().validate(
            tmp_path,
            organization_id=organization_id,
            project_id=project_id,
            # Report the uploaded name, not the temp file name.
            document_name=file.filename,
        )
        return build_response(
            response_code=status.HTTP_200_OK,
            message="Word validated successfully",
            data=result,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("orion-validate-word failed")
        raise HTTPException(status_code=500, detail=f"Failed to validate Word: {exc}") from exc
    finally:
        if tmp_path:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# POST /orion-remediate-word
# ---------------------------------------------------------------------------

@router.post("/orion-remediate-word",
             status_code=status.HTTP_202_ACCEPTED,
             response_model=APIResponse)
async def orion_remediate_word(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    organization_id: int | None = None,
    project_id: str | None = None,
    user_id: int | None = None,
    db: Session = Depends(get_db),
):
    """
    Start word remediation (non-blocking). Returns 202 Accepted immediately.

    Workflow:
      1. POST here -> receive job_id
      2. GET /remediation-status/{job_id} -- poll every few seconds.
         - status "pending" / "running" -> keep polling
         - status "completed" -> full result is in the response (issues, summary, download_url)
         - status "failed"    -> error message is in the response
      3. GET /download-remediated-word/{job_id} -> download fixed word
    """
    _dlog(f"[ROUTE] orion-remediate-word HIT | file={getattr(file, 'filename', None)} org={organization_id}")
    
    if not file.filename:
        raise HTTPException(status_code=400, detail="File name is required")
    if not file.filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400,
                            detail="Only .docx files are supported")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    file_type = (Path(file.filename).suffix.lstrip(".") or "docx").capitalize()
    _capture_accessibility_mis_record(db, file.filename, file_type, user_id=user_id)

    job_id = uuid.uuid4().hex
    _job_store[job_id] = {
        "job_id": job_id, "status": "pending", "filename": file.filename,
        "remediated_docx_path": None, "report": None, "error": None,
        "created_at": datetime.utcnow().isoformat(),
    }

    background_tasks.add_task(
        _run_word_remediation_job, job_id, file_bytes, file.filename,
        organization_id, project_id,
    )

    logger.info("orion-remediate-word queued | job=%s file=%s bytes=%s",
                job_id, file.filename, len(file_bytes))

    return build_response(
        response_code=status.HTTP_202_ACCEPTED,
        message="Remediation started. Poll status_url until status is completed.",
        data={
            "job_id": job_id,
            "status": "pending",
            "status_url": f"{_WORD_PREFIX}/word-remediation-status/{job_id}",
            "download_url": f"{_WORD_PREFIX}/download-remediated-word/{job_id}",
            "report_url": f"{_WORD_PREFIX}/remediation-report/{job_id}",
        },
    )


# ---------------------------------------------------------------------------
# GET /remediation-status/{job_id}
# ---------------------------------------------------------------------------

@router.get("/word-remediation-status/{job_id}", response_model=APIResponse)
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
            "download_url": f"{_WORD_PREFIX}/download-remediated-word/{job_id}",
        })
        msg = "Remediation completed successfully."

    elif job_status == "failed":
        data["error"]      = job.get("error")
        data["status_url"] = f"{_WORD_PREFIX}/word-remediation-status/{job_id}"
        msg = f"Remediation failed: {job.get('error') or 'unknown error'}"

    else:
        data["status_url"] = f"{_WORD_PREFIX}/word-remediation-status/{job_id}"
        data["hint"]       = "Job is in progress. Poll status_url every 3-5 seconds."
        msg = f"Remediation is {job_status}. Poll status_url for updates."

    return build_response(response_code=status.HTTP_200_OK, message=msg, data=data)


@router.get("/dashboard/word/{job_id}", response_model=APIResponse)
async def word_accessibility_dashboard(job_id: str):
    """
    Four headline KPIs for a completed remediation job — designed for
    summary cards / dashboard widgets.

    curl http://localhost:8000/api/v1/accessibility/dashboard/word/{job_id}

    Returns:
        dashboard.accessibility_score  — weighted PASS ratio (0–100)
        dashboard.wordua_compliance     — % of word/UA rules that PASS
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
#            "summary": report.get("summary") if is_done else None,
            "issues_fixed": report.get("issues_fixed") if is_done else [],
            "issues_failed": report.get("issues_failed") if is_done else [],
            "remediation_results": report.get("remediation_results") if is_done else [],
            "download_url": f"{_WORD_PREFIX}/download-remediated-word/{job_id}" if is_done else None,
            "error": job.get("error"),
        },
    )


# ---------------------------------------------------------------------------
# GET /download-remediated-word/{job_id}
# ---------------------------------------------------------------------------

@router.get("/download-remediated-word/{job_id}")
async def download_remediated_word(job_id: str):
    job = _job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Remediation job not found")
    if job.get("status") in ("pending", "running"):
        raise HTTPException(
            status_code=409,
            detail=f"Job is still {job['status']}. Poll /word-remediation-status/{job_id} first.",
        )
    docx_path = job.get("remediated_docx_path")
    if not docx_path or not Path(docx_path).exists():
        raise HTTPException(status_code=404, detail="Remediated Docx not found on disk.")

    stem = Path(job.get("filename", "document.docx")).stem
    return FileResponse(
        path=docx_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"{stem}_remediated.docx",
        content_disposition_type="attachment",
    )