"""PromptRequestValidator — business validation of an execution request.

Validates that the prompt is runnable before anything happens: the template and
an active version exist, the version is ACTIVE, a model is configured, and the
temperature / max_tokens are within allowed ranges.
"""
from typing import Optional

from src.modules.book_forge.ai.foundation.prompts.models import (
    PromptTemplate,
    PromptVersion,
    VersionStatus,
)
from src.modules.book_forge.ai.foundation.prompts.validators.validation_result import (
    ValidationResult,
)

_MIN_TEMPERATURE = 0.0
_MAX_TEMPERATURE = 2.0


class PromptRequestValidator:
    def validate(
        self,
        template: Optional[PromptTemplate],
        version: Optional[PromptVersion],
    ) -> ValidationResult:
        result = ValidationResult()

        if template is None:
            result.add_error("Prompt template not found")

        if version is None:
            result.add_error("No active prompt version found")
            return result  # nothing more we can check without a version

        if version.status != VersionStatus.ACTIVE:
            result.add_error(
                f"Prompt version {version.version} is not active "
                f"(status={version.status.value})"
            )

        if not version.model:
            result.add_error("No model configured for the prompt version")

        if version.temperature is not None and not (
            _MIN_TEMPERATURE <= version.temperature <= _MAX_TEMPERATURE
        ):
            result.add_error(
                f"Temperature {version.temperature} is out of range "
                f"({_MIN_TEMPERATURE}-{_MAX_TEMPERATURE})"
            )

        if version.max_tokens is not None and version.max_tokens <= 0:
            result.add_error(
                f"max_tokens must be positive (got {version.max_tokens})"
            )

        return result
