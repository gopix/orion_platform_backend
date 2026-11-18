"""Audit-sheet persistence service.

Owns the versioned exchange of the structure audit sheet: the system generates a
sheet, the SME fills it in and uploads it back, and BOTH directions are kept as
immutable rows so any earlier version can be retrieved.

``version`` is one monotonic sequence per project across both directions, so the
history reads as a single ordered conversation (see
``BookForgeAuditSheetModel``). Nothing is ever overwritten — a new generation or
a new submission always inserts a new row and demotes the previous row of the
same kind from ``current`` to ``superseded``.
"""
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.core.logger import get_logger
from src.modules.book_forge.models.bookforge_audit_sheet_model import (
    BookForgeAuditSheetModel,
)
from src.modules.book_forge.services import (
    audit_sheet_builder,
    project_service,
    syllabus_structure_service,
)
from src.modules.book_forge.storage import storage_service

logger = get_logger(__name__)

SHEET_TYPE_GENERATED = "generated"
SHEET_TYPE_SUBMITTED = "submitted"
_SHEET_TYPES = (SHEET_TYPE_GENERATED, SHEET_TYPE_SUBMITTED)

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _next_version(db: Session, project_id: int) -> int:
    """Next version for a project, counting both generated and submitted rows."""
    current_max = (
        db.query(func.max(BookForgeAuditSheetModel.version))
        .filter(
            BookForgeAuditSheetModel.project_id == project_id,
            BookForgeAuditSheetModel.is_deleted.is_(False),
        )
        .scalar()
    )
    return (current_max or 0) + 1


def _supersede_current(db: Session, project_id: int, sheet_type: str) -> None:
    """Demote existing ``current`` rows of this kind. Does not commit."""
    (
        db.query(BookForgeAuditSheetModel)
        .filter(
            BookForgeAuditSheetModel.project_id == project_id,
            BookForgeAuditSheetModel.sheet_type == sheet_type,
            BookForgeAuditSheetModel.status == "current",
            BookForgeAuditSheetModel.is_deleted.is_(False),
        )
        .update({"status": "superseded"}, synchronize_session=False)
    )


def generate_sheet(db: Session, *, project_id: int) -> BookForgeAuditSheetModel:
    """Extract the syllabus structure and persist it as a new audit-sheet version.

    Takes nothing but the project. The chapter structure is READ FROM the project's
    syllabus document — it is never supplied by the caller, because working out the
    structure is what the system is for. Raises 409 when no syllabus document is
    tagged for the project, 422 when the syllabus cannot be read.
    """
    # 404s if the project does not exist / is soft-deleted.
    project = project_service.get_project(db, project_id)

    extracted = syllabus_structure_service.extract_structure(db, project_id)
    rows = extracted["chapters"]
    flags = extracted["flags"]
    source = extracted["source"]
    # PYQ frequency is a separate signal and is not measured yet, so the reference
    # columns stay empty rather than carrying a number nobody can defend.
    matches: List[Dict[str, Any]] = []
    pyq_source_note = (
        "PYQ frequency has not been measured for this project yet, so every "
        "'PYQ hits' count reads 0 and the advisory band is blank. Set weights "
        "from your own judgement."
    )

    version = _next_version(db, project_id)
    generated_at = datetime.utcnow().isoformat()

    workbook_bytes = audit_sheet_builder.build_workbook(
        project_id=project_id,
        version=version,
        generated_at=generated_at,
        chapters=rows,
        project_title=getattr(project, "book_title", None),
        flags=flags,
        matches=matches,
        pyq_source_note=pyq_source_note,
    )

    stored_filename = f"audit_v{version}_{uuid4().hex}.xlsx"
    saved_path = storage_service.save_audit_sheet(
        project_id, stored_filename, workbook_bytes
    )

    _supersede_current(db, project_id, SHEET_TYPE_GENERATED)
    sheet = BookForgeAuditSheetModel(
        project_id=project_id,
        version=version,
        sheet_type=SHEET_TYPE_GENERATED,
        stored_filename=stored_filename,
        original_filename=f"blueprint_sme_audit_v{version}.xlsx",
        file_path=str(saved_path),
        file_size=len(workbook_bytes),
        checksum_sha256=sha256(workbook_bytes).hexdigest(),
        # 'source' records which documents, prompt template and model produced
        # this structure, so a disputed sheet can always be traced back.
        payload_json={
            "chapters": rows,
            "flags": flags,
            "matches": matches,
            "source": source,
        },
        row_count=len(rows),
        weighted_count=0,
        status="current",
    )
    try:
        db.add(sheet)
        db.commit()
        db.refresh(sheet)
    except Exception:
        db.rollback()
        # Keep disk and DB consistent — same discipline as document_service.
        storage_service.remove_file(str(saved_path))
        logger.error(
            "Failed to record audit sheet for project %s", project_id, exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to record the generated audit sheet",
        )

    logger.info(
        "Generated audit sheet | project=%s version=%s units=%s chapters=%s "
        "unverified=%s",
        project_id,
        version,
        source.get("units"),
        len(rows),
        source.get("unverified"),
    )
    return sheet


def submit_sheet(
    db: Session,
    *,
    project_id: int,
    file_bytes: bytes,
    original_filename: Optional[str] = None,
    notes: Optional[str] = None,
    created_by: Optional[int] = None,
) -> Tuple[BookForgeAuditSheetModel, Dict[str, Any]]:
    """Record a filled-in audit sheet as a new submitted version.

    The workbook is parsed before anything is stored, so a file that is not an
    audit sheet is rejected as a 400 rather than saved and puzzled over later.
    Returns the stored row plus the parsed payload.
    """
    project_service.get_project(db, project_id)

    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

    try:
        parsed = audit_sheet_builder.read_submission(file_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 - any openpyxl failure is a bad upload
        logger.warning("Could not read submitted audit sheet: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not read the uploaded workbook as an .xlsx audit sheet",
        )

    if not parsed["chapters"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded audit sheet contains no chapter rows",
        )

    # Match the upload back to the generated version it came from, when the
    # identity block survived. A missing block is tolerated (the user may have
    # rebuilt the file) but a MISMATCHED project is not.
    identity = audit_sheet_builder.read_sheet_identity(file_bytes)
    source_version = None
    if identity:
        identity_project = identity.get("project_id")
        if identity_project is not None and int(identity_project) != int(project_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"This sheet was generated for project {identity_project}, "
                    f"not project {project_id}."
                ),
            )
        source_version = identity.get("version")

    version = _next_version(db, project_id)
    stored_filename = f"audit_submitted_v{version}_{uuid4().hex}.xlsx"
    saved_path = storage_service.save_audit_sheet(
        project_id, stored_filename, file_bytes
    )

    _supersede_current(db, project_id, SHEET_TYPE_SUBMITTED)
    sheet = BookForgeAuditSheetModel(
        project_id=project_id,
        version=version,
        sheet_type=SHEET_TYPE_SUBMITTED,
        source_version=source_version,
        stored_filename=stored_filename,
        original_filename=original_filename,
        file_path=str(saved_path),
        file_size=len(file_bytes),
        checksum_sha256=sha256(file_bytes).hexdigest(),
        payload_json=parsed,
        row_count=parsed["counts"]["rows"],
        weighted_count=parsed["counts"]["weighted"],
        status="current",
        notes=notes,
        created_by=created_by,
    )
    try:
        db.add(sheet)
        db.commit()
        db.refresh(sheet)
    except Exception:
        db.rollback()
        storage_service.remove_file(str(saved_path))
        logger.error(
            "Failed to record submitted audit sheet for project %s",
            project_id,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to record the submitted audit sheet",
        )

    logger.info(
        "Audit sheet submitted | project=%s version=%s source_version=%s "
        "rows=%s kept=%s weighted=%s retitled=%s",
        project_id,
        version,
        source_version,
        parsed["counts"]["rows"],
        parsed["counts"]["kept"],
        parsed["counts"]["weighted"],
        parsed["counts"]["retitled"],
    )
    return sheet, parsed


def get_signed_off_structure(db: Session, project_id: int) -> Dict[str, Any]:
    """Return the chapter structure the SME signed off, for blueprint generation.

    Reads the newest ``submitted`` sheet and returns only the chapters the SME
    KEPT, using the corrected title where one was supplied. This is the
    authoritative chapter list: blueprint generation may write prose for these
    chapters but may not add, drop, rename or reorder them.

    Raises 409 when no sheet has been submitted — generating a blueprint without a
    signed-off structure is exactly the failure this gate exists to prevent.
    """
    sheet = (
        db.query(BookForgeAuditSheetModel)
        .filter(
            BookForgeAuditSheetModel.project_id == project_id,
            BookForgeAuditSheetModel.sheet_type == SHEET_TYPE_SUBMITTED,
            BookForgeAuditSheetModel.is_deleted.is_(False),
        )
        .order_by(BookForgeAuditSheetModel.version.desc())
        .first()
    )
    if sheet is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "No signed-off audit sheet for this project. Generate the audit "
                f"sheet (POST /projects/{project_id}/audit-sheet), have the SME "
                "complete it, and submit it back before generating a blueprint."
            ),
        )

    payload = sheet.payload_json or {}
    kept = [
        chapter
        for chapter in (payload.get("chapters") or [])
        if chapter.get("keep", True) and (chapter.get("chapter") or "").strip()
    ]
    if not kept:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Audit sheet version {sheet.version} has no chapters marked to "
                "keep, so there is nothing to generate."
            ),
        )

    chapters: List[Dict[str, Any]] = []
    for chapter in kept:
        chapters.append(
            {
                "section": chapter.get("section"),
                "unit_number": chapter.get("unit_number"),
                "unit": chapter.get("unit"),
                "chapter_number": chapter.get("chapter_number"),
                # The corrected title already won during parsing; this is the
                # wording the SME approved.
                "title": (chapter.get("chapter") or "").strip(),
                "sme_weight": chapter.get("sme_weight"),
                "sme_notes": chapter.get("sme_notes"),
                "pyq_hits": chapter.get("pyq_hits"),
            }
        )

    logger.info(
        "Loaded signed-off structure | project=%s audit_version=%s chapters=%s "
        "weighted=%s",
        project_id,
        sheet.version,
        len(chapters),
        len([c for c in chapters if c["sme_weight"] is not None]),
    )
    return {
        "audit_sheet_version": sheet.version,
        "audit_sheet_id": sheet.id,
        "chapters": chapters,
    }


def list_sheets(
    db: Session, project_id: int, sheet_type: Optional[str] = None
) -> List[BookForgeAuditSheetModel]:
    """Return every audit-sheet version for a project, newest first."""
    if sheet_type is not None and sheet_type not in _SHEET_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"sheet_type must be one of {list(_SHEET_TYPES)}",
        )

    query = db.query(BookForgeAuditSheetModel).filter(
        BookForgeAuditSheetModel.project_id == project_id,
        BookForgeAuditSheetModel.is_deleted.is_(False),
    )
    if sheet_type:
        query = query.filter(BookForgeAuditSheetModel.sheet_type == sheet_type)
    return query.order_by(BookForgeAuditSheetModel.version.desc()).all()


def get_sheet(
    db: Session, project_id: int, version: int
) -> BookForgeAuditSheetModel:
    """Return one specific version, or 404."""
    sheet = (
        db.query(BookForgeAuditSheetModel)
        .filter(
            BookForgeAuditSheetModel.project_id == project_id,
            BookForgeAuditSheetModel.version == version,
            BookForgeAuditSheetModel.is_deleted.is_(False),
        )
        .first()
    )
    if sheet is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No audit sheet version {version} for project {project_id}",
        )
    return sheet


def get_latest_sheet(
    db: Session, project_id: int, sheet_type: str = SHEET_TYPE_GENERATED
) -> BookForgeAuditSheetModel:
    """Return the newest version of one kind, or 404."""
    sheet = (
        db.query(BookForgeAuditSheetModel)
        .filter(
            BookForgeAuditSheetModel.project_id == project_id,
            BookForgeAuditSheetModel.sheet_type == sheet_type,
            BookForgeAuditSheetModel.is_deleted.is_(False),
        )
        .order_by(BookForgeAuditSheetModel.version.desc())
        .first()
    )
    if sheet is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No {sheet_type} audit sheet for project {project_id} yet."
            ),
        )
    return sheet


def get_sheet_with_path(
    db: Session, project_id: int, version: Optional[int] = None, *,
    sheet_type: str = SHEET_TYPE_GENERATED,
) -> Tuple[BookForgeAuditSheetModel, Path]:
    """Resolve a version (or the latest of a kind) to its file on disk.

    404s when the row exists but the file is gone, rather than handing
    ``FileResponse`` a path that will fail at send time.
    """
    sheet = (
        get_sheet(db, project_id, version)
        if version is not None
        else get_latest_sheet(db, project_id, sheet_type)
    )
    path = Path(sheet.file_path)
    if not path.exists():
        logger.error(
            "Audit sheet row %s points at a missing file: %s", sheet.id, sheet.file_path
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The audit sheet file is no longer present on disk",
        )
    return sheet, path
