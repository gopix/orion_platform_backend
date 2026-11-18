from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, Field


# ==================== Input (request) schemas ====================
class ProjectCreate(BaseModel):
    project_name: str = Field(..., min_length=1, max_length=255, examples=["Biology Textbook 3e"])
    customer_id: int = Field(..., gt=0, examples=[1])
    project_description: Optional[str] = Field(None, examples=["Copy editing of 24 chapters"])
    project_manager: Optional[str] = Field(None, max_length=255, examples=["Suresh K"])
    created_by: Optional[int] = Field(None, examples=[1])


class ProjectUpdate(BaseModel):
    """Partial update: only fields present in the request body are changed."""

    project_name: Optional[str] = Field(None, min_length=1, max_length=255)
    customer_id: Optional[int] = Field(None, gt=0)
    project_description: Optional[str] = None
    project_manager: Optional[str] = Field(None, max_length=255)


# ==================== Output (response) schemas ====================
class ProjectResponse(BaseModel):
    project_id: int
    project_name: str
    customer_id: int
    customer_name: Optional[str] = None
    project_description: Optional[str] = None
    project_manager: Optional[str] = None
    created_at: Optional[datetime] = None
    created_by: Optional[int] = None

    model_config = {"from_attributes": True}


class ProjectListData(BaseModel):
    total: int
    skip: int
    limit: int
    items: List[ProjectResponse]


class ProjectDeleteData(BaseModel):
    project_id: int


# ---- API envelopes (same shape as src.core.response.APIResponse) ----
class _ProjectAPIResponse(BaseModel):
    response_code: int
    message: str
    errors: List[Any] = Field(default_factory=list)


class ProjectSingleAPIResponse(_ProjectAPIResponse):
    data: Optional[ProjectResponse] = None


class ProjectListAPIResponse(_ProjectAPIResponse):
    data: Optional[ProjectListData] = None


class ProjectDeleteAPIResponse(_ProjectAPIResponse):
    data: Optional[ProjectDeleteData] = None
