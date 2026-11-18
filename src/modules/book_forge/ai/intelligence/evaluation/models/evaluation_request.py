"""EvaluationRequest — everything needed to evaluate one AI operation.

Evaluation is cross-cutting: almost every AI module can be evaluated, so a request
names the ``module`` under test and carries its input, output, and (optionally) an
expected/reference output to compare against. Data model only — no behaviour.
"""
from enum import Enum
from typing import Any, Dict, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class AIModule(str, Enum):
    """The AI modules that can be evaluated."""

    PARSER = "parser"
    CHUNKING = "chunking"
    EMBEDDINGS = "embeddings"
    VECTOR_STORE = "vector_store"
    PROMPT = "prompt"
    GUARDRAILS = "guardrails"
    LLM = "llm"
    RETRIEVAL = "retrieval"
    KNOWLEDGE_GRAPH = "knowledge_graph"


class EvaluationRequest(BaseModel):
    # Which AI module/operation is being evaluated.
    module: AIModule
    # The operation's input and output being judged.
    input: Optional[Any] = None
    output: Optional[Any] = None
    # A reference/expected output to compare against, when available.
    expected_output: Optional[Any] = None

    # Traceability / free-form context (which metrics to run, thresholds, ...).
    request_id: str = Field(default_factory=lambda: uuid4().hex)
    metadata: Dict[str, Any] = Field(default_factory=dict)
