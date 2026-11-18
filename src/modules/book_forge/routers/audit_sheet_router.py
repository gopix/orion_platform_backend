"""Audit-sheet endpoints — the structural review gate.

The audit sheet is how a proposed unit -> chapter breakdown gets confirmed by a
human before a blueprint is generated. Both directions are versioned, so any
earlier sheet (generated or submitted) can be downloaded again:

    POST /projects/{id}/audit-sheet            generate a new version
    GET  /projects/{id}/audit-sheet/versions   full version history
    GET  /projects/{id}/audit-sheet/download   download latest, or ?version=N
    POST /projects/{id}/audit-sheet/submit     upload the filled-in sheet
    GET  /projects/{id}/audit-sheet/{version}  one version's metadata + payload

Route order matters: the literal paths are declared BEFORE ``/{version}`` so
"versions", "download" and "submit" are never coerced into the int path param.
"""
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.response import build_response
from src.modules.book_forge.services import audit_sheet_service

router = APIRouter()


@router.post("/projects/{project_id}/audit-sheet", status_code=status.HTTP_201_CREATED)
def generate_audit_sheet(project_id: int, db: Session = Depends(get_db)):
    """Generate a new audit-sheet version for a project.

    Takes NO request body. The chapter structure is read from the project's
    syllabus document — determining it is the system's job, not the caller's.

    409 if no document is tagged ``document_type='syllabus'``;
    422 if the syllabus cannot be parsed into text.
    """
    sheet = audit_sheet_service.generate_sheet(db, project_id=project_id)
    return build_response(
        response_code=status.HTTP_201_CREATED,
        message=f"Audit sheet version {sheet.version} generated successfully",
        data={
            **sheet.to_dict(),
            "download_url": (
                f"/api/v1/book-forge/projects/{project_id}"
                f"/audit-sheet/download?version={sheet.version}"
            ),
        },
    )


@router.get("/projects/{project_id}/audit-sheet/versions")
def list_audit_sheet_versions(
    project_id: int,
    sheet_type: Optional[str] = Query(
        None, description="Filter to 'generated' or 'submitted'"
    ),
    db: Session = Depends(get_db),
):
    """Full audit-sheet history for a project, newest version first.

    Both directions of the exchange appear in one ordered list, so the review
    conversation is readable end to end.
    """
    sheets = audit_sheet_service.list_sheets(db, project_id, sheet_type)
    return build_response(
        response_code=status.HTTP_200_OK,
        message="Audit sheet versions retrieved successfully",
        data=[
            {
                **sheet.to_dict(),
                "download_url": (
                    f"/api/v1/book-forge/projects/{project_id}"
                    f"/audit-sheet/download?version={sheet.version}"
                ),
            }
            for sheet in sheets
        ],
    )


@router.get("/projects/{project_id}/audit-sheet/download")
def download_audit_sheet(
    project_id: int,
    version: Optional[int] = Query(
        None, description="Specific version; defaults to the latest of sheet_type"
    ),
    sheet_type: str = Query(
        audit_sheet_service.SHEET_TYPE_GENERATED,
        description="Which side of the exchange to download when no version is given",
    ),
    db: Session = Depends(get_db),
):
    """Download an audit sheet as .xlsx — the latest by default, or any version."""
    sheet, path = audit_sheet_service.get_sheet_with_path(
        db, project_id, version, sheet_type=sheet_type
    )
    filename = (
        sheet.original_filename
        or f"blueprint_sme_audit_v{sheet.version}.xlsx"
    )
    return FileResponse(
        path=str(path),
        filename=filename,
        media_type=audit_sheet_service.XLSX_MIME,
    )


@router.post(
    "/projects/{project_id}/audit-sheet/submit", status_code=status.HTTP_201_CREATED
)
async def submit_audit_sheet(
    project_id: int,
    file: UploadFile = File(...),
    created_by: Optional[int] = Form(None),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Upload a filled-in audit sheet, stored as a new submitted version.

    The workbook is parsed and validated before anything is written, so a file
    that is not an audit sheet — or belongs to another project — is rejected
    rather than stored.
    """
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File name is required",
        )
    if not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .xlsx / .xlsm audit sheets are supported",
        )

    file_bytes = await file.read()
    sheet, parsed = audit_sheet_service.submit_sheet(
        db,
        project_id=project_id,
        file_bytes=file_bytes,
        original_filename=file.filename,
        notes=notes,
        created_by=created_by,
    )
    return build_response(
        response_code=status.HTTP_201_CREATED,
        message=f"Audit sheet submitted as version {sheet.version}",
        data={
            **sheet.to_dict(),
            # Summary counters so the caller can confirm the round-trip landed
            # without downloading and re-reading the file.
            "summary": parsed["counts"],
        },
    )


@router.get("/projects/{project_id}/audit-sheet/{version}")
def get_audit_sheet_version(
    project_id: int,
    version: int,
    include_payload: bool = Query(
        True, description="Include the parsed rows (large for 100+ chapters)"
    ),
    db: Session = Depends(get_db),
):
    """Metadata for one audit-sheet version, with its parsed content by default."""
    sheet = audit_sheet_service.get_sheet(db, project_id, version)
    return build_response(
        response_code=status.HTTP_200_OK,
        message=f"Audit sheet version {version} retrieved successfully",
        data=sheet.to_dict(include_payload=include_payload),
    )
