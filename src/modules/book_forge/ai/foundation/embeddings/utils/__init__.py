"""Embeddings utilities — stateless, pure helpers.

They depend only on the data models; providers and the service depend on them,
never the other way around.
"""
from src.modules.book_forge.ai.foundation.embeddings.utils.embedding_statistics import (
    EmbeddingStatisticsCalculator,
)

__all__ = ["EmbeddingStatisticsCalculator"]
