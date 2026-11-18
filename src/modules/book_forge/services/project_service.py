"""Service layer for Book Forge projects.

Encapsulates all database access for BookForgeProjectModel using SQLAlchemy.

Exception strategy
------------------
* Intentional business errors (404 not found, 400 bad request) are raised as
  HTTPException and allowed to propagate untouched.
* Any database/SQLAlchemy failure is logged, the transaction is rolled back,
  and a clean HTTP 500 is raised so the caller never sees a raw driver error.
"""
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.core.logger import get_logger
from src.modules.book_forge.models.bookforge_project_model import BookForgeProjectModel
from src.modules.book_forge.schemas.book_forge_schema import ProjectCreate, ProjectUpdate
from src.modules.book_forge.services import category_service
from src.modules.book_forge.storage import storage_service

logger = get_logger(__name__)


def _validate_category_id(db: Session, category_id: Optional[int]) -> None:
    """Ensure category_id references a real category (clear 400, not a raw FK error)."""
    if category_id is None:
        return
    if category_service.get_category_by_id(db, category_id) is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unknown category_id {category_id}. Create it first via POST "
                "/categories, or by creating its blueprint prompt."
            ),
        )


def create_project(db: Session, project_in: ProjectCreate) -> BookForgeProjectModel:
    """Create and persist a new book project."""
    data = project_in.model_dump(exclude_unset=True)

    # A new project ALWAYS starts in 'draft' (status_id=1). Status only advances
    # through the workflow (sources_added -> building_knowledge -> ...), never at
    # creation, so we ignore any client-supplied book_status here.
    data["book_status"] = "draft"

    # Validate the category_id against the master list (hard FK).
    _validate_category_id(db, data.get("category_id"))

    project = BookForgeProjectModel(**data)

    try:
        db.add(project)
        db.commit()
        db.refresh(project)
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error("Error creating project: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create project",
        )

    # Create the on-disk folder structure for the new project.
    storage_service.create_project_folders(project.id)

    return project


def set_status(
    db: Session,
    project_id: int,
    status_name: str,
    *,
    only_if: Optional[set] = None,
) -> BookForgeProjectModel:
    """Advance a project's workflow status.

    ``status_name`` must be a valid ``book_forge_project_status.status_name``
    (enforced by the FK). ``only_if`` keeps transitions forward-only: the change
    is applied only when the project's current status is one of the given values;
    otherwise the project is returned unchanged. A no-op (already at the target
    status) short-circuits without a write.
    """
    project = get_project(db, project_id)

    if only_if is not None and project.book_status not in only_if:
        return project
    if project.book_status == status_name:
        return project

    project.book_status = status_name
    try:
        db.commit()
        db.refresh(project)
        return project
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error(
            "Error setting status of project %s to %s: %s",
            project_id,
            status_name,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update project status",
        )


def get_projects(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    book_status: Optional[str] = None,
) -> List[BookForgeProjectModel]:
    """Return a paginated list of active (non-deleted) projects."""
    try:
        query = db.query(BookForgeProjectModel).filter(
            BookForgeProjectModel.is_deleted.is_(False)
        )

        if book_status:
            query = query.filter(BookForgeProjectModel.book_status == book_status)

        return (
            query.order_by(BookForgeProjectModel.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
    except SQLAlchemyError as exc:
        logger.error("Error listing projects: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve projects",
        )


def get_project(db: Session, project_id: int) -> BookForgeProjectModel:
    """Fetch a single active project or raise 404."""
    try:
        project = (
            db.query(BookForgeProjectModel)
            .filter(
                BookForgeProjectModel.id == project_id,
                BookForgeProjectModel.is_deleted.is_(False),
            )
            .first()
        )
    except SQLAlchemyError as exc:
        logger.error(
            "Error fetching project %s: %s", project_id, exc, exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve project",
        )

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project with id {project_id} not found",
        )

    return project


def update_project(
    db: Session, project_id: int, project_in: ProjectUpdate
) -> BookForgeProjectModel:
    """Apply a partial update to an existing project."""
    project = get_project(db, project_id)

    update_data = project_in.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields provided to update",
        )

    # Validate the category_id against the master list (hard FK).
    if "category_id" in update_data:
        _validate_category_id(db, update_data.get("category_id"))

    for field, value in update_data.items():
        setattr(project, field, value)

    try:
        db.commit()
        db.refresh(project)
        return project
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error(
            "Error updating project %s: %s", project_id, exc, exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update project",
        )


def delete_project(db: Session, project_id: int) -> BookForgeProjectModel:
    """Soft-delete a project (sets is_deleted = True)."""
    project = get_project(db, project_id)

    project.is_deleted = True

    try:
        db.commit()
        db.refresh(project)
        return project
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error(
            "Error deleting project %s: %s", project_id, exc, exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete project",
        )
