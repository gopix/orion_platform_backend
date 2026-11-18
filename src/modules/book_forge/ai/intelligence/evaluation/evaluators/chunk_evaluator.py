"""ChunkEvaluator — measure the quality of a document's chunks.

Metrics: average size (close to a target token budget), heading preservation
(chunks retain locating context), and semantic boundaries (chunks end on
sentence boundaries). Input is a list of chunks (or a ``ChunkResult``); each chunk
may be a ``Chunk`` model or a dict. Heuristic baseline — stateless.
"""
import time

from src.modules.book_forge.ai.foundation.chunking.utils import TokenEstimator
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

_SENTENCE_ENDINGS = (".", "!", "?", '"', "”")


class ChunkEvaluator:
    """Evaluate chunk size, heading preservation, and boundary cleanliness."""

    def evaluate(self, request: EvaluationRequest) -> EvaluationResult:
        start = time.perf_counter()
        chunks = self._as_list(request.input)
        if not chunks:
            return build_result(
                AIModule.CHUNKING,
                [metric("chunk_count", 0.0)],
                start,
                recommendations=["No chunks were produced."],
            )

        target = (request.metadata or {}).get("target_tokens", 512)
        n = len(chunks)
        sizes = [self._tokens(c) for c in chunks]
        avg = sum(sizes) / n
        average_size = clamp(1 - abs(avg - target) / target)

        with_heading = sum(1 for c in chunks if get(c, "heading") or get(c, "section"))
        heading_preservation = with_heading / n

        clean = sum(
            1 for c in chunks if str(get(c, "text", "")).rstrip().endswith(_SENTENCE_ENDINGS)
        )
        semantic_boundaries = clean / n

        metrics = [
            metric("average_size", average_size),
            metric("heading_preservation", heading_preservation),
            metric("semantic_boundaries", semantic_boundaries),
        ]
        recs = []
        if average_size < 0.7:
            recs.append(f"Average chunk size ({avg:.0f} tokens) is far from target {target}.")
        if heading_preservation < 0.7:
            recs.append("Many chunks lack heading/section context; prefer heading-based chunking.")
        if semantic_boundaries < 0.7:
            recs.append("Chunks often split mid-sentence; align to sentence boundaries.")
        return build_result(AIModule.CHUNKING, metrics, start, recommendations=recs)

    @staticmethod
    def _as_list(value):
        if value is None:
            return []
        # Accept a ChunkResult (has .chunks) or a bare list.
        inner = getattr(value, "chunks", None)
        return inner if inner is not None else list(value)

    @staticmethod
    def _tokens(chunk) -> int:
        meta = get(chunk, "metadata")
        estimated = getattr(meta, "estimated_tokens", None) if meta is not None else None
        if estimated:
            return estimated
        return TokenEstimator.estimate(str(get(chunk, "text", "")))
