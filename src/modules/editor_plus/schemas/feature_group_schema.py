from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from src.modules.editor_plus.schemas.api_envelope import APIEnvelope, PagedData


# ==================== Input ====================
class FeatureGroupCreate(BaseModel):
    """group_code is auto-generated: 0, 1000, 2000, ..."""

    group_name: str = Field(..., min_length=1, max_length=255, examples=["Punctuation"])
    group_description: Optional[str] = Field(None, examples=["Punctuation-related copyediting rules"])
    created_by: Optional[int] = Field(None, examples=[1])


class FeatureGroupUpdate(BaseModel):
    """Partial update: only fields present in the request body are changed.
    group_code is system-generated and cannot be changed."""

    group_name: Optional[str] = Field(None, min_length=1, max_length=255)
    group_description: Optional[str] = None
    updated_by: Optional[int] = None


# ==================== Output ====================
class FeatureGroupResponse(BaseModel):
    feature_group_id: int
    group_name: str
    group_code: int
    group_description: Optional[str] = None
    created_by: Optional[int] = None
    updated_by: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class FeatureGroupDeleteData(BaseModel):
    feature_group_id: int
    deleted_feature_count: int


FeatureGroupSingleAPIResponse = APIEnvelope[FeatureGroupResponse]
FeatureGroupListAPIResponse = APIEnvelope[PagedData[FeatureGroupResponse]]
FeatureGroupDeleteAPIResponse = APIEnvelope[FeatureGroupDeleteData]
