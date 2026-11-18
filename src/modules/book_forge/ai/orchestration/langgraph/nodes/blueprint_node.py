"""BlueprintNode — the graph step that generates the book blueprint.

Wraps ``BlueprintGenerationAgent``. The graph references the node; the node's
internals (the agent, its prompt/LLM/guardrail collaborators) can change without
the graph changing. Callable: ``node(state) -> state``.
"""
from typing import Optional

from src.modules.book_forge.ai.orchestration.agents import BlueprintGenerationAgent
from src.modules.book_forge.ai.orchestration.blueprint_context import BlueprintContext
from src.modules.book_forge.ai.orchestration.workflow_state import BlueprintState


class BlueprintNode:
    """Graph node wrapping the blueprint generation agent."""

    name = "blueprint"

    def __init__(
        self,
        *,
        context: BlueprintContext,
        agent: Optional[BlueprintGenerationAgent] = None,
    ) -> None:
        self._agent = agent or BlueprintGenerationAgent(context=context)

    def __call__(self, state: BlueprintState) -> BlueprintState:
        return self._agent.run(state)
