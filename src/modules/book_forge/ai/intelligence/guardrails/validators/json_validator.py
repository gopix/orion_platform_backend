"""JsonValidator — ensure LLM output is the JSON the agent 
expected.

One of the most useful guardrails. If the agent expects

    {"title": "", "chapters": []}

and the LLM returns ``Hello``, this fails immediately. Checks: valid JSON, an
optional set of required keys, and an optional shape (a template dict whose
top-level keys must be present). Returns one ``ValidationResult`` per rule.
Stateless and pure.
"""
import json
from typing import Any, List, Optional

from src.modules.book_forge.ai.intelligence.guardrails.models import (
    Severity,
    ValidationResult,
)
from src.modules.book_forge.ai.intelligence.guardrails.validators._common import (
    fail,
    ok,
)


class JsonValidator:
    """Validate that output is well-formed JSON with the expected keys."""

    def validate(
        self,
        output: str,
        *,
        required_keys: Optional[List[str]] = None,
        shape: Optional[dict] = None,
    ) -> List[ValidationResult]:
        results: List[ValidationResult] = []

        try:
            data: Any = json.loads(output) if output is not None else None
            if output is None:
                raise ValueError("output is None")
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            # Not JSON at all — fail immediately, nothing else to check.
            results.append(
                fail(
                    "valid_json",
                    f"Output is not valid JSON: {exc}",
                    severity=Severity.HIGH,
                )
            )
            return results

        results.append(ok("valid_json"))

        expected_keys = list(required_keys or []) + list((shape or {}).keys())
        if expected_keys:
            results.append(self._check_keys(data, expected_keys))
        return results

    def _check_keys(self, data: Any, expected_keys: List[str]) -> ValidationResult:
        if not isinstance(data, dict):
            return fail(
                "required_keys",
                "Expected a JSON object but got "
                f"{type(data).__name__}.",
                severity=Severity.HIGH,
            )
        missing = [key for key in expected_keys if key not in data]
        if missing:
            return fail(
                "required_keys",
                f"JSON is missing required keys: {missing}.",
                severity=Severity.HIGH,
                details={"missing": missing},
            )
        return ok("required_keys")
