"""EmbeddingResponse — the normalized result of an embedding request.

Rather than returning a bare ``List[List[float]]``, the service returns a
response object that bundles the vectors with usage and statistics — the same
philosophy as ``ChunkResult`` and ``LLMResponse``. Callers get a self-contained,
observable result and the return type can grow without breaking them. Data model
only — the service fills these fields; the model carries no logic.
"""
from typing import List, Optional

from pydantic import BaseModel, Field

from src.modules.book_forge.ai.foundation.embeddings.models.embedding_usage import EmbeddingUsage
from src.modules.book_forge.ai.foundation.embeddings.models.embedding_vector import (
    EmbeddingVector,
)


class EmbeddingStatistics(BaseModel):
    """Summary statistics over the produced vectors.

    Filled by ``EmbeddingStatisticsCalculator`` (not the provider or service) —
    useful later for dashboards and monitoring.
    """

    total_vectors: int = 0
    # Representative dimension when all vectors share one (the common case).
    dimension: Optional[int] = None
    average_dimension: Optional[float] = None
    min_dimension: Optional[int] = None
    max_dimension: Optional[int] = None
    # Processing time and cost, sourced from usage.
    total_latency_ms: Optional[float] = None
    average_latency_ms: Optional[float] = None
    estimated_cost: Optional[float] = None


class EmbeddingResponse(BaseModel):
    model: Optional[str] = None
    vectors: List[EmbeddingVector] = Field(default_factory=list)
    usage: EmbeddingUsage = Field(default_factory=EmbeddingUsage)
    statistics: EmbeddingStatistics = Field(default_factory=EmbeddingStatistics)
