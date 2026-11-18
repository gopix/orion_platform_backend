"""RetrievalEvaluator — measure vector-search retrieval quality (RAG).

Metrics: top-K relevance (precision@k against expected ids, or mean similarity),
duplicate chunks (unique ratio), and missing chunks (recall against expected).
Input is the list of search results (``VectorSearchResult`` or dicts with
``chunk_id``/``score``); ``expected_output`` is the ground-truth relevant chunk
ids. Heuristic baseline — stateless.
"""
import time

from src.modules.book_forge.ai.intelligence.evaluation.evaluators._common import (
    build_result,
    clamp,
    get,
    metric,
)
from src.modules.book_forge.ai.intelligence.evaluation.models import (
    AIModule,
    EvaluationRequest,
    EvaluationResult,
)


class RetrievalEvaluator:
    """Evaluate top-K relevance, duplicates, and recall of retrieval."""

    def evaluate(self, request: EvaluationRequest) -> EvaluationResult:
        start = time.perf_counter()
        results = list(request.input or [])
        if not results:
            return build_result(
                AIModule.RETRIEVAL,
                [metric("retrieved", 0.0)],
                start,
                recommendations=["No results were retrieved."],
            )

        k = len(results)
        ids = [get(r, "chunk_id") for r in results]
        scores = [float(get(r, "score", 0) or 0) for r in results]
        expected = set(request.expected_output or [])

        if expected:
            relevant = sum(1 for i in ids if i in expected)
            top_k_relevance = relevant / k                      # precision@k
            missing_chunks = clamp(relevant / len(expected))    # recall
        else:
            top_k_relevance = clamp(sum(scores) / k)            # mean similarity
            missing_chunks = 1.0                                # unknown -> assume ok

        identified = [i for i in ids if i is not None]
        duplicate_chunks = (
            len(set(identified)) / len(identified) if identified else 1.0
        )

        metrics = [
            metric("top_k_relevance", top_k_relevance),
            metric("duplicate_chunks", duplicate_chunks),
            metric("missing_chunks", missing_chunks),
        ]
        recs = []
        if top_k_relevance < 0.7:
            recs.append("Low top-K relevance; revisit the query embedding or index.")
        if duplicate_chunks < 0.7:
            recs.append("Duplicate chunks retrieved; dedupe at store or query time.")
        if missing_chunks < 0.7:
            recs.append("Relevant chunks are missing; increase top_k or improve recall.")
        return build_result(AIModule.RETRIEVAL, metrics, start, recommendations=recs)
