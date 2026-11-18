"""RetrieveKnowledgeNode — the RAG retrieval step for the blueprint workflow.

Owns retrieval only: build the system-generated query (Prompt Engine), embed it
with the SAME model used at ingestion, and search the project's vector namespace.
The retrieved chunks are written onto the state for the generation agent to use.
"""
from typing import List, Optional

from src.core.config import settings
from src.modules.book_forge.ai.foundation.chunking.models.chunk import Chunk
from src.modules.book_forge.ai.foundation.embeddings.models import EmbeddingRequest
from src.modules.book_forge.ai.foundation.embeddings.services import embedding_service
from src.modules.book_forge.ai.foundation.vector_store.models import VectorSearchRequest
from src.modules.book_forge.ai.foundation.prompts.repositories import PromptRepository
from src.modules.book_forge.ai.foundation.vector_store.services import (
    vector_store_service,
)
# The query and generation prompts share the same project-variable contract and
# category-resolution; those helpers live with the generation agent (nodes depend
# on agents, not vice versa).
from src.modules.book_forge.ai.orchestration.agents.blueprint_generation_agent import (
    build_prompt_variables,
    resolve_template_name,
)
from src.modules.book_forge.ai.orchestration.blueprint_context import BlueprintContext
from src.modules.book_forge.ai.orchestration.workflow_state import BlueprintState

QUERY_TEMPLATE = "blueprint_query"


class RetrieveKnowledgeNode:
    """Graph node that retrieves project knowledge for the blueprint."""

    name = "retrieve_knowledge"

    def __init__(self, *, context: BlueprintContext) -> None:
        self._context = context

    def __call__(self, state: BlueprintState) -> BlueprintState:
        state.advance("retrieve_knowledge")
        context = self._context

        category = (state.project_metadata or {}).get("category")
        query_template = resolve_template_name(
            PromptRepository(context.db), QUERY_TEMPLATE, category
        )
        query = context.prompt_service.render_prompt(
            query_template, build_prompt_variables(state)
        ).rendered_text
        state.query = query

        query_vector = _embed_query(query, project_id=state.project_id)
        results = vector_store_service.search(
            VectorSearchRequest(
                query_vector=query_vector,
                top_k=context.top_k,
                collection=f"project_{state.project_id}",
            )
        )

        state.retrieved_chunks = [
            {
                "text": r.text,
                "score": r.score,
                "document_id": (r.metadata or {}).get("document_id"),
                "chunk_index": r.chunk_index,
            }
            for r in results
        ]
        state.retrieval_metadata = {"top_k": context.top_k, "count": len(results)}
        state.add_message(
            "system", f"Retrieved {len(results)} chunk(s) for the blueprint."
        )
        return state


def _embed_query(text: str, *, project_id: Optional[int]) -> List[float]:
    """Embed a single query string with the SAME model used at ingestion."""
    response = embedding_service.embed(
        EmbeddingRequest(
            chunks=[Chunk(chunk_index=0, text=text)],
            model=settings.embedding_model,
            provider=settings.embedding_provider,
            project_id=project_id,
        )
    )
    return response.vectors[0].embedding
