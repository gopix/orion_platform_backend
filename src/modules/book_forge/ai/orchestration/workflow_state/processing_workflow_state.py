"""ProcessingWorkflowState — the state threaded through the book-processing graph.

One object flows through every node, growing as it goes::

    project_id, documents
      -> parsed_documents   (ParserNode)
      -> knowledge_graph    (KnowledgeGraphNode)
      -> chunks             (ChunkingNode)
      -> embeddings         (EmbeddingNode)
      -> vector_ids         (VectorStoreNode)

Each node reads what it needs and writes its output back. Skipped stages (e.g.
embeddings without credentials) are recorded in ``skipped``.
"""
from typing import Any, Dict, List, Optional

from pydantic import Field

from src.modules.book_forge.ai.foundation.chunking.models.chunk import Chunk
from src.modules.book_forge.ai.foundation.embeddings.models.embedding_vector import (
    EmbeddingVector,
)
from src.modules.book_forge.ai.intelligence.knowledge_graph.models import (
    KnowledgeGraph,
)
from src.modules.book_forge.ai.intelligence.parsers.models import ParsedDocument
from src.modules.book_forge.ai.orchestration.workflow_state.base_workflow_state import (
    BaseWorkflowState,
)


class ProcessingWorkflowState(BaseWorkflowState):
    # Input: lightweight document descriptors {id, project_id, filename, file_path}.
    documents: List[Dict[str, Any]] = Field(default_factory=list)

    # Accumulated outputs, one stage per node.
    parsed_documents: List[ParsedDocument] = Field(default_factory=list)
    knowledge_graph: Optional[KnowledgeGraph] = None
    chunks: List[Chunk] = Field(default_factory=list)
    embeddings: List[EmbeddingVector] = Field(default_factory=list)
    vector_ids: List[str] = Field(default_factory=list)

    # Stages intentionally skipped (e.g. missing provider config), for reporting.
    skipped: List[str] = Field(default_factory=list)

    def skip(self, stage: str, reason: str) -> "ProcessingWorkflowState":
        """Record that a stage was skipped (non-fatal)."""
        self.skipped.append(stage)
        self.add_message("system", f"Skipped {stage}: {reason}")
        return self
