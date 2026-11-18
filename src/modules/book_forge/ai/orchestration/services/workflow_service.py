"""Workflow orchestration service — lifecycle & state, not agent execution.

This service manages a workflow's *lifecycle* and *state*; it does NOT execute
agents. Agent execution is the LangGraph engine's job, and the business logic
lives inside the agents. The service only:

* starts a workflow,
* resumes a paused/incomplete one,
* pauses or cancels one,
* loads and saves workflow state,
* delegates actual execution to the injected LangGraph engine.

    WorkflowService  --(state)-->  LangGraph engine  --(runs agents)-->  state

The engine is injected as anything exposing ``invoke(state) -> state``, so this
service stays decoupled from the engine implementation (and testable without it).
"""
import time
from typing import Dict, Optional, Protocol

from src.core.logger import get_logger
from src.modules.book_forge.ai.orchestration.exceptions import (
    StateException,
    WorkflowException,
)
from src.modules.book_forge.ai.orchestration.workflow_state import (
    BaseWorkflowState,
    WorkflowStatus,
)

logger = get_logger(__name__)

# Terminal statuses a workflow can't be resumed from.
_TERMINAL = {WorkflowStatus.COMPLETED, WorkflowStatus.CANCELLED}


class WorkflowEngine(Protocol):
    """A LangGraph-style engine: runs the graph over a state and returns it."""

    def invoke(self, state: BaseWorkflowState) -> BaseWorkflowState: ...


class InMemoryStateStore:
    """Default state store — keeps states in memory, keyed by ``run_id``."""

    def __init__(self) -> None:
        self._data: Dict[str, BaseWorkflowState] = {}

    def save(self, state: BaseWorkflowState) -> str:
        self._data[state.run_id] = state
        return state.run_id

    def load(self, run_id: str) -> BaseWorkflowState:
        state = self._data.get(run_id)
        if state is None:
            raise WorkflowException(
                f"Workflow '{run_id}' not found.", details={"run_id": run_id}
            )
        return state

    def exists(self, run_id: str) -> bool:
        return run_id in self._data


class WorkflowService:
    """Manage workflow lifecycle and state; delegate execution to the engine."""

    def __init__(
        self,
        *,
        engine: Optional[WorkflowEngine] = None,
        state_store: Optional[InMemoryStateStore] = None,
    ) -> None:
        self._engine = engine
        self._store = state_store or InMemoryStateStore()

    # -- lifecycle ---------------------------------------------------------

    def start(
        self, state: BaseWorkflowState, *, engine: Optional[WorkflowEngine] = None
    ) -> BaseWorkflowState:
        """Persist the initial state and run it via the engine."""
        self._require_state(state)
        state.status = WorkflowStatus.RUNNING
        self.save(state)
        return self._execute(state, engine, "start")

    def resume(
        self, run_id: str, *, engine: Optional[WorkflowEngine] = None
    ) -> BaseWorkflowState:
        """Load a saved state and continue running it via the engine."""
        state = self.load(run_id)
        if state.status in _TERMINAL:
            raise WorkflowException(
                f"Cannot resume a {state.status.value} workflow.",
                details={"run_id": run_id, "status": state.status.value},
            )
        state.status = WorkflowStatus.RUNNING
        self.save(state)
        return self._execute(state, engine, "resume")

    def pause(self, run_id: str) -> BaseWorkflowState:
        """Mark a workflow paused (no execution)."""
        return self._set_status(run_id, WorkflowStatus.PAUSED, "pause")

    def cancel(self, run_id: str) -> BaseWorkflowState:
        """Mark a workflow cancelled (no execution)."""
        return self._set_status(run_id, WorkflowStatus.CANCELLED, "cancel")

    # -- state persistence -------------------------------------------------

    def save(self, state: BaseWorkflowState) -> str:
        """Persist a workflow state; returns its ``run_id``."""
        self._require_state(state)
        return self._store.save(state)

    def load(self, run_id: str) -> BaseWorkflowState:
        """Load a persisted workflow state by id."""
        return self._store.load(run_id)

    def get_status(self, run_id: str) -> WorkflowStatus:
        return self.load(run_id).status

    # -- internals ---------------------------------------------------------

    def _execute(
        self,
        state: BaseWorkflowState,
        engine: Optional[WorkflowEngine],
        action: str,
    ) -> BaseWorkflowState:
        """Delegate execution to the engine (which runs the agents)."""
        engine = engine or self._engine
        if engine is None:
            raise WorkflowException(
                "No workflow engine configured; cannot execute.",
                details={"run_id": state.run_id, "action": action},
            )

        start = time.perf_counter()
        error: Optional[BaseException] = None
        result = state
        try:
            result = engine.invoke(state)
            return result
        except WorkflowException:
            raise
        except Exception as exc:  # noqa: BLE001 - translated to a domain error
            error = exc
            state.fail(f"Engine execution failed: {exc}")
            self.save(state)
            raise WorkflowException(
                f"Workflow '{state.run_id}' failed during {action}: {exc}",
                details={"run_id": state.run_id, "action": action},
                cause=exc,
            )
        finally:
            self.save(result)
            duration_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "Workflow %s | run_id=%s | status=%s | duration_ms=%.1f | success=%s",
                action, state.run_id, result.status.value, duration_ms, error is None,
            )

    def _set_status(
        self, run_id: str, status: WorkflowStatus, action: str
    ) -> BaseWorkflowState:
        state = self.load(run_id)
        if state.status in _TERMINAL:
            raise WorkflowException(
                f"Cannot {action} a {state.status.value} workflow.",
                details={"run_id": run_id, "status": state.status.value},
            )
        state.status = status
        self.save(state)
        logger.info("Workflow %s | run_id=%s | status=%s", action, run_id, status.value)
        return state

    def _require_state(self, state: BaseWorkflowState) -> None:
        if not isinstance(state, BaseWorkflowState):
            raise StateException(
                f"Expected a workflow state, got {type(state).__name__}.",
                field="state",
            )
        if not state.run_id:
            raise StateException("Workflow state has no run_id.", field="run_id")


# Shared singleton — an engine must be injected (or passed per-call) to execute.
workflow_service = WorkflowService()
