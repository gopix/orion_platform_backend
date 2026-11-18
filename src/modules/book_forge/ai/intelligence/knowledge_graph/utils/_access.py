"""Tiny internal accessor shared by the graph utils.

Lets the utilities read a field whether a node/edge is a plain dict or an object
with attributes, so they work with the interim dict representation and with real
graph models later.
"""
from typing import Any


def get_field(obj: Any, key: str, default: Any = None) -> Any:
    """Read ``key`` from ``obj`` whether it's a dict or an attributes object."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def get_edge_type(edge: Any) -> Any:
    """Edge relationship label, tolerant of dict ('type') and model
    ('relationship_type') representations."""
    return get_field(edge, "type") or get_field(edge, "relationship_type")
