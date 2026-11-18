"""EvaluationValidator — guard an evaluation request before it runs.

Checks three things and raises ``EvaluationException`` on the first problem:

* valid request — it's an ``EvaluationRequest`` with a proper ``AIModule``;
* supported evaluator — the module has an evaluator (when a supported set is
  provided);
* required data — the module's needed field (input and/or output) is present.

Stateless and pure.
"""
from typing import Iterable, Optional

from src.modules.book_forge.ai.intelligence.evaluation.exceptions import (
    EvaluationException,
)
from src.modules.book_forge.ai.intelligence.evaluation.models import (
    AIModule,
    EvaluationRequest,
)

# Which field each module needs: "input", "output", or "either".
_REQUIRED_FIELD = {
    AIModule.PROMPT: "input",
    AIModule.CHUNKING: "input",
    AIModule.EMBEDDINGS: "input",
    AIModule.VECTOR_STORE: "input",
    AIModule.RETRIEVAL: "input",
    AIModule.KNOWLEDGE_GRAPH: "input",
    AIModule.PARSER: "input",
    AIModule.LLM: "output",
    AIModule.GUARDRAILS: "either",
}


class EvaluationValidator:
    """Validate an ``EvaluationRequest`` before evaluation."""

    def validate(
        self,
        request: EvaluationRequest,
        *,
        supported_modules: Optional[Iterable[AIModule]] = None,
    ) -> None:
        """Raise ``EvaluationException`` if the request can't be evaluated."""
        self._check_request(request)
        self._check_supported(request, supported_modules)
        self._check_required_data(request)

    # -- checks ------------------------------------------------------------

    def _check_request(self, request: EvaluationRequest) -> None:
        if not isinstance(request, EvaluationRequest):
            raise EvaluationException(
                f"Expected an EvaluationRequest, got {type(request).__name__}."
            )
        if not isinstance(request.module, AIModule):
            raise EvaluationException(
                f"Request has an invalid module: {request.module!r}."
            )

    def _check_supported(
        self,
        request: EvaluationRequest,
        supported_modules: Optional[Iterable[AIModule]],
    ) -> None:
        if supported_modules is None:
            return
        supported = set(supported_modules)
        if request.module not in supported:
            available = ", ".join(sorted(m.value for m in supported))
            raise EvaluationException(
                f"No evaluator registered for module '{request.module.value}'. "
                f"Available: {available}.",
                details={"module": request.module.value},
            )

    def _check_required_data(self, request: EvaluationRequest) -> None:
        required = _REQUIRED_FIELD.get(request.module, "either")
        has_input = request.input is not None
        has_output = request.output is not None

        if required == "input" and not has_input:
            self._missing(request, "input")
        elif required == "output" and not has_output:
            self._missing(request, "output")
        elif required == "either" and not (has_input or has_output):
            self._missing(request, "input or output")

    @staticmethod
    def _missing(request: EvaluationRequest, field: str) -> None:
        raise EvaluationException(
            f"Module '{request.module.value}' requires {field} to evaluate.",
            details={"module": request.module.value, "required": field},
        )
