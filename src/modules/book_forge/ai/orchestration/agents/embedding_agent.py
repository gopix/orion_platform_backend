"""EmbeddingAgent — embed the chunks.

Wraps the embedding service. Runs only when an embedding provider is configured
(``settings.openai_api_key``); otherwise records a skip so the workflow still
completes without credentials.
"""
from src.core.config import settings
from src.modules.book_forge.ai.foundation.embeddings.models import EmbeddingRequest
from src.modules.book_forge.ai.foundation.embeddings.services import embedding_service
from src.modules.book_forge.ai.orchestration.agents.base_agent import BaseAgent
from src.modules.book_forge.ai.orchestration.workflow_state import (
    ProcessingWorkflowState,
)


class EmbeddingAgent(BaseAgent[ProcessingWorkflowState]):
    """Generate embeddings for the chunks (provider-gated)."""

    name = "Embedding Agent"
    step = "embedding"

    def execute(self, state: ProcessingWorkflowState) -> None:
        if not state.chunks:
            state.skip("embedding", "no chunks to embed")
            return
        if not settings.openai_api_key:
            state.skip("embedding", "no embedding provider configured")
            return

        response = embedding_service.embed(
            EmbeddingRequest(
                chunks=state.chunks,
                model=settings.embedding_model,
                provider=settings.embedding_provider,
                project_id=state.project_id,
            )
        )
        state.embeddings = response.vectors
        state.add_message("assistant", f"Embedded {len(response.vectors)} chunk(s).")
