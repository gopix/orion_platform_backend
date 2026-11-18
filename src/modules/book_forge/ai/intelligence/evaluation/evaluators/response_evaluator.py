"""ResponseEvaluator — measure the quality of an LLM response.

Metrics: completeness (covers required sections / adequate length), consistency
(agreement with a reference), faithfulness (grounding in provided context — the
inverse of hallucination), and structure (formatting present). Also fills a
``ScoreCard``. Input is the response text; ``expected_output`` is a reference and
``metadata['context']`` the source to ground against. Heuristic baseline —
stateless.
"""
import re
import time

from src.modules.book_forge.ai.intelligence.evaluation.evaluators._common import (
    build_result,
    clamp,
    metric,
    overlap,
)
from src.modules.book_forge.ai.intelligence.evaluation.models import (
    AIModule,
    EvaluationRequest,
    EvaluationResult,
    ScoreCard,
)

_STRUCTURE_RE = re.compile(r"(^|\n)\s*(#{1,6}\s|[-*]\s|\d+\.\s)")


class ResponseEvaluator:
    """Evaluate response completeness, consistency, faithfulness, structure."""

    def evaluate(self, request: EvaluationRequest) -> EvaluationResult:
        start = time.perf_counter()
        response = str(request.output or "")
        reference = request.expected_output
        meta = request.metadata or {}
        context = meta.get("context")
        required = meta.get("required_sections")

        if required:
            completeness = clamp(
                sum(1 for s in required if str(s).lower() in response.lower())
                / len(required)
            )
        else:
            completeness = clamp(len(response.split()) / 50.0)

        consistency = overlap(response, str(reference)) if reference else 1.0
        # Faithfulness = grounding in context; hallucination = 1 - faithfulness.
        faithfulness = overlap(response, str(context)) if context else 1.0
        structure = self._structure_score(response)

        metrics = [
            metric("completeness", completeness),
            metric("consistency", consistency),
            metric("faithfulness", faithfulness),
            metric("structure", structure),
        ]
        score_card = ScoreCard(
            accuracy=faithfulness,
            consistency=consistency,
            completeness=completeness,
        )
        recs = []
        if faithfulness < 0.7 and context:
            recs.append("Response may contain hallucinations; low grounding in context.")
        if completeness < 0.7:
            recs.append("Response looks incomplete; ensure all required content is present.")
        if structure < 0.7:
            recs.append("Add structure (headings/lists) to improve readability.")
        return build_result(
            AIModule.LLM, metrics, start, score_card=score_card, recommendations=recs
        )

    @staticmethod
    def _structure_score(response: str) -> float:
        if not response.strip():
            return 0.0
        score = 0.5  # non-empty prose
        if _STRUCTURE_RE.search(response) or "\n\n" in response:
            score += 0.5
        return clamp(score)
