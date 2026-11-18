from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, EmailStr, Field

PHONE_PATTERN = r"^\+?[0-9][0-9\s\-]{5,18}$"


# ==================== Input (request) schemas ====================
class CustomerCreate(BaseModel):
    customer_name: str = Field(..., min_length=1, max_length=255)
    customer_address: Optional[str] = Field(None, max_length=500)
    phone_no: Optional[str] = Field(None, pattern=PHONE_PATTERN)
    email_id: Optional[EmailStr] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "customer_name": "Acme Publishing",
                "customer_address": "12 Anna Salai, Chennai",
                "phone_no": "+91 98400 12345",
                "email_id": "contact@acme.com",
            }
        }
    }


class CustomerUpdate(BaseModel):
    """Partial update: only fields present in the request body are changed."""

    customer_name: Optional[str] = Field(None, min_length=1, max_length=255)
    customer_address: Optional[str] = Field(None, max_length=500)
    phone_no: Optional[str] = Field(None, pattern=PHONE_PATTERN)
    email_id: Optional[EmailStr] = None


# ==================== Output (response) schemas ====================
class CustomerResponse(BaseModel):
    id: int
    customer_name: str
    customer_address: Optional[str] = None
    phone_no: Optional[str] = None
    email_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class CustomerListData(BaseModel):
    total: int
    skip: int
    limit: int
    items: List[CustomerResponse]


class CustomerDeleteData(BaseModel):
    id: int


# ---- API envelopes (same shape as src.core.response.APIResponse) ----
class _CustomerAPIResponse(BaseModel):
    response_code: int
    message: str
    errors: List[Any] = Field(default_factory=list)


class CustomerSingleAPIResponse(_CustomerAPIResponse):
    data: Optional[CustomerResponse] = None


class CustomerListAPIResponse(_CustomerAPIResponse):
    data: Optional[CustomerListData] = None


class CustomerDeleteAPIResponse(_CustomerAPIResponse):
    data: Optional[CustomerDeleteData] = None
