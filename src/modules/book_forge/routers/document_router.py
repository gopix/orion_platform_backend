"""Book Forge document APIs.

1. POST   /book-forge/projects/{project_id}/documents   Upload a document
2. GET    /book-forge/projects/{project_id}/documents   List a project's documents
3. GET    /book-forge/documents/{document_id}           Get document metadata
4. GET    /book-forge/documents/{document_id}/download   Download a document (attachment)
5. GET    /book-forge/documents/{document_id}/preview    Preview a document (inline)
6. DELETE /book-forge/documents/{document_id}           Delete a document
"""
from typing import List, Optional

from pathlib import Path

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
from src.modules.book_forge.services import document_service, project_service

router = APIRouter()


@router.post("/projects/{project_id}/documents", status_code=status.HTTP_201_CREATED)
async def upload_documents(
    project_id: int,
    files: List[UploadFile] = File(...),
    created_by: int = Form(...),
    document_type: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Upload one or more documents into a project's storage and record them.

    Each file is processed independently so a single bad file (empty, too large,
    unsupported) does not fail the whole batch — the response reports which
    uploads succeeded and which failed.
    """
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files provided",
        )

    uploaded = []
    failed = []
    for file in files:
        try:
            file_bytes = await file.read()
            document = document_service.create_document(
                db,
                project_id=project_id,
                original_filename=file.filename,
                mime_type=file.content_type,
                file_bytes=file_bytes,
                created_by=created_by,
                document_type=document_type,
            )
            uploaded.append(document.to_dict())
        except HTTPException as exc:
            failed.append({"filename": file.filename, "error": exc.detail})

    # If every file failed, surface it as an error rather than a 201.
    if not uploaded:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "All uploads failed", "failed": failed},
        )

    # First source added: advance the project from 'draft' to 'sources_added'.
    # only_if={'draft'} keeps the transition forward-only — a later upload on an
    # already-advanced project leaves its status untouched.
    project_service.set_status(
        db, project_id, "sources_added", only_if={"draft"}
    )

    message = f"{len(uploaded)} document(s) uploaded successfully"
    if failed:
        message += f"; {len(failed)} failed"
    return build_response(
        response_code=status.HTTP_201_CREATED,
        message=message,
        data={"uploaded": uploaded, "failed": failed},
    )


@router.get("/projects/{project_id}/documents")
def list_documents(
    project_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Return a paginated list of a project's documents."""
    documents = document_service.get_documents(
        db, project_id=project_id, skip=skip, limit=limit
    )
    return build_response(
        response_code=status.HTTP_200_OK,
        message="Documents retrieved successfully",
        data=[document.to_dict() for document in documents],
    )


@router.get("/documents/{document_id}")
def get_document_metadata(document_id: int, db: Session = Depends(get_db)):
    """Fetch metadata for a single document."""
    document = document_service.get_document(db, document_id)
    return build_response(
        response_code=status.HTTP_200_OK,
        message="Document metadata retrieved successfully",
        data=document.to_dict(),
    )


@router.get("/documents/{document_id}/download")
def download_document(document_id: int, db: Session = Depends(get_db)):
    """Download a document as an attachment."""
    document, path = document_service.get_document_with_path(db, document_id)
    return FileResponse(
        path=str(path),
        filename=document.original_filename,
        media_type=document.mime_type or "application/octet-stream",
    )


@router.get("/documents/{document_id}/preview")
def preview_document(document_id: int, db: Session = Depends(get_db)):
    """Preview a document inline (rendered in the browser where supported)."""
    document, path = document_service.get_document_with_path(db, document_id)
    return FileResponse(
        path=str(path),
        media_type=document.mime_type or "application/octet-stream",
        content_disposition_type="inline",
    )


@router.delete("/documents/{document_id}")
def delete_document(document_id: int, db: Session = Depends(get_db)):
    """Soft-delete a document and remove its file from disk."""
    document = document_service.delete_document(db, document_id)
    return build_response(
        response_code=status.HTTP_200_OK,
        message="Document deleted successfully",
        data={"id": document.id, "is_deleted": document.is_deleted},
    )


@router.post(
    "/projects/{project_id}/interview", status_code=status.HTTP_201_CREATED
)
async def submit_interview(
    project_id: int,
    created_by: int = Form(...),
    text: Optional[str] = Form(None),
    file: UploadFile = File(None),
    db: Session = Depends(get_db),
):
    """Submit an SME interview as raw text or a text/PDF upload.

    The submission is stored as ``sme_interview_<datetime>.pdf`` in the project's
    document storage: text (typed or from a text file) is rendered to PDF, while a
    PDF upload is stored as-is under the same naming.
    """
    if file is not None:
        content = await file.read()
        if not content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty",
            )

        content_type = (file.content_type or "").lower()
        extension = Path(file.filename or "").suffix.lower()

        if content_type == "application/pdf" or extension == ".pdf":
            document = document_service.store_interview_pdf(
                db, project_id=project_id, pdf_bytes=content, created_by=created_by
            )
        elif content_type.startswith("text/") or extension in ("", ".txt", ".md"):
            document = document_service.create_interview_pdf_from_text(
                db,
                project_id=project_id,
                text=content.decode("utf-8", errors="replace"),
                created_by=created_by,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported file type; upload plain text or a PDF",
            )
    elif text and text.strip():
        document = document_service.create_interview_pdf_from_text(
            db, project_id=project_id, text=text, created_by=created_by
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide interview text or upload a text/PDF file",
        )

    # On interview submit, advance the project to 'building_knowledge' (id=3).
    # Forward-only: only from 'draft'/'sources_added' so an already-advanced
    # project isn't pulled backward.
    project_service.set_status(
        db, project_id, "building_knowledge", only_if={"draft", "sources_added"}
    )

    return build_response(
        response_code=status.HTTP_201_CREATED,
        message="Interview saved as PDF successfully",
        data=document.to_dict(),
    )
