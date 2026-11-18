from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field

TemplateStatus = Literal["draft", "active", "inactive"]


# ==================== Input (request) schemas ====================
class TemplateCreate(BaseModel):
    template_name: str = Field(..., min_length=1, max_length=255, examples=["APA 7 Copyedit Style"])
    project_id: int = Field(..., gt=0, examples=[1])
    template_design: Optional[str] = Field(
        None, examples=['{"headings": {"h1": "Title Case"}, "citation": "APA"}']
    )
    template_description: Optional[str] = Field(None, examples=["House style for Biology 3e"])
    template_status: TemplateStatus = Field("draft", examples=["draft"])


class TemplateUpdate(BaseModel):
    """Partial update: only fields present in the request body are changed."""

    template_name: Optional[str] = Field(None, min_length=1, max_length=255)
    project_id: Optional[int] = Field(None, gt=0)
    template_design: Optional[str] = None
    template_description: Optional[str] = None
    template_status: Optional[TemplateStatus] = None


# ==================== Output (response) schemas ====================
class TemplateResponse(BaseModel):
    template_id: int
    template_name: str
    project_id: int
    project_name: Optional[str] = None
    template_design: Optional[str] = None
    template_description: Optional[str] = None
    template_status: str

    model_config = {"from_attributes": True}


class TemplateListData(BaseModel):
    total: int
    skip: int
    limit: int
    items: List[TemplateResponse]


class TemplateDeleteData(BaseModel):
    template_id: int


# ---- API envelopes (same shape as src.core.response.APIResponse) ----
class _TemplateAPIResponse(BaseModel):
    response_code: int
    message: str
    errors: List[Any] = Field(default_factory=list)


class TemplateSingleAPIResponse(_TemplateAPIResponse):
    data: Optional[TemplateResponse] = None


class TemplateListAPIResponse(_TemplateAPIResponse):
    data: Optional[TemplateListData] = None


class TemplateDeleteAPIResponse(_TemplateAPIResponse):
    data: Optional[TemplateDeleteData] = None
