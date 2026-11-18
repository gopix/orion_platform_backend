"""Service layer for Book Forge documents.

Encapsulates database access for BookForgeDocumentModel (SQLAlchemy) plus the
filesystem side-effects of storing uploaded files.

Exception strategy
------------------
* Intentional business errors (404 not found, 400/413 bad request) are raised
  as HTTPException and allowed to propagate untouched.
* Any database/SQLAlchemy failure is logged, the transaction is rolled back,
  and a clean HTTP 500 is raised so the caller never sees a raw driver error.
* Filesystem failures during save are surfaced as HTTP 500 (via storage_service);
  best-effort cleanup removes orphaned files if the DB write later fails.
"""
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import List, Tuple
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.core.config import settings
from src.core.logger import get_logger
from src.modules.book_forge.models.bookforge_document_model import BookForgeDocumentModel
from src.modules.book_forge.services import project_service
from src.modules.book_forge.storage import storage_service
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

logger = get_logger(__name__)

# Document type tag applied to SME interview submissions.
INTERVIEW_DOCUMENT_TYPE = "sme_interview"


def create_document(
    db: Session,
    project_id: int,
    original_filename: str,
    mime_type: str,
    file_bytes: bytes,
    created_by: int,
    document_type: str = None,
) -> BookForgeDocumentModel:
    """Persist an uploaded document: validate, write to disk, then record in DB."""
    # 404 if the parent project does not exist / is deleted.
    project_service.get_project(db, project_id)

    if not original_filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No filename provided",
        )

    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

    max_size = getattr(settings, "max_upload_size", 0)
    if max_size and len(file_bytes) > max_size:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the maximum allowed size of {max_size} bytes",
        )

    extension = Path(original_filename).suffix.lower().lstrip(".")
    stored_filename = f"{uuid4().hex}.{extension}" if extension else uuid4().hex

    # Write to disk first (raises HTTP 500 on filesystem error).
    saved_path = storage_service.save_upload(project_id, stored_filename, file_bytes)

    document = BookForgeDocumentModel(
        project_id=project_id,
        original_filename=original_filename,
        stored_filename=stored_filename,
        file_path=str(saved_path),
        file_extension=extension or None,
        mime_type=mime_type,
        file_size=len(file_bytes),
        document_type=document_type,
        created_by=created_by,
    )

    try:
        db.add(document)
        db.commit()
        db.refresh(document)
        return document
    except SQLAlchemyError as exc:
        db.rollback()
        # Remove the orphaned file so disk and DB stay consistent.
        storage_service.remove_file(str(saved_path))
        logger.error("Error creating document: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create document",
        )


def create_interview_pdf_from_text(
    db: Session,
    project_id: int,
    text: str,
    created_by: int,
) -> BookForgeDocumentModel:
    """Render SME interview ``text`` to a PDF and store it as a project document.

    The PDF is named ``sme_interview_<YYYYmmdd_HHMMSS>.pdf`` and saved to the same
    location as every other project document (via ``create_document``).
    """
    if not text or not text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Interview text is empty",
        )

    pdf_bytes = _text_to_pdf_bytes(text, title="SME Interview")
    return create_document(
        db,
        project_id=project_id,
        original_filename=_interview_filename(),
        mime_type="application/pdf",
        file_bytes=pdf_bytes,
        created_by=created_by,
        document_type=INTERVIEW_DOCUMENT_TYPE,
    )


def store_interview_pdf(
    db: Session,
    project_id: int,
    pdf_bytes: bytes,
    created_by: int,
) -> BookForgeDocumentModel:
    """Store an already-PDF interview upload as a project document.

    Saved under the same ``sme_interview_<YYYYmmdd_HHMMSS>.pdf`` naming as the
    text-conversion path, alongside all other project documents.
    """
    return create_document(
        db,
        project_id=project_id,
        original_filename=_interview_filename(),
        mime_type="application/pdf",
        file_bytes=pdf_bytes,
        created_by=created_by,
        document_type=INTERVIEW_DOCUMENT_TYPE,
    )


def _interview_filename() -> str:
    """``sme_interview_<YYYYmmdd_HHMMSS>.pdf``."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"sme_interview_{timestamp}.pdf"


def _text_to_pdf_bytes(text: str, *, title: str = "Document") -> bytes:
    """Render plain text into a simple, paginated PDF and return its bytes."""

    buffer = BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=A4, title=title)
    styles = getSampleStyleSheet()

    flow = [Paragraph(_escape(title), styles["Title"]), Spacer(1, 12)]
    # Split on blank lines into paragraphs; keep single newlines as line breaks.
    for block in text.replace("\r\n", "\n").split("\n\n"):
        block = block.strip()
        if not block:
            continue
        flow.append(Paragraph(_escape(block).replace("\n", "<br/>"), styles["BodyText"]))
        flow.append(Spacer(1, 8))

    document.build(flow)
    return buffer.getvalue()


def _escape(value: str) -> str:
    """Escape XML-special characters for reportlab Paragraph markup."""
    return (
        value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def get_documents(
    db: Session,
    project_id: int,
    skip: int = 0,
    limit: int = 100,
) -> List[BookForgeDocumentModel]:
    """Return a paginated list of active documents for a project."""
    # Ensures the project exists (404 otherwise).
    project_service.get_project(db, project_id)

    try:
        return (
            db.query(BookForgeDocumentModel)
            .filter(
                BookForgeDocumentModel.project_id == project_id,
                BookForgeDocumentModel.is_deleted.is_(False),
            )
            .order_by(BookForgeDocumentModel.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
    except SQLAlchemyError as exc:
        logger.error(
            "Error listing documents for project %s: %s",
            project_id,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve documents",
        )


def get_document(db: Session, document_id: int) -> BookForgeDocumentModel:
    """Fetch a single active document or raise 404."""
    try:
        document = (
            db.query(BookForgeDocumentModel)
            .filter(
                BookForgeDocumentModel.id == document_id,
                BookForgeDocumentModel.is_deleted.is_(False),
            )
            .first()
        )
    except SQLAlchemyError as exc:
        logger.error(
            "Error fetching document %s: %s", document_id, exc, exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve document",
        )

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with id {document_id} not found",
        )

    return document


def get_document_with_path(
    db: Session, document_id: int
) -> Tuple[BookForgeDocumentModel, Path]:
    """Return a document and its on-disk path, raising 404 if the file is missing."""
    document = get_document(db, document_id)
    path = Path(document.file_path)

    if not path.exists():
        logger.error(
            "File for document %s missing on disk: %s", document_id, path
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document file not found on disk",
        )

    return document, path


def delete_document(db: Session, document_id: int) -> BookForgeDocumentModel:
    """Soft-delete a document record and remove its file from disk (best-effort)."""
    document = get_document(db, document_id)
    document.is_deleted = True

    try:
        db.commit()
        db.refresh(document)
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error(
            "Error deleting document %s: %s", document_id, exc, exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete document",
        )

    # DB state is committed; removing the physical file is best-effort.
    storage_service.remove_file(document.file_path)
    return document
