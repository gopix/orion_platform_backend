"""VectorStoreResponse — the outcome of a store operation.

Bundles what was stored (count, collection) with observability (latency) and a
success flag, rather than returning a bare boolean. Data model only — the store
layer fills these fields.
"""
from typing import Optional

from pydantic import BaseModel


class VectorStoreResponse(BaseModel):
    success: bool = False
    stored_count: int = 0
    collection: Optional[str] = None
    latency_ms: Optional[float] = None
    # Populated when ``success`` is False.
    error: Optional[str] = None
