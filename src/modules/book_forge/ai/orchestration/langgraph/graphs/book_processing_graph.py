"""BookProcessingGraph — the document-ingestion workflow.

    START -> parser -> knowledge_graph -> chunking -> embedding -> vector_store -> END

One ``ProcessingWorkflowState`` flows through every node, growing at each stage
(parsed_documents -> knowledge_graph -> chunks -> embeddings -> vector_ids).
Defines nodes and edges — nothing else. Adding OCR, parallelism, or a review
loop-back later is a change *here*, never in the calling service.
"""
from src.modules.book_forge.ai.orchestration.langgraph.graphs._state_graph import (
    END,
    CompiledGraph,
    StateGraph,
)
from src.modules.book_forge.ai.orchestration.langgraph.nodes import (
    ChunkingNode,
    EmbeddingNode,
    KnowledgeGraphNode,
    ParserNode,
    VectorStoreNode,
)


def build_book_processing_graph() -> CompiledGraph:
    """Build and compile the book-processing workflow graph."""
    graph = StateGraph()
    graph.add_node("parser", ParserNode())
    graph.add_node("knowledge_graph", KnowledgeGraphNode())
    graph.add_node("chunking", ChunkingNode())
    graph.add_node("embedding", EmbeddingNode())
    graph.add_node("vector_store", VectorStoreNode())

    graph.set_entry_point("parser")
    graph.add_edge("parser", "knowledge_graph")
    graph.add_edge("knowledge_graph", "chunking")
    graph.add_edge("chunking", "embedding")
    graph.add_edge("embedding", "vector_store")
    graph.add_edge("vector_store", END)
    return graph.compile()
