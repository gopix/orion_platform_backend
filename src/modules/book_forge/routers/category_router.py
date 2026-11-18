"""Book category (book-type) master endpoints.

The controlled list a project-creation UI selects from. Categories are also
auto-registered when a blueprint prompt is defined for one. Each has a
``category_id`` (the PK the prompt book-type endpoints use).

    GET  /categories                  list categories (dropdown source)
    POST /categories                  define a category up front
    GET  /categories/{category_id}    fetch one by id
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.response import build_response
from src.modules.book_forge.schemas.book_forge_schema import CategoryCreate
from src.modules.book_forge.services import category_service

router = APIRouter()


@router.get("/categories")
def list_categories(db: Session = Depends(get_db)):
    """List book categories (for a project-creation dropdown)."""
    categories = category_service.list_categories(db)
    return build_response(
        response_code=status.HTTP_200_OK,
        message="Categories retrieved successfully",
        data=[c.to_dict() for c in categories],
    )


@router.post("/categories", status_code=status.HTTP_201_CREATED)
def create_category(payload: CategoryCreate, db: Session = Depends(get_db)):
    """Define a category (idempotent on its normalized name); returns its id."""
    category = category_service.upsert_category(
        db, payload.category, category_description=payload.category_description
    )
    return build_response(
        response_code=status.HTTP_201_CREATED,
        message="Category saved successfully",
        data=category.to_dict(),
    )


@router.get("/categories/{category_id}")
def get_category(category_id: int, db: Session = Depends(get_db)):
    """Fetch a single category by id."""
    category = category_service.get_category_by_id(db, category_id)
    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Category not found"
        )
    return build_response(
        response_code=status.HTTP_200_OK,
        message="Category retrieved successfully",
        data=category.to_dict(),
    )
