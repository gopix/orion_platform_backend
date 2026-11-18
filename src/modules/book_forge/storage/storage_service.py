"""Filesystem storage helpers for Book Forge.

Responsible for creating and locating the on-disk folder structure that backs
each project. The storage root and sub-folder names are read from settings
(sourced from .env).

Layout created per project::

    BOOK_FORGE_STORAGE_ROOT/
    └── project_<id>/
        ├── uploads/
        ├── processing/
        ├── exports/
        └── temp/
"""
from pathlib import Path
from typing import Dict

from fastapi import HTTPException, status

from src.core.config import settings
from src.core.logger import get_logger

logger = get_logger(__name__)

# Sub-folders created under each project directory, keyed by a stable name.
_SUBFOLDERS = {
    "uploads": settings.book_forge_uploads,
    "processing": settings.book_forge_processing,
    "temp": settings.book_forge_temp,
    "exports": settings.book_forge_exports,
}


def get_project_root(project_id: int) -> Path:
    """Return the absolute path to a project's root folder (no I/O)."""
    return Path(settings.book_forge_storage_root) / f"project_{project_id}"


def create_project_folders(project_id: int) -> Dict[str, str]:
    """Create the folder structure for a project and return the created paths.

    Idempotent: existing folders are left untouched (``exist_ok=True``).
    Raises HTTP 500 if the directories cannot be created.
    """
    project_root = get_project_root(project_id)

    try:
        project_root.mkdir(parents=True, exist_ok=True)

        paths: Dict[str, str] = {"root": str(project_root)}
        for key, folder_name in _SUBFOLDERS.items():
            sub_path = project_root / folder_name
            sub_path.mkdir(parents=True, exist_ok=True)
            paths[key] = str(sub_path)

        logger.info(
            "Created storage folders for project %s at %s", project_id, project_root
        )
        return paths
    except OSError as exc:
        logger.error(
            "Failed to create storage folders for project %s: %s",
            project_id,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create project storage folders",
        )


def get_uploads_dir(project_id: int) -> Path:
    """Return the absolute path to a project's uploads folder (no I/O)."""
    return get_project_root(project_id) / settings.book_forge_uploads


def save_upload(project_id: int, stored_filename: str, data: bytes) -> Path:
    """Write uploaded bytes into the project's uploads folder and return the path.

    Ensures the uploads folder exists first. Raises HTTP 500 on filesystem errors.
    """
    uploads_dir = get_uploads_dir(project_id)
    try:
        uploads_dir.mkdir(parents=True, exist_ok=True)
        destination = uploads_dir / stored_filename
        destination.write_bytes(data)
        logger.info("Saved upload for project %s at %s", project_id, destination)
        return destination
    except OSError as exc:
        logger.error(
            "Failed to save upload for project %s: %s", project_id, exc, exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save uploaded document",
        )


def get_audit_sheets_dir(project_id: int) -> Path:
    """Return the absolute path to a project's audit-sheet folder (no I/O).

    Audit sheets are review working files rather than user-supplied sources, so
    they live under ``processing/`` and not alongside uploaded documents.
    """
    return (
        get_project_root(project_id) / settings.book_forge_processing / "audit_sheets"
    )


def save_audit_sheet(project_id: int, stored_filename: str, data: bytes) -> Path:
    """Write an audit-sheet workbook into the project's audit-sheet folder.

    Mirrors ``save_upload`` (creates the folder, raises HTTP 500 on OS errors) and
    is used for BOTH generated and submitted sheets, so every version of the
    exchange is retrievable from one place.
    """
    target_dir = get_audit_sheets_dir(project_id)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        destination = target_dir / stored_filename
        destination.write_bytes(data)
        logger.info("Saved audit sheet for project %s at %s", project_id, destination)
        return destination
    except OSError as exc:
        logger.error(
            "Failed to save audit sheet for project %s: %s",
            project_id,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save audit sheet",
        )


def remove_file(file_path: str) -> None:
    """Best-effort deletion of a file from disk. Never raises; logs on failure."""
    try:
        path = Path(file_path)
        if path.exists():
            path.unlink()
            logger.info("Removed file %s", path)
    except OSError as exc:
        logger.warning("Could not remove file %s: %s", file_path, exc)
