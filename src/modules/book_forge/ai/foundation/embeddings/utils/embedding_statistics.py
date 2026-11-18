"""EmbeddingStatisticsCalculator — derive summary statistics from embeddings.

Statistics are a cross-cutting concern: the provider shouldn't compute them and
neither should the service — this utility owns that responsibility (parallel to
the chunking module's ``ChunkStatisticsCalculator``)::

    EmbeddingService
        │
        ▼
    Provider.generate_embeddings()
        │
        ▼
    EmbeddingStatisticsCalculator.calculate(...)
        │
        ▼
    EmbeddingResponse

It reports total embeddings, dimension (average/min/max, plus a single
representative value when uniform), total and average processing time, and the
estimated cost. Latency and cost are read from ``usage``; the vectors supply the
dimensions. Stateless and pure: no I/O, no configuration.
"""
from typing import List, Optional

from src.modules.book_forge.ai.foundation.embeddings.models.embedding_response import (
    EmbeddingStatistics,
)
from src.modules.book_forge.ai.foundation.embeddings.models.embedding_usage import EmbeddingUsage
from src.modules.book_forge.ai.foundation.embeddings.models.embedding_vector import (
    EmbeddingVector,
)


class EmbeddingStatisticsCalculator:
    """Compute an :class:`EmbeddingStatistics` from vectors (+ optional usage)."""

    @staticmethod
    def calculate(
        vectors: List[EmbeddingVector],
        usage: Optional[EmbeddingUsage] = None,
    ) -> EmbeddingStatistics:
        """Summarise ``vectors``, sourcing latency/cost from ``usage`` if given."""
        total_latency = usage.latency_ms if usage is not None else None
        estimated_cost = usage.estimated_cost if usage is not None else None

        if not vectors:
            # Nothing embedded, but still surface any latency/cost that occurred.
            return EmbeddingStatistics(
                total_latency_ms=EmbeddingStatisticsCalculator._round(total_latency),
                estimated_cost=estimated_cost,
            )

        dimensions = [v.dimension for v in vectors]
        count = len(vectors)
        average_latency = total_latency / count if total_latency is not None else None
        uniform_dimension = dimensions[0] if len(set(dimensions)) == 1 else None

        return EmbeddingStatistics(
            total_vectors=count,
            dimension=uniform_dimension,
            average_dimension=round(sum(dimensions) / count, 2),
            min_dimension=min(dimensions),
            max_dimension=max(dimensions),
            total_latency_ms=EmbeddingStatisticsCalculator._round(total_latency),
            average_latency_ms=EmbeddingStatisticsCalculator._round(average_latency),
            estimated_cost=estimated_cost,
        )

    @staticmethod
    def _round(value: Optional[float]) -> Optional[float]:
        return round(value, 2) if value is not None else None
