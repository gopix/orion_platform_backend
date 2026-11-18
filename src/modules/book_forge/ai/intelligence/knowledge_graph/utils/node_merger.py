"""NodeMerger — collapse duplicate nodes that refer to the same thing.

Extraction often yields the same entity under slightly different surface forms
("Open AI" and "OpenAI"). This merges them into a single node, keeps the variants
as ``aliases``, and rewrites every edge to point at the canonical node (dropping
any duplicate edges that result). Works on lightweight node/edge dicts. Stateless
and pure — returns new lists, never mutates the inputs.
"""
import re
from typing import Any, Callable, List, Optional, Tuple

from src.modules.book_forge.ai.intelligence.knowledge_graph.utils._access import (
    get_edge_type,
    get_field,
)

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


class NodeMerger:
    """Merge duplicate/equivalent nodes and remap their edges."""

    @staticmethod
    def merge(
        nodes: List[Any],
        edges: List[Any],
        *,
        key: Optional[Callable[[str], str]] = None,
    ) -> Tuple[List[dict], List[dict]]:
        """Return (merged_nodes, merged_edges).

        Two nodes merge when their names normalise to the same key. By default
        normalisation lowercases and strips non-alphanumerics, so "Open AI" and
        "OpenAI" collapse together. Pass ``key`` to customise.
        """
        normalise = key or NodeMerger._default_key

        canonical: dict = {}          # norm_key -> canonical node dict
        id_map: dict = {}             # original id -> canonical id

        for node in nodes:
            node_id = NodeMerger._node_id(node)
            name = NodeMerger._node_name(node)
            norm = normalise(name)

            if norm in canonical:
                canon = canonical[norm]
                id_map[node_id] = canon["id"]
                NodeMerger._add_alias(canon, name)
            else:
                canon = NodeMerger._as_dict(node)
                canon.setdefault("id", node_id)
                canon.setdefault("aliases", [])
                canonical[norm] = canon
                id_map[node_id] = canon["id"]

        merged_edges: List[dict] = []
        seen: set = set()
        for edge in edges:
            src = id_map.get(get_field(edge, "source"), get_field(edge, "source"))
            dst = id_map.get(get_field(edge, "target"), get_field(edge, "target"))
            etype = get_edge_type(edge)
            signature = (src, dst, etype)
            if signature in seen:
                continue  # duplicate edge after remap
            seen.add(signature)
            new_edge = NodeMerger._as_dict(edge)
            new_edge["source"] = src
            new_edge["target"] = dst
            merged_edges.append(new_edge)

        return list(canonical.values()), merged_edges

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _default_key(name: str) -> str:
        return _NON_ALNUM.sub("", (name or "").lower())

    @staticmethod
    def _add_alias(canon: dict, name: str) -> None:
        if not name:
            return
        canonical_name = canon.get("name") or canon.get("label")
        if name == canonical_name:
            return
        aliases = canon.setdefault("aliases", [])
        if name not in aliases:
            aliases.append(name)

    @staticmethod
    def _node_id(node: Any) -> Any:
        return (
            get_field(node, "id")
            or get_field(node, "name")
            or get_field(node, "label")
        )

    @staticmethod
    def _node_name(node: Any) -> str:
        return (
            get_field(node, "name")
            or get_field(node, "label")
            or get_field(node, "id")
            or ""
        )

    @staticmethod
    def _as_dict(obj: Any) -> dict:
        if isinstance(obj, dict):
            return dict(obj)  # copy — never mutate the input
        if hasattr(obj, "model_dump"):  # pydantic
            return obj.model_dump()
        return dict(getattr(obj, "__dict__", {}))
