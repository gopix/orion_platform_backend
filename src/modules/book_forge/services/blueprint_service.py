"""Blueprint persistence service.

Stores generated blueprints as versioned rows (never overwriting), so the
review/revision loop keeps history. ``create_blueprint`` assigns the next
version for the project automatically.
"""
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.modules.book_forge.models.bookforge_blueprint_model import (
    BookForgeBlueprintModel,
)


def _next_version(db: Session, project_id: int) -> int:
    """Return the next version number for a project's blueprint (1-based)."""
    current_max = (
        db.query(func.max(BookForgeBlueprintModel.version))
        .filter(
            BookForgeBlueprintModel.project_id == project_id,
            BookForgeBlueprintModel.is_deleted.is_(False),
        )
        .scalar()
    )
    return (current_max or 0) + 1


def create_blueprint(
    db: Session,
    *,
    project_id: int,
    blueprint_json: Dict[str, Any],
    title: Optional[str] = None,
    description: Optional[str] = None,
    status: str = "generated",
    created_by: Optional[int] = None,
) -> BookForgeBlueprintModel:
    """Insert a new blueprint version for the project."""
    blueprint = BookForgeBlueprintModel(
        project_id=project_id,
        version=_next_version(db, project_id),
        title=title,
        description=description,
        blueprint_json=blueprint_json,
        status=status,
        created_by=created_by,
    )
    db.add(blueprint)
    db.commit()
    db.refresh(blueprint)
    return blueprint


def get_blueprints(db: Session, project_id: int) -> List[BookForgeBlueprintModel]:
    """Return all blueprint versions for a project, newest version first."""
    return (
        db.query(BookForgeBlueprintModel)
        .filter(
            BookForgeBlueprintModel.project_id == project_id,
            BookForgeBlueprintModel.is_deleted.is_(False),
        )
        .order_by(BookForgeBlueprintModel.version.desc())
        .all()
    )


def get_latest_blueprint(
    db: Session, project_id: int
) -> Optional[BookForgeBlueprintModel]:
    """Return the most recent blueprint version for a project, or None."""
    return (
        db.query(BookForgeBlueprintModel)
        .filter(
            BookForgeBlueprintModel.project_id == project_id,
            BookForgeBlueprintModel.is_deleted.is_(False),
        )
        .order_by(BookForgeBlueprintModel.version.desc())
        .first()
    )


def get_blueprint(
    db: Session, blueprint_id: int
) -> Optional[BookForgeBlueprintModel]:
    """Return a single blueprint by id, or None."""
    return (
        db.query(BookForgeBlueprintModel)
        .filter(
            BookForgeBlueprintModel.id == blueprint_id,
            BookForgeBlueprintModel.is_deleted.is_(False),
        )
        .first()
    )


def get_blueprint_by_version(
    db: Session, project_id: int, version: int
) -> Optional[BookForgeBlueprintModel]:
    """Return a specific blueprint version for a project, or None."""
    return (
        db.query(BookForgeBlueprintModel)
        .filter(
            BookForgeBlueprintModel.project_id == project_id,
            BookForgeBlueprintModel.version == version,
            BookForgeBlueprintModel.is_deleted.is_(False),
        )
        .first()
    )


def update_status(
    db: Session, blueprint_id: int, status: str
) -> Optional[BookForgeBlueprintModel]:
    """Advance a blueprint's lifecycle status (generated/reviewed/approved)."""
    blueprint = get_blueprint(db, blueprint_id)
    if not blueprint:
        return None
    blueprint.status = status
    db.commit()
    db.refresh(blueprint)
    return blueprint
