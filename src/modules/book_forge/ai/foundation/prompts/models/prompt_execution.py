"""PromptExecution — a runtime record of one prompt run.

Represents a single: render -> LLM -> response cycle. Useful for logging and
debugging (and later, persisted execution history). Runtime-only for now.
"""
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from src.modules.book_forge.ai.foundation.llm.models import LLMUsage


class ExecutionStatus(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


class PromptExecution(BaseModel):
    request_id: str = Field(default_factory=lambda: uuid4().hex)
    prompt_id: Optional[int] = None
    version: Optional[int] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    rendered_prompt: Optional[str] = None
    response: Optional[str] = None
    usage: Optional[LLMUsage] = None
    latency_ms: Optional[float] = None
    cost: Optional[float] = None
    status: ExecutionStatus = ExecutionStatus.PENDING
