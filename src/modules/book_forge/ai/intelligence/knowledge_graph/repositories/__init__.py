"""Knowledge graph repositories — persistence behind a backend-agnostic interface."""
from src.modules.book_forge.ai.intelligence.knowledge_graph.repositories.graph_repository import (
    BaseGraphRepository,
    JsonGraphRepository,
)

__all__ = ["BaseGraphRepository", "JsonGraphRepository"]
