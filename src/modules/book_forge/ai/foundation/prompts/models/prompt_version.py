"""PromptVersion — the actual, versioned prompt content.

Every edit to a prompt produces a new ``PromptVersion``. It carries the prompt
text plus the model parameters it was authored for.
"""
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class VersionStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class PromptVersion(BaseModel):
    id: Optional[int] = None
    template_id: Optional[int] = None
    version: int
    template_text: str
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    status: VersionStatus = VersionStatus.DRAFT
    created_by: Optional[int] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
