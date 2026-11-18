"""GraphNode — one node in the knowledge graph.

The generic node: an ``id``, a human-readable ``label`` (e.g. "Newton"), a
``type`` discriminator, and free-form ``properties``. ``Entity`` and ``Concept``
specialise this. Data model only — no behaviour.
"""
from enum import Enum
from typing import Any, Dict

from pydantic import BaseModel, Field


class NodeType(str, Enum):
    """Coarse node kinds. The ``type`` field is a plain string so extraction can
    also produce custom kinds, but these are the canonical values."""

    ENTITY = "entity"
    CONCEPT = "concept"


class GraphNode(BaseModel):
    id: str
    label: str
    # Node kind — "entity" / "concept" / a custom string.
    type: str = "node"
    properties: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"from_attributes": True}
