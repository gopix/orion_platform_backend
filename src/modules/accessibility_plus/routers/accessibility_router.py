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

router = APIRouter()
logger = get_logger(__name__)

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

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    job_id = uuid.uuid4().hex
    logger.info(
        "orion-remediate-pdf | job=%s org=%s project=%s file=%s bytes=%s",
        job_id, organization_id, project_id, file.filename, len(file_bytes),
    )

    pdfix_module = pdfix_service._load_pdfix_module()
    pdfix = pdfix_module.GetPdfix()
    if not pdfix:
        raise HTTPException(status_code=500, detail="Unable to initialize PDFix SDK")

    tmp_path: str | None = None
    pdf_doc = None
    try:
        # ── Write upload to a temp file so PDFix can open it ─────────
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

        # ── Run the full pipeline ─────────────────────────────────────
        # AccessibilityRemediationPipeline:
        #   1. Validates with AccessibilityEnginePipeline
        #   2. Remediates each auto_fixable issue via RemediatorService
        #   3. Saves modified pdf_doc to <original>_remediated.pdf
        #   4. Clears caches and re-validates
        pipeline = get_remediation_pipeline()
        pipeline_result = pipeline.run(
            organization_id=organization_id,
            project_id=project_id,
            context=context,
        )

        summary = pipeline_result.get("summary", {})
        initial = pipeline_result.get("validation_result", {})
        revalidation = pipeline_result.get("revalidation_result", {})
        remediated_pdf_path = pipeline_result.get("remediated_pdf_path")

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

        response_data = {
            "job_id": job_id,
            "status": "completed",
            "issues_detected": initial.get("total_issues", 0),
            "issues_fixed": summary.get("issues_fixed", 0),
            "issues_remaining": revalidation.get("total_issues", 0),
            "auto_fixable_count": initial.get("auto_fixable_count", 0),
            "save_success": summary.get("save_success", False),
            "download_url": (
                f"/api/v1/accessibility/download-remediated-pdf/{job_id}"
                if remediated_pdf_path
                else None
            ),
            "report_url": f"/api/v1/accessibility/remediation-report/{job_id}",
            "summary": summary,
        }

        logger.info(
            "orion-remediate-pdf done | job=%s fixed=%s remaining=%s saved=%s",
            job_id,
            summary.get("issues_fixed", 0),
            revalidation.get("total_issues", 0),
            summary.get("save_success", False),
        )

        return build_response(
            response_code=status.HTTP_200_OK,
            message="PDF remediated successfully",
            data=response_data,
        )

    except ValueError as exc:
        _job_store[job_id] = {
            "job_id": job_id,
            "status": "failed",
            "error": str(exc),
            "created_at": datetime.utcnow().isoformat(),
        }
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
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

    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=download_name,
    )
