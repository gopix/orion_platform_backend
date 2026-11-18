from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from src.modules.editor_plus.schemas.api_envelope import APIEnvelope, PagedData


# ==================== Input ====================
class MainFeatureCreate(BaseModel):
    feature_name: str = Field(..., min_length=1, max_length=255, examples=["Serial comma"])
    feature_code: int = Field(..., ge=0, examples=[1001])
    group_code: Optional[int] = Field(None, ge=0, examples=[100])
    feature_description: Optional[str] = Field(None, examples=["Insert Oxford comma in lists of 3+"])
    created_by: Optional[int] = Field(None, examples=[1])


class MainFeatureUpdate(BaseModel):
    """Partial update: only fields present in the request body are changed.
    Send "group_code": null to detach the feature from its group."""

    feature_name: Optional[str] = Field(None, min_length=1, max_length=255)
    feature_code: Optional[int] = Field(None, ge=0)
    group_code: Optional[int] = Field(None, ge=0)
    feature_description: Optional[str] = None
    updated_by: Optional[int] = None


# ==================== Output ====================
class MainFeatureResponse(BaseModel):
    feature_id: int
    feature_name: str
    feature_code: int
    group_code: Optional[int] = None
    group_name: Optional[str] = None
    feature_description: Optional[str] = None
    created_by: Optional[int] = None
    updated_by: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class MainFeatureDeleteData(BaseModel):
    feature_id: int


MainFeatureSingleAPIResponse = APIEnvelope[MainFeatureResponse]
MainFeatureListAPIResponse = APIEnvelope[PagedData[MainFeatureResponse]]
MainFeatureDeleteAPIResponse = APIEnvelope[MainFeatureDeleteData]
