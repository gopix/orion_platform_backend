"""Book Forge project APIs.

1. POST   /book-forge/projects            Create a new project
2. GET    /book-forge/projects            List all projects (paginated, filterable)
3. GET    /book-forge/projects/{id}       Get a single project
4. PUT    /book-forge/projects/{id}       Update a project
5. DELETE /book-forge/projects/{id}       Soft-delete a project
"""
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.response import build_response
from src.modules.book_forge.services.blueprint_pdf import render_blueprint_pdf
from src.modules.book_forge.schemas.book_forge_schema import (
    BlueprintGenerate,
    ProjectCreate,
    ProjectUpdate,
)
from src.modules.book_forge.services import (
    ai_workflow_service,
    blueprint_service,
    document_service,
    project_service as book_forge_service,
)
from typing import Optional

router = APIRouter()


@router.post("/projects", status_code=status.HTTP_201_CREATED)
def create_project(project_in: ProjectCreate, db: Session = Depends(get_db)):
    """Create a new book project."""
    project = book_forge_service.create_project(db, project_in)
    return build_response(
        response_code=status.HTTP_201_CREATED,
        message="Project created successfully",
        data=project.to_dict(),
    )


@router.get("/projects")
def list_projects(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    book_status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Return a paginated list of projects."""
    projects = book_forge_service.get_projects(
        db, skip=skip, limit=limit, book_status=book_status
    )
    return build_response(
        response_code=status.HTTP_200_OK,
        message="Projects retrieved successfully",
        data=[project.to_dict() for project in projects],
    )


@router.get("/projects/{project_id}")
def get_project(project_id: int, db: Session = Depends(get_db)):
    """Fetch a single project by id."""
    project = book_forge_service.get_project(db, project_id)
    return build_response(
        response_code=status.HTTP_200_OK,
        message="Project retrieved successfully",
        data=project.to_dict(),
    )


@router.put("/projects/{project_id}")
def update_project(
    project_id: int, project_in: ProjectUpdate, db: Session = Depends(get_db)
):
    """Update an existing project."""
    project = book_forge_service.update_project(db, project_id, project_in)
    return build_response(
        response_code=status.HTTP_200_OK,
        message="Project updated successfully",
        data=project.to_dict(),
    )


@router.delete("/projects/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db)):
    """Soft-delete a project."""
    project = book_forge_service.delete_project(db, project_id)
    return build_response(
        response_code=status.HTTP_200_OK,
        message="Project deleted successfully",
        data={"id": project.id, "is_deleted": project.is_deleted},
    )


@router.post("/projects/{project_id}/process")
def process_project(project_id: int, db: Session = Depends(get_db)):
    """Process a project and all its documents through the AI pipeline.

    Fetches every document belonging to the project and hands them to
    ``ai_workflow_service.process_project`` (parse -> chunk -> knowledge graph),
    returning a per-document and aggregate summary.
    """
    documents = document_service.get_documents(
        db, project_id=project_id, skip=0, limit=1000
    )

    # Mark ingestion as running. Forward-only, and allow a retry from 'failed'.
    book_forge_service.set_status(
        db,
        project_id,
        "building_knowledge",
        only_if={"draft", "sources_added", "failed"},
    )

    try:
        result = ai_workflow_service.process_project(
            db, project_id=project_id, documents=documents
        )
    except Exception:
        # Any hard failure in the pipeline drops the project to 'failed'.
        book_forge_service.set_status(db, project_id, "failed")
        raise

    # Advance based on the workflow outcome: 'completed' -> knowledge_ready,
    # anything else (e.g. 'failed') -> failed.
    if result.get("status") == "completed":
        book_forge_service.set_status(
            db, project_id, "knowledge_ready", only_if={"building_knowledge"}
        )
    else:
        book_forge_service.set_status(db, project_id, "failed")

    return build_response(
        response_code=status.HTTP_200_OK,
        message="Project processed successfully",
        data=result,
    )


@router.post(
    "/projects/{project_id}/blueprint", status_code=status.HTTP_202_ACCEPTED
)
def generate_blueprint(
    project_id: int,
    background_tasks: BackgroundTasks,
    payload: Optional[BlueprintGenerate] = None,
    db: Session = Depends(get_db),
):
    """Start blueprint generation (non-blocking). Returns 202 with a blueprint id.

    The chapter structure comes from the SME-signed-off audit sheet, so this
    endpoint refuses with 409 until one has been submitted. Writing prose for
    every chapter is too slow for one request at 100+ chapters, so generation runs
    in the background:

      1. POST here -> 202 with blueprint_id and status_url
      2. GET the status_url until "status" is no longer "generating"
         - "generated" / "approved" -> the blueprint is in blueprint_json
         - "failed"                 -> blueprint_json.error says why

    Job state lives on the blueprint ROW, not in memory, so polling still works
    after a restart and with more than one worker.
    """
    created_by = payload.created_by if payload else None
    sme_emphasis = payload.sme_emphasis if payload else None

    # Precondition: the knowledge base must be built before a blueprint can be
    # generated. Only 'knowledge_ready' (first run) or 'blueprint_ready'
    # (regeneration) may proceed; anything earlier — or a 'failed' project whose
    # knowledge base isn't confirmed — is rejected with 409 so the caller runs
    # /process first.
    project = book_forge_service.get_project(db, project_id)
    ready_states = {"knowledge_ready", "blueprint_ready"}
    if project.book_status not in ready_states:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Knowledge base not ready (status: '{project.book_status}'). "
                "Process the project's sources first (POST /projects/"
                f"{project_id}/process)."
            ),
        )

    # Gate + reserve the row. Raises 409 when no audit sheet has been submitted,
    # BEFORE anything is scheduled, so the caller is told immediately.
    reserved = ai_workflow_service.prepare_blueprint(
        db, project_id=project_id, created_by=created_by
    )

    book_forge_service.set_status(
        db,
        project_id,
        "generating_blueprint",
        only_if=ready_states,
    )

    background_tasks.add_task(
        ai_workflow_service.run_blueprint_job,
        project_id,
        reserved["blueprint_id"],
        created_by,
        sme_emphasis,
    )

    return build_response(
        response_code=status.HTTP_202_ACCEPTED,
        message=(
            f"Blueprint generation started for {reserved['chapters_to_write']} "
            "chapter(s). Poll status_url until status is no longer 'generating'."
        ),
        data={
            **reserved,
            "status": "generating",
            "status_url": f"/api/v1/book-forge/projects/{project_id}/blueprint",
        },
    )


@router.get("/projects/{project_id}/blueprint")
def get_latest_blueprint(project_id: int, db: Session = Depends(get_db)):
    """Return the most recent blueprint version for a project."""
    blueprint = blueprint_service.get_latest_blueprint(db, project_id)
    if not blueprint:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No blueprint found for this project",
        )
    return build_response(
        response_code=status.HTTP_200_OK,
        message="Blueprint retrieved successfully",
        data=blueprint.to_dict(),
    )


@router.get("/projects/{project_id}/blueprints")
def list_blueprint_versions(project_id: int, db: Session = Depends(get_db)):
    """List all blueprint versions for a project (newest first)."""
    blueprints = blueprint_service.get_blueprints(db, project_id)
    return build_response(
        response_code=status.HTTP_200_OK,
        message="Blueprint versions retrieved successfully",
        data=[
            {
                "id": bp.id,
                "version": bp.version,
                "title": bp.title,
                "status": bp.status,
                "created_at": bp.created_at,
            }
            for bp in blueprints
        ],
    )


@router.get("/projects/{project_id}/blueprint/pdf")
def download_blueprint_pdf(project_id: int, db: Session = Depends(get_db)):
    """Download the latest blueprint as an author-friendly PDF."""
    blueprint = blueprint_service.get_latest_blueprint(db, project_id)
    return _blueprint_pdf_response(project_id, blueprint)


@router.get("/projects/{project_id}/blueprint/{version}/pdf")
def download_blueprint_version_pdf(
    project_id: int, version: int, db: Session = Depends(get_db)
):
    """Download a specific blueprint version as an author-friendly PDF."""
    blueprint = blueprint_service.get_blueprint_by_version(db, project_id, version)
    return _blueprint_pdf_response(project_id, blueprint)


def _blueprint_pdf_response(project_id: int, blueprint) -> Response:
    """Render a blueprint row to a downloadable PDF response (404 if missing)."""
    if not blueprint:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No blueprint found for this project",
        )
    pdf_bytes = render_blueprint_pdf(
        blueprint.blueprint_json,
        project_title=blueprint.title,
        version=blueprint.version,
    )
    filename = f"blueprint_project_{project_id}_v{blueprint.version}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
