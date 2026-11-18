"""PromptTemplate — the master object describing a prompt.

Holds only metadata about a prompt (name, category, which version is live).
The actual prompt text lives in ``PromptVersion``, so the template stays stable
while versions evolve.
"""
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class PromptStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class PromptTemplate(BaseModel):
    id: Optional[int] = None
    name: str
    category: Optional[str] = None
    description: Optional[str] = None
    # Version number (or id) currently marked active for this template.
    active_version: Optional[int] = None
    status: PromptStatus = PromptStatus.DRAFT
    created_by: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
