from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    book_title: str = Field(..., min_length=1, max_length=255)
    category_id: Optional[int] = Field(None, description="FK to book_forge_category.id")
    book_subject: Optional[str] = None
    target_audience: Optional[str] = Field(None, max_length=255)
    language_code: Optional[str] = Field(None, max_length=10)
    expected_pages: Optional[int] = Field(None, ge=0)
    chapter_count: Optional[int] = Field(None, ge=0)
    publisher_name: Optional[str] = Field(None, max_length=255)
    edition: Optional[str] = Field(None, max_length=50)
    primary_output_format: Optional[str] = Field(None, max_length=50)
    book_description: Optional[str] = None
    submission_deadline: Optional[date] = None
    # book_status is not client-settable on create — new projects always start
    # in 'draft'. Status advances only through the workflow.
    created_by: int


class ProjectUpdate(BaseModel):
    book_title: Optional[str] = Field(None, min_length=1, max_length=255)
    category_id: Optional[int] = Field(None, description="FK to book_forge_category.id")
    book_subject: Optional[str] = None
    target_audience: Optional[str] = Field(None, max_length=255)
    language_code: Optional[str] = Field(None, max_length=10)
    expected_pages: Optional[int] = Field(None, ge=0)
    chapter_count: Optional[int] = Field(None, ge=0)
    publisher_name: Optional[str] = Field(None, max_length=255)
    edition: Optional[str] = Field(None, max_length=50)
    primary_output_format: Optional[str] = Field(None, max_length=50)
    book_description: Optional[str] = None
    submission_deadline: Optional[date] = None
    # book_status is not client-settable via update — status advances only through
    # the workflow, not arbitrary PUTs. (Use a dedicated transition endpoint.)


class BlueprintGenerate(BaseModel):
    # Optional actor id recorded on the generated blueprint row.
    created_by: Optional[int] = None
    # Optional SME emphasis/priority note; authoritative weighting signal.
    sme_emphasis: Optional[str] = None


class GuidanceUpdate(BaseModel):
    # Plain-English guidance for a book type (the only thing a publisher edits).
    guidance: str = Field(..., min_length=1)
    created_by: Optional[int] = None
    # Optional generation model override for this book type (e.g. "gpt-4o" for a
    # complex exam book, "gpt-4o-mini" for a simple one). Defaults to inherited.
    model: Optional[str] = Field(None, max_length=100)


class GuidancePreview(BaseModel):
    guidance: str = Field(..., min_length=1)


class CategoryCreate(BaseModel):
    # Free-form; normalized to category_name server-side (e.g. "UPSC History" -> "upsc_history").
    category: str = Field(..., min_length=1, max_length=100)
    category_description: Optional[str] = Field(None, max_length=500)


class DocumentResponse(BaseModel):
    id: int
    project_id: int
    original_filename: str
    stored_filename: str
    file_path: str
    file_extension: Optional[str] = None
    mime_type: Optional[str] = None
    file_size: Optional[int] = None
    document_type: Optional[str] = None
    created_by: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    is_deleted: bool

    model_config = {"from_attributes": True}


class ProjectResponse(BaseModel):
    id: int
    book_title: str
    category: Optional[str] = None
    book_subject: Optional[str] = None
    target_audience: Optional[str] = None
    language_code: Optional[str] = None
    expected_pages: Optional[int] = None
    chapter_count: Optional[int] = None
    publisher_name: Optional[str] = None
    edition: Optional[str] = None
    primary_output_format: Optional[str] = None
    book_description: Optional[str] = None
    submission_deadline: Optional[date] = None
    book_status: str
    created_by: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    is_deleted: bool

    model_config = {"from_attributes": True}
