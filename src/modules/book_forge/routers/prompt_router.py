"""Friendly, end-user prompt management for blueprint generation.

Publishers manage one plain-English *guidance* box per book type; the technical
prompt (Jinja, JSON contract, model settings, versions) is hidden and handled by
``blueprint_prompt_admin``. Book types are addressed by ``category_id`` (the
master-list PK), so the category must exist first (POST /categories).

    GET    /prompts/book-types                        list book types
    GET    /prompts/book-types/{category_id}          get current guidance
    PUT    /prompts/book-types/{category_id}          save guidance (new version + activate)
    POST   /prompts/book-types/{category_id}/preview  render preview (no tokens)
    POST   /prompts/book-types/{category_id}/revert   roll back to previous version

Every endpoint takes an optional ``template`` naming WHICH prompt to manage:

    chapter_content     (default) — how each chapter's prose is written
    syllabus_structure            — what counts as a chapter for this book type

Both are prompts the pipeline actually calls, so an edit here changes output.

NOTE: this is an admin capability (editing a prompt changes AI output for a whole
book category). It should be restricted to admin users once auth is enforced on
routes — see the TODO below.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.response import build_response
from src.modules.book_forge.schemas.book_forge_schema import (
    GuidancePreview,
    GuidanceUpdate,
)
from src.modules.book_forge.services import blueprint_prompt_admin, category_service

router = APIRouter()

# TODO(auth): gate these endpoints to admin role once route auth is in place.

_TEMPLATE_QUERY = Query(
    None,
    description=(
        "Which prompt to manage: 'chapter_content' (default, chapter prose) or "
        "'syllabus_structure' (what counts as a chapter)."
    ),
)


def _checked(template):
    """400 on an unknown template rather than silently editing the wrong prompt."""
    try:
        blueprint_prompt_admin.get_family(template)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unknown template '{template}'. Valid options: "
                f"{blueprint_prompt_admin.FAMILY_NAMES()}."
            ),
        )
    return template


def _category_name(db: Session, category_id: int) -> str:
    """Resolve a category_id to its name, or 404 if it doesn't exist."""
    category = category_service.get_category_by_id(db, category_id)
    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Category id {category_id} not found. Create it first (POST /categories).",
        )
    return category.category_name


@router.get("/prompts/book-types")
def list_book_types(
    template: str = _TEMPLATE_QUERY, db: Session = Depends(get_db)
):
    """List all book-type prompts in a family, with a friendly summary."""
    return build_response(
        response_code=status.HTTP_200_OK,
        message="Book types retrieved successfully",
        data=blueprint_prompt_admin.list_book_types(db, _checked(template)),
    )


@router.get("/prompts/book-types/{category_id}")
def get_guidance(
    category_id: int,
    template: str = _TEMPLATE_QUERY,
    db: Session = Depends(get_db),
):
    """Get the current plain-English guidance for a book type."""
    name = _category_name(db, category_id)
    return build_response(
        response_code=status.HTTP_200_OK,
        message="Guidance retrieved successfully",
        data=blueprint_prompt_admin.get_guidance(db, name, _checked(template)),
    )


@router.put("/prompts/book-types/{category_id}")
def update_guidance(
    category_id: int,
    payload: GuidanceUpdate,
    template: str = _TEMPLATE_QUERY,
    db: Session = Depends(get_db),
):
    """Save new guidance for a book type (composes, versions, and activates it)."""
    name = _category_name(db, category_id)
    result = blueprint_prompt_admin.set_guidance(
        db,
        name,
        payload.guidance,
        created_by=payload.created_by,
        model=payload.model,
        template=_checked(template),
    )
    return build_response(
        response_code=status.HTTP_200_OK,
        message="Guidance saved and activated",
        data=result,
    )


@router.post("/prompts/book-types/{category_id}/preview")
def preview_guidance(
    category_id: int,
    payload: GuidancePreview,
    template: str = _TEMPLATE_QUERY,
    db: Session = Depends(get_db),
):
    """Preview the composed prompt for some guidance — no LLM, no tokens spent."""
    name = _category_name(db, category_id)
    return build_response(
        response_code=status.HTTP_200_OK,
        message="Preview generated successfully",
        data=blueprint_prompt_admin.preview(
            db, name, payload.guidance, _checked(template)
        ),
    )


@router.post("/prompts/book-types/{category_id}/revert")
def revert_guidance(
    category_id: int,
    template: str = _TEMPLATE_QUERY,
    db: Session = Depends(get_db),
):
    """Roll back a book type's prompt to its previous version."""
    name = _category_name(db, category_id)
    return build_response(
        response_code=status.HTTP_200_OK,
        message="Reverted to previous version",
        data=blueprint_prompt_admin.revert(db, name, _checked(template)),
    )
