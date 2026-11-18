from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class OrganizationCreate(BaseModel):
    organization_name: str = Field(..., min_length=1, max_length=255)
    created_by: Optional[int] = None


class OrganizationUpdate(BaseModel):
    organization_name: Optional[str] = Field(None, min_length=1, max_length=255)
    updated_by: Optional[int] = None


class OrganizationResponse(BaseModel):
    id: int
    organization_name: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    created_by: Optional[int] = None
    updated_by: Optional[int] = None

    model_config = {"from_attributes": True}
