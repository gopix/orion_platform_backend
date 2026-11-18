"""Graph execution service — the engine layer for the LangGraph graphs.

Its only job is to run graphs; it holds no business logic:

    compile graph  ->  execute graph  ->  (resume graph)  ->  return final state

It owns a registry of named graph builders, compiles them (caching the default
build), and invokes the compiled graph over a state. The compiled graph exposes
``invoke(state) -> state``, so ``engine_for(name)`` yields a ``WorkflowEngine`` the
``WorkflowService`` can drive.
"""
import time
from typing import Callable, Dict, List, Optional

from src.core.logger import get_logger
from src.modules.book_forge.ai.orchestration.langgraph.exceptions import (
    GraphExecutionException,
)
from src.modules.book_forge.ai.orchestration.langgraph.graphs import (
    build_blueprint_graph,
    build_book_processing_graph,
    build_interview_graph,
    build_review_graph,
)
from src.modules.book_forge.ai.orchestration.langgraph.graphs._state_graph import (
    CompiledGraph,
)

logger = get_logger(__name__)

GraphBuilder = Callable[..., CompiledGraph]


class GraphExecutionService:
    """Compile and run named workflow graphs."""

    def __init__(self, *, graphs: Optional[Dict[str, GraphBuilder]] = None) -> None:
        self._builders: Dict[str, GraphBuilder] = graphs or {
            "interview": build_interview_graph,
            "blueprint": build_blueprint_graph,
            "review": build_review_graph,
            "book_processing": build_book_processing_graph,
        }
        # Cache of compiled graphs built with default arguments.
        self._compiled: Dict[str, CompiledGraph] = {}

    def register(self, name: str, builder: GraphBuilder) -> None:
        """Register (or override) a graph builder; clears its cached compile."""
        self._builders[name] = builder
        self._compiled.pop(name, None)

    def available(self) -> List[str]:
        return list(self._builders)

    # -- compile -----------------------------------------------------------

    def compile(self, name: str, **build_kwargs) -> CompiledGraph:
        """Compile the named graph. Default builds are cached; custom args aren't."""
        builder = self._builders.get(name)
        if builder is None:
            raise GraphExecutionException(
                f"Unknown graph '{name}'. Available: {', '.join(self.available())}.",
                details={"graph": name},
            )
        if build_kwargs:
            return builder(**build_kwargs)
        if name not in self._compiled:
            self._compiled[name] = builder()
        return self._compiled[name]

    # -- execute / resume --------------------------------------------------

    def execute(self, name: str, state, **build_kwargs):
        """Compile (if needed) and run the graph, returning the final state."""
        return self._run("execute", name, state, build_kwargs)

    def resume(self, name: str, state, **build_kwargs):
        """Continue a graph from an existing state, returning the final state.

        The current runtime restarts from the graph's entry point; true
        checkpoint-based resume arrives with the real LangGraph engine.
        """
        return self._run("resume", name, state, build_kwargs)

    # -- internals ---------------------------------------------------------

    def _run(self, action: str, name: str, state, build_kwargs: dict):
        graph = self.compile(name, **build_kwargs)
        start = time.perf_counter()
        error: Optional[BaseException] = None
        result = state
        try:
            result = graph.invoke(state)
            return result
        except GraphExecutionException:
            raise
        except Exception as exc:  # noqa: BLE001 - translated to a domain error
            error = exc
            raise GraphExecutionException(
                f"Graph '{name}' failed during {action}: {exc}",
                details={"graph": name, "action": action},
                cause=exc,
            )
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            status = getattr(getattr(result, "status", None), "value", "n/a")
            log = logger.info if error is None else logger.error
            log(
                "Graph %s | graph=%s | status=%s | duration_ms=%.1f | success=%s",
                action, name, status, duration_ms, error is None,
            )

    # -- engine adapter ----------------------------------------------------

    def engine_for(self, name: str, **build_kwargs) -> "GraphEngine":
        """Return a ``WorkflowEngine`` (``invoke(state) -> state``) for one graph."""
        return GraphEngine(self, name, build_kwargs)


class GraphEngine:
    """Adapter exposing a single named graph as a ``WorkflowEngine``."""

    def __init__(
        self, service: GraphExecutionService, name: str, build_kwargs: dict
    ) -> None:
        self._service = service
        self._name = name
        self._build_kwargs = build_kwargs

    def invoke(self, state):
        return self._service.execute(self._name, state, **self._build_kwargs)


# Shared singleton — import this from other modules.
graph_execution_service = GraphExecutionService()
