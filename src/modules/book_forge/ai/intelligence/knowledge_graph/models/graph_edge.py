"""GraphEdge — one directed relationship between two nodes.

    Newton  --DISCOVERED-->  Laws of Motion

Holds the ``source`` and ``target`` node ids, the ``relationship_type`` (a value
from ``RelationshipType`` or a custom string), and a ``confidence`` for
extraction. Data model only — no behaviour.
"""
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class GraphEdge(BaseModel):
    # Node ids this edge connects.
    source: str
    target: str
    # The relationship (e.g. "DISCOVERED", "IS_A"); see RelationshipType.
    relationship_type: str
    # Extraction confidence in [0, 1].
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    properties: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"from_attributes": True}
