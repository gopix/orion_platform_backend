"""BaseAgent — the contract every BookForge agent implements.

LangGraph-style: an agent is a node that receives a workflow state, updates it,
and returns it. This base provides the ``run`` template — advance the state to
this agent's step, invoke ``execute`` (the business logic), capture any error onto
the state, and return it — so concrete agents only implement ``execute``.

An optional ``llm`` callable is injected for agents that generate content; when
absent they fall back to deterministic heuristics (a documented seam for real LLM
generation later).
"""
import time
from abc import ABC, abstractmethod
from typing import Callable, Generic, Optional, TypeVar

from src.core.logger import get_logger
from src.modules.book_forge.ai.orchestration.workflow_state import BaseWorkflowState

logger = get_logger(__name__)

StateT = TypeVar("StateT", bound=BaseWorkflowState)
LLMCallable = Callable[[str], str]


class BaseAgent(ABC, Generic[StateT]):
    """Common contract and run-loop for all agents."""

    #: Human-readable agent name and the workflow step it represents.
    name: str = "agent"
    step: str = "agent"

    def __init__(self, *, llm: Optional[LLMCallable] = None) -> None:
        self._llm = llm

    def run(self, state: StateT) -> StateT:
        """Advance the state to this agent's step, execute, and return it."""
        state.advance(self.step)
        start = time.perf_counter()
        try:
            self.execute(state)
        except Exception as exc:  # noqa: BLE001 - captured onto the state
            state.fail(f"{self.name} failed: {exc}")
            logger.error("Agent '%s' failed: %s", self.name, exc)
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "Agent %s | step=%s | status=%s | duration_ms=%.1f",
            self.name, self.step, state.status.value, duration_ms,
        )
        return state

    @abstractmethod
    def execute(self, state: StateT) -> None:
        """Do this agent's work by mutating ``state`` in place."""
        raise NotImplementedError

    # -- helper ------------------------------------------------------------

    def _generate(self, prompt: str) -> Optional[str]:
        """Call the injected LLM if present, else return ``None`` (heuristic path)."""
        return self._llm(prompt) if self._llm is not None else None
