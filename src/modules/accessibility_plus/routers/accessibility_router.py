from typing import Any, Literal

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from src.modules.accessibility_plus.engines.accesibility_engine_pipeline import AccessibilityEnginePipeline
from src.modules.accessibility_plus.engines.audit_template_engine import AccessiblilityAudit

router = APIRouter()
accessibility_audit_engine = AccessiblilityAudit()
accessibility_engine_pipeline = AccessibilityEnginePipeline()


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


class RunAccessibilityChecksRequest(BaseModel):
    organization_id: int
    project_id: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    include_org_level_fallback: bool = True


class RunAccessibilityChecksResponse(BaseModel):
    organization_id: int
    project_id: str | None = None
    total_checks: int
    executed_checks: int
    results: list[dict[str, Any]]


@router.post(
    "/master_accessibility_check",
    status_code=status.HTTP_200_OK,
    response_model=MasterChecksUpsertResponse,
)
async def upsert_master_accessibility_check_json(payload: MasterAccessibilityChecksBulkRequest):
    try:
        rows = [row.model_dump() if hasattr(row, "model_dump") else row.dict() for row in payload.rows]
        result = accessibility_audit_engine.upsert_master_checks_json(rows)
        return MasterChecksUpsertResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to process JSON rows") from exc


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
        payload_data = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
        result = accessibility_audit_engine.clone_master_checks(payload_data)
        return CloneMasterChecksResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to clone master accessibility checks") from exc


@router.post(
    "/run-checks",
    status_code=status.HTTP_200_OK,
    response_model=RunAccessibilityChecksResponse,
)
async def run_accessibility_checks(payload: RunAccessibilityChecksRequest):
    try:
        result = accessibility_engine_pipeline.run(
            organization_id=payload.organization_id,
            project_id=payload.project_id,
            context=payload.context,
            include_org_level_fallback=payload.include_org_level_fallback,
        )
        return RunAccessibilityChecksResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to run accessibility checks") from exc

