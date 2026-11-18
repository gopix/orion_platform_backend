"""
website_schema.py - Pydantic request/response schemas for the
web_accessibility_websites resource.

accessibility_status is intentionally absent from WebsiteUpdate: it's a
system-derived rollup (UNKNOWN / SCANNING / PASS / WARNING / FAIL) written
only by scan_service.run_scan() based on actual scan findings, never by a
client PUT - see scan_service.py's _derive_accessibility_status(). It's
still exposed read-only on WebsiteResponse.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


def _normalize_url(value: str) -> str:
    value = value.strip()
    if not (value.startswith("http://") or value.startswith("https://")):
        raise ValueError("base_url must start with http:// or https://")
    return value


class WebsiteCreate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    base_url: str = Field(..., min_length=1, max_length=2048)
    description: Optional[str] = Field(None, max_length=255)
    environment: str = Field("PRODUCTION", max_length=50)
    crawl_enabled: bool = False
    crawl_frequency: Optional[str] = Field(None, max_length=50)
    authentication_required: bool = False
    authentication_type: Optional[str] = Field(None, max_length=50)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: str) -> str:
        return _normalize_url(v)


class WebsiteUpdate(BaseModel):
    # accessibility_status is deliberately NOT here - see module docstring.
    name: Optional[str] = Field(None, max_length=255)
    base_url: Optional[str] = Field(None, min_length=1, max_length=2048)
    description: Optional[str] = Field(None, max_length=255)
    environment: Optional[str] = Field(None, max_length=50)
    crawl_enabled: Optional[bool] = None
    crawl_frequency: Optional[str] = Field(None, max_length=50)
    authentication_required: Optional[bool] = None
    authentication_type: Optional[str] = Field(None, max_length=50)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return _normalize_url(v)


class WebsiteResponse(BaseModel):
    id: int
    name: Optional[str] = None
    base_url: Optional[str] = None
    description: Optional[str] = None
    accessibility_status: Optional[str] = None
    environment: str
    crawl_enabled: bool
    crawl_frequency: Optional[str] = None
    authentication_required: bool
    authentication_type: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_scan_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
