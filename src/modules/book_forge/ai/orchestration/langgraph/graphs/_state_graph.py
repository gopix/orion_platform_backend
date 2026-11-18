"""Minimal StateGraph runtime (private) — a stand-in for the real LangGraph.

Mirrors LangGraph's building API (``add_node`` / ``add_edge`` /
``add_conditional_edges`` / ``set_entry_point`` / ``compile``) so the graph
definitions in this package read the same as they would against ``langgraph``.
Swap this for ``from langgraph.graph import StateGraph, START, END`` once that
dependency is added — the graph files won't change.

A compiled graph exposes ``invoke(state) -> state`` (the ``WorkflowEngine``
contract): it walks nodes from the entry point, following edges and conditional
routers, calling each node ``fn(state) -> state`` until it reaches ``END``. Node
failures become ``NodeExecutionException``; malformed graphs become
``InvalidGraphException``.
"""
from typing import Any, Callable, Dict, Optional, Tuple

from src.modules.book_forge.ai.orchestration.langgraph.exceptions import (
    GraphExecutionException,
    InvalidGraphException,
    NodeExecutionException,
)
from src.modules.book_forge.ai.orchestration.workflow_state import WorkflowStatus

START = "__start__"
END = "__end__"

NodeFn = Callable[[Any], Any]
Router = Callable[[Any], str]

_MAX_STEPS = 100  # safety valve against runaway loops


class CompiledGraph:
    """An executable graph produced by ``StateGraph.compile()``."""

    def __init__(
        self,
        nodes: Dict[str, NodeFn],
        entry: str,
        edges: Dict[str, str],
        conditionals: Dict[str, Tuple[Router, Dict[str, str]]],
    ) -> None:
        self._nodes = nodes
        self._entry = entry
        self._edges = edges
        self._conditionals = conditionals

    def invoke(self, state: Any) -> Any:
        """Run the graph over ``state`` and return the (updated) state."""
        current = self._entry
        steps = 0
        while current != END:
            if steps > _MAX_STEPS:
                raise GraphExecutionException(
                    "Graph exceeded the maximum number of steps.",
                    details={"max_steps": _MAX_STEPS},
                )
            state = self._run_node(current, state)
            # An agent that failed marks the state FAILED without raising; stop.
            if getattr(state, "status", None) == WorkflowStatus.FAILED:
                return state
            current = self._next(current, state)
            steps += 1

        if getattr(state, "status", None) != WorkflowStatus.FAILED:
            state.complete()
        return state

    def _run_node(self, name: str, state: Any) -> Any:
        node = self._nodes[name]
        try:
            result = node(state)
        except GraphExecutionException:
            raise
        except Exception as exc:  # noqa: BLE001 - translated to a domain error
            raise NodeExecutionException(
                f"Node '{name}' failed: {exc}", node=name, cause=exc
            )
        return result if result is not None else state

    def _next(self, current: str, state: Any) -> str:
        if current in self._conditionals:
            router, mapping = self._conditionals[current]
            key = router(state)
            target = mapping.get(key)
            if target is None:
                raise GraphExecutionException(
                    f"Router for '{current}' returned unmapped key '{key}'.",
                    details={"node": current, "key": key},
                )
            return target
        return self._edges.get(current, END)


class StateGraph:
    """Builder for a workflow graph: declare nodes, edges, and branches."""

    def __init__(self) -> None:
        self._nodes: Dict[str, NodeFn] = {}
        self._edges: Dict[str, str] = {}
        self._conditionals: Dict[str, Tuple[Router, Dict[str, str]]] = {}
        self._entry: Optional[str] = None

    def add_node(self, name: str, fn: NodeFn) -> "StateGraph":
        self._nodes[name] = fn
        return self

    def set_entry_point(self, name: str) -> "StateGraph":
        self._entry = name
        return self

    def add_edge(self, source: str, target: str) -> "StateGraph":
        self._edges[source] = target
        return self

    def add_conditional_edges(
        self, source: str, router: Router, mapping: Dict[str, str]
    ) -> "StateGraph":
        self._conditionals[source] = (router, mapping)
        return self

    def compile(self) -> CompiledGraph:
        """Validate structure and return an executable graph."""
        if not self._entry:
            raise InvalidGraphException("Graph has no entry point.")
        if self._entry not in self._nodes:
            raise InvalidGraphException(
                f"Entry point '{self._entry}' is not a node.",
                details={"entry": self._entry},
            )
        self._validate_targets()
        return CompiledGraph(
            self._nodes, self._entry, self._edges, self._conditionals
        )

    def _validate_targets(self) -> None:
        known = set(self._nodes) | {END}
        for source, target in self._edges.items():
            if source not in self._nodes:
                raise InvalidGraphException(f"Edge from unknown node '{source}'.")
            if target not in known:
                raise InvalidGraphException(
                    f"Edge from '{source}' points to unknown node '{target}'."
                )
        for source, (_router, mapping) in self._conditionals.items():
            if source not in self._nodes:
                raise InvalidGraphException(
                    f"Conditional edge from unknown node '{source}'."
                )
            for key, target in mapping.items():
                if target not in known:
                    raise InvalidGraphException(
                        f"Conditional edge '{source}'[{key}] points to unknown "
                        f"node '{target}'."
                    )
