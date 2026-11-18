"""BlueprintContext — per-request collaborators injected into the blueprint graph.

The graph runtime calls nodes as ``fn(state)``, but the blueprint nodes need a
``db`` session (for the DB-backed Prompt Engine) and a few request-scoped knobs.
Rather than thread ``db`` through the state, we compile the blueprint graph
per-request with this context captured in the node closures (see
``build_blueprint_graph``). The service singletons (embedding, vector store,
guardrails, llm) are imported directly by the nodes — only the request-scoped
bits live here.
"""
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from src.modules.book_forge.ai.foundation.prompts.services import PromptService


@dataclass
class BlueprintContext:
    """Request-scoped dependencies for the blueprint workflow."""

    db: Session
    prompt_service: PromptService
    top_k: int = 20
    created_by: Optional[int] = None
