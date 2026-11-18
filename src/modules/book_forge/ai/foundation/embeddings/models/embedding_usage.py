"""EmbeddingUsage — token accounting and cost record for one embedding call.

The embeddings analogue of ``LLMUsage``. Embedding calls only consume input
tokens (there is no generated output), so a single ``total_tokens`` figure is
enough. The provider/model/latency/cost fields are enriched by the service layer
after the call, making ``response.usage`` a self-contained record for logging,
persistence, and cost dashboards.
"""
from typing import Optional

from pydantic import BaseModel


class EmbeddingUsage(BaseModel):
    """Usage and cost for a single embedding request."""

    # Embeddings consume input tokens only; there is no output.
    total_tokens: int = 0

    # --- Enriched by the service layer after the call --- #
    provider: Optional[str] = None
    model: Optional[str] = None
    latency_ms: Optional[float] = None
    estimated_cost: Optional[float] = None
