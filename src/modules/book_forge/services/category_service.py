"""Book category (book-type) master service.

The single source of truth for the categories a project can use and that
blueprint prompts are authored for. ``category_name`` is the normalized key that
projects and prompt templates key off — normalize once, here, so every layer
agrees.
"""
from typing import List, Optional

from sqlalchemy.orm import Session

from src.modules.book_forge.models.bookforge_book_category_model import (
    BookForgeBookCategoryModel,
)


def normalize_category(value: Optional[str]) -> str:
    """Normalize a category to its canonical name/key (lowercase, underscores)."""
    return (value or "").strip().lower().replace(" ", "_").replace("-", "_")


def get_category(
    db: Session, category_name: str
) -> Optional[BookForgeBookCategoryModel]:
    """Fetch a category by its (normalized) name."""
    name = normalize_category(category_name)
    return (
        db.query(BookForgeBookCategoryModel)
        .filter(BookForgeBookCategoryModel.category_name == name)
        .first()
    )


def get_category_by_id(
    db: Session, category_id: int
) -> Optional[BookForgeBookCategoryModel]:
    """Fetch a category by its id."""
    return (
        db.query(BookForgeBookCategoryModel)
        .filter(BookForgeBookCategoryModel.id == category_id)
        .first()
    )


def list_categories(db: Session) -> List[BookForgeBookCategoryModel]:
    """List categories (for a project-creation dropdown)."""
    return (
        db.query(BookForgeBookCategoryModel)
        .order_by(BookForgeBookCategoryModel.category_name.asc())
        .all()
    )


def upsert_category(
    db: Session, category: str, *, category_description: Optional[str] = None
) -> BookForgeBookCategoryModel:
    """Create the category if new; return it either way. Idempotent on the name.

    Called when a blueprint prompt is defined for a category, so 'define a prompt'
    registers the book type. An optional description is set/updated when provided.
    """
    name = normalize_category(category)
    if not name:
        raise ValueError("A category name is required")

    existing = get_category(db, name)
    if existing:
        if category_description is not None:
            existing.category_description = category_description
            db.commit()
            db.refresh(existing)
        return existing

    row = BookForgeBookCategoryModel(
        category_name=name, category_description=category_description
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
