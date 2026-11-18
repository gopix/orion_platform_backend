"""Provider-agnostic request/response models for LLM calls.

These are plain data contracts only — no provider SDK logic lives here. A
provider client (e.g. Anthropic) is responsible for translating an ``LLMRequest``
into its own API call and mapping the raw result back into an ``LLMResponse``.
"""
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, computed_field


class LLMRole(str, Enum):
    """Conversation roles supported across providers."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class LLMMessage(BaseModel):
    """A single message in a conversation."""

    role: LLMRole
    content: str


class LLMUsage(BaseModel):
    """Token accounting and cost record for a single LLM call.

    ``input_tokens`` / ``output_tokens`` are set by the provider. The remaining
    fields (provider, model, latency_ms, estimated_cost) are enriched by
    ``LLMService`` after the call, so ``response.usage`` becomes a self-contained
    record suitable for logging, persistence, and dashboards.
    """

    input_tokens: int = 0
    output_tokens: int = 0

    # Enriched by the service layer.
    provider: Optional[str] = None
    model: Optional[str] = None
    latency_ms: Optional[float] = None
    estimated_cost: Optional[float] = None

    @computed_field  # included in model_dump() / JSON output
    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class LLMRequest(BaseModel):
    """Everything needed to make one LLM completion request.

    The fields below the divider are for traceability/observability only — they
    are never sent to the provider API, but let us answer later questions like
    "which project generated this response?".
    """

    model: str
    messages: List[LLMMessage]
    max_tokens: int = Field(1024, ge=1)
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    system: Optional[str] = None
    stop_sequences: Optional[List[str]] = None

    # --- Traceability (not forwarded to the provider) --- #
    request_id: str = Field(default_factory=lambda: uuid4().hex)
    project_id: Optional[int] = None
    document_id: Optional[int] = None
    user_id: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    """The normalized result of an LLM completion request."""

    content: str
    model: str
    usage: LLMUsage = Field(default_factory=LLMUsage)
    stop_reason: Optional[str] = None
    response_id: Optional[str] = None
