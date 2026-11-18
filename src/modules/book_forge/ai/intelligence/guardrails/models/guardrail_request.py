"""GuardrailRequest — everything needed to run guardrail validation.

Carries the ``prompt`` (and optionally the ``output`` to check on the way back),
plus context, metadata, the operation being guarded, and the target LLM provider.
Data model only — no behaviour.
"""
from typing import Any, Dict, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class GuardrailRequest(BaseModel):
    # The prompt/input to validate.
    prompt: str
    # The generated output to validate (for output-side guardrails).
    output: Optional[str] = None

    # Additional context the rules may need (retrieved docs, system prompt, ...).
    context: Optional[str] = None
    # The operation being guarded (e.g. "generate", "summarize").
    operation: Optional[str] = None
    # Which LLM provider the operation targets.
    llm_provider: Optional[str] = None

    # Traceability / free-form context.
    request_id: str = Field(default_factory=lambda: uuid4().hex)
    metadata: Dict[str, Any] = Field(default_factory=dict)
