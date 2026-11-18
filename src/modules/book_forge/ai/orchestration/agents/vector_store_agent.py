"""VectorStoreAgent — upsert embeddings into the vector store.

Wraps the vector store service. Runs only when a vector provider is configured
(``settings.pinecone_api_key``); otherwise records a skip. Stores under the
project's collection and records the vector ids on the state.
"""
from src.core.config import settings
from src.modules.book_forge.ai.foundation.vector_store.models import VectorStoreRequest
from src.modules.book_forge.ai.foundation.vector_store.services import (
    vector_store_service,
)
from src.modules.book_forge.ai.orchestration.agents.base_agent import BaseAgent
from src.modules.book_forge.ai.orchestration.workflow_state import (
    ProcessingWorkflowState,
)


class VectorStoreAgent(BaseAgent[ProcessingWorkflowState]):
    """Persist the embeddings to the vector store (provider-gated)."""

    name = "Vector Store Agent"
    step = "vector_store"

    def execute(self, state: ProcessingWorkflowState) -> None:
        if not state.embeddings:
            state.skip("vector_store", "no embeddings to store")
            return
        if not settings.pinecone_api_key:
            state.skip("vector_store", "no vector provider configured")
            return

        collection = f"project_{state.project_id}"
        response = vector_store_service.store(
            VectorStoreRequest(
                project_id=state.project_id,
                vectors=state.embeddings,
                collection=collection,
                # Re-processing a project re-embeds all its documents, so replace
                # the whole namespace to guarantee no orphaned vectors survive
                # from a previous run (e.g. after changing chunking settings).
                replace=True,
            )
        )
        state.vector_ids = [self._vector_id(state.project_id, v) for v in state.embeddings]
        state.add_message(
            "assistant",
            f"Stored {response.stored_count} vector(s) in '{collection}'.",
        )

    @staticmethod
    def _vector_id(project_id, vector) -> str:
        ref = vector.chunk_id if vector.chunk_id is not None else vector.chunk_index
        return f"{project_id}:{ref}"
