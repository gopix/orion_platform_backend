"""Guardrail orchestration service.

One orchestrator running the full guardrail pipeline around a generation:

    GuardrailRequest -> input validation -> policy checks -> prompt sanitization
    -> LLM -> output validation -> output repair -> GuardrailResponse

The LLM is injected as a plain callable, so guardrails stay decoupled from the
LLM module. Every stage's collaborators (validators, policies, processors) are
injectable, so the service owns orchestration only — never *how* any single check
or repair works. When no ``llm`` is supplied, the service simply guards whatever
prompt/output are already on the request (input and/or output phases run as
applicable).
"""
import json
import time
from typing import Callable, List, Optional

from src.core.logger import get_logger
from src.modules.book_forge.ai.intelligence.guardrails.exceptions import (
    PolicyViolationException,
    ValidationException,
)
from src.modules.book_forge.ai.intelligence.guardrails.models import (
    GuardrailRequest,
    GuardrailResponse,
    RiskDecision,
    ValidationResult,
    ValidationStatus,
)
from src.modules.book_forge.ai.intelligence.guardrails.policies import (
    BasePolicy,
    PIIPolicy,
    PromptInjectionPolicy,
)
from src.modules.book_forge.ai.intelligence.guardrails.processors import (
    JsonRepair,
    OutputCleaner,
    PromptSanitizer,
)
from src.modules.book_forge.ai.intelligence.guardrails.utils import RiskCalculator
from src.modules.book_forge.ai.intelligence.guardrails.validators import (
    InputValidator,
    JsonValidator,
    OutputValidator,
)

logger = get_logger(__name__)

# An LLM is any callable that turns a (sanitised) prompt into output text.
LLMCallable = Callable[[str], str]


class GuardrailService:
    """Run the guardrail pipeline over a request and return a response."""

    def __init__(
        self,
        *,
        input_validator: Optional[InputValidator] = None,
        output_validator: Optional[OutputValidator] = None,
        json_validator: Optional[JsonValidator] = None,
        policies: Optional[List[BasePolicy]] = None,
        sanitizer: Optional[PromptSanitizer] = None,
        output_cleaner: Optional[OutputCleaner] = None,
        json_repair: Optional[JsonRepair] = None,
        risk_calculator: Optional[RiskCalculator] = None,
    ) -> None:
        self._input_validator = input_validator or InputValidator()
        self._output_validator = output_validator or OutputValidator()
        self._json_validator = json_validator or JsonValidator()
        self._policies = (
            policies if policies is not None else [PIIPolicy(), PromptInjectionPolicy()]
        )
        self._sanitizer = sanitizer or PromptSanitizer()
        self._cleaner = output_cleaner or OutputCleaner()
        self._json_repair = json_repair or JsonRepair()
        self._risk_calculator = risk_calculator or RiskCalculator()

    def run(
        self,
        request: GuardrailRequest,
        *,
        llm: Optional[LLMCallable] = None,
        files: Optional[List[str]] = None,
        required_sections: Optional[List[str]] = None,
        json_shape: Optional[dict] = None,
        repair: bool = True,
        raise_on_violation: bool = False,
    ) -> GuardrailResponse:
        """Run the guardrail pipeline; returns an aggregated ``GuardrailResponse``.

        If ``llm`` is given, the (sanitised) prompt is sent to it and the output is
        validated/repaired. Otherwise the request's existing prompt/output are
        guarded.
        """
        self._validate_request(request, llm)
        start = time.perf_counter()

        all_results: List[ValidationResult] = []
        response = GuardrailResponse()

        # 1) Input validation.
        if request.prompt is not None:
            all_results.extend(
                self._input_validator.validate(request.prompt, files=files)
            )

        # 2) Policy checks (prompt-side).
        policy_results = [p.evaluate(request) for p in self._policies]
        for policy in policy_results:
            all_results.extend(policy.results)

        # 3) Prompt sanitization.
        effective_prompt = request.prompt or ""
        if repair and request.prompt:
            sanitized = self._sanitizer.sanitize(request.prompt)
            if sanitized != request.prompt:
                response.modified_prompt = sanitized
            effective_prompt = sanitized

        # 4) LLM (optional). Generate output from the sanitised prompt.
        output = request.output
        if llm is not None:
            output = llm(effective_prompt)

        # 5) Output validation (+ JSON shape when expected).
        if output is not None:
            all_results.extend(
                self._output_validator.validate(
                    output, required_sections=required_sections
                )
            )
            if json_shape is not None:
                all_results.extend(
                    self._json_validator.validate(output, shape=json_shape)
                )

        # 6) Output repair.
        if repair and output is not None:
            repaired = self._repair_output(output, json_shape)
            if repaired is not None and repaired != output:
                response.modified_output = repaired

        # 7) Centralised risk decision — validators/policies never see this.
        violations, warnings = self._split(all_results)
        risk = self._risk_calculator.calculate(all_results)

        response.violations = violations
        response.warnings = warnings
        response.policy_results = policy_results
        response.risk = risk
        response.allowed = risk.decision != RiskDecision.BLOCK

        duration_ms = (time.perf_counter() - start) * 1000
        self._log(request, response, duration_ms, generated=llm is not None)

        if raise_on_violation and not response.allowed:
            raise PolicyViolationException(
                "Request blocked by guardrails.",
                violations=violations,
                details={
                    "rules": sorted({v.rule for v in violations}),
                    "risk": risk.overall_risk,
                    "level": risk.level.value,
                },
            )
        return response

    def repair_json(self, text: str, default=None):
        """Convenience: recover JSON from messy text via the JSON processor."""
        return self._json_repair.repair_or_default(text, default=default)

    # -- internals ---------------------------------------------------------

    def _validate_request(
        self, request: GuardrailRequest, llm: Optional[LLMCallable]
    ) -> None:
        if not isinstance(request, GuardrailRequest):
            raise ValidationException(
                f"Expected a GuardrailRequest, got {type(request).__name__}.",
                field="request",
            )
        if llm is not None and not request.prompt:
            raise ValidationException(
                "A prompt is required to generate with an LLM.", field="prompt"
            )
        if llm is None and not (request.prompt or request.output):
            raise ValidationException(
                "Request has neither a prompt nor an output to check.", field="prompt"
            )

    def _repair_output(self, output: str, json_shape: Optional[dict]) -> Optional[str]:
        """Repair output — JSON-repair when a shape is expected, else clean text."""
        if json_shape is not None:
            parsed = self._json_repair.try_repair(output)
            if parsed is not None:
                return json.dumps(parsed)
        cleaned = self._cleaner.clean(output)
        return cleaned

    @staticmethod
    def _split(results: List[ValidationResult]):
        """Partition results into (violations, warnings)."""
        violations = [r for r in results if r.status == ValidationStatus.FAIL]
        warnings = [r for r in results if r.status == ValidationStatus.WARNING]
        return violations, warnings

    def _log(
        self,
        request: GuardrailRequest,
        response: GuardrailResponse,
        duration_ms: float,
        generated: bool,
    ) -> None:
        risk = response.risk
        logger.info(
            "Guardrail run | request_id=%s | generated=%s allowed=%s decision=%s "
            "risk=%s | violations=%s warnings=%s modified=%s | duration_ms=%.1f",
            request.request_id,
            generated,
            response.allowed,
            risk.decision.value if risk else "n/a",
            risk.overall_risk if risk else "n/a",
            len(response.violations),
            len(response.warnings),
            response.was_modified,
            duration_ms,
        )


# Shared singleton — import this from other modules.
guardrail_service = GuardrailService()
