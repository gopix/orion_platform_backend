"""RenderedPrompt — a runtime-only result of filling a template with variables.

Not persisted to the database; produced during execution when ``{{ variables }}``
are substituted into a version's text.
"""
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class RenderedPrompt(BaseModel):
    template_id: Optional[int] = None
    version: Optional[int] = None
    rendered_text: str
    variables_used: Dict[str, Any] = Field(default_factory=dict)
    token_estimate: Optional[int] = None
