"""PromptEvaluator — measure the quality of a prompt/template.

Metrics: prompt completeness (has enough instruction), variable usage (template
variables present / expected), and token efficiency (concise for its budget).
Input is the prompt string; ``metadata`` may carry ``expected_variables`` and
``target_tokens``. Heuristic baseline — stateless.
"""
import re
import time

from src.modules.book_forge.ai.foundation.chunking.utils import TokenEstimator
from src.modules.book_forge.ai.intelligence.evaluation.evaluators._common import (
    build_result,
    clamp,
    metric,
)
from src.modules.book_forge.ai.intelligence.evaluation.models import (
    AIModule,
    EvaluationRequest,
    EvaluationResult,
)

_VARIABLE_RE = re.compile(r"{\s*(\w+)\s*}")


class PromptEvaluator:
    """Evaluate prompt completeness, variable usage, and token efficiency."""

    def evaluate(self, request: EvaluationRequest) -> EvaluationResult:
        start = time.perf_counter()
        prompt = str(request.input or "")
        meta = request.metadata or {}

        completeness = clamp(len(prompt.split()) / 20.0)  # ~20 words = complete

        variables = set(_VARIABLE_RE.findall(prompt))
        expected = set(meta.get("expected_variables") or [])
        if expected:
            variable_usage = clamp(len(variables & expected) / len(expected))
        else:
            variable_usage = 1.0 if variables else 0.6

        target = meta.get("target_tokens", 400)
        tokens = TokenEstimator.estimate(prompt)
        token_efficiency = 1.0 if tokens <= target else clamp(target / tokens)

        metrics = [
            metric("prompt_completeness", completeness),
            metric("variable_usage", variable_usage),
            metric("token_efficiency", token_efficiency),
        ]
        recs = []
        if completeness < 0.7:
            recs.append("Add clearer, more complete instructions to the prompt.")
        if variable_usage < 0.7:
            recs.append("Include all expected template variables.")
        if token_efficiency < 0.7:
            recs.append(f"Prompt is long ({tokens} tokens); tighten it.")
        return build_result(AIModule.PROMPT, metrics, start, recommendations=recs)
