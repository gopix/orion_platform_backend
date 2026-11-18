"""SemanticChunkStrategy — placeholder for meaning-aware chunking.

Deliberately not implemented yet. A semantic strategy decides chunk boundaries
from *meaning* rather than structure or size, so a future implementation may lean
on sentence embeddings, cosine similarity between adjacent sentences, detected
topic shifts, or light LLM assistance to find the seams.

Crucially, even then this strategy's only job is still to answer *where does the
next chunk begin and end?* — it does not generate embeddings, call the vector
database, persist chunks, or invoke the LLM directly. Those concerns live in
their own collaborators; the strategy would merely consume their output.

Until that work lands, ``chunk`` raises ``NotImplementedError`` so the contract
and the factory wiring can exist without a real implementation behind them.
"""
from src.modules.book_forge.ai.foundation.chunking.models.chunk_request import ChunkRequest
from src.modules.book_forge.ai.foundation.chunking.models.chunk_result import ChunkResult
from src.modules.book_forge.ai.foundation.chunking.strategies.base_chunk_strategy import (
    BaseChunkStrategy,
)


class SemanticChunkStrategy(BaseChunkStrategy):
    """Meaning-based chunking — not yet implemented."""

    def chunk(self, request: ChunkRequest) -> ChunkResult:
        raise NotImplementedError(
            "SemanticChunkStrategy is not implemented yet. Use HEADING (default), "
            "PARAGRAPH, or FIXED for now."
        )
