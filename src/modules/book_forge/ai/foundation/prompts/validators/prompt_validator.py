"""PromptValidator — the orchestrator.

It performs no validation itself; it coordinates the request, template, and
variable validators and merges their results into a single ``ValidationResult``.
The service only needs to call ``validate(...)``.
"""
from typing import Any, Dict, List, Optional

from src.modules.book_forge.ai.foundation.prompts.models import (
    PromptTemplate,
    PromptVariable,
    PromptVersion,
)
from src.modules.book_forge.ai.foundation.prompts.validators.prompt_request_validator import (
    PromptRequestValidator,
)
from src.modules.book_forge.ai.foundation.prompts.validators.prompt_template_validator import (
    PromptTemplateValidator,
)
from src.modules.book_forge.ai.foundation.prompts.validators.prompt_variable_validator import (
    PromptVariableValidator,
)
from src.modules.book_forge.ai.foundation.prompts.validators.validation_result import (
    ValidationResult,
)


class PromptValidator:
    def __init__(
        self,
        request_validator: Optional[PromptRequestValidator] = None,
        template_validator: Optional[PromptTemplateValidator] = None,
        variable_validator: Optional[PromptVariableValidator] = None,
    ) -> None:
        self._request_validator = request_validator or PromptRequestValidator()
        self._template_validator = template_validator or PromptTemplateValidator()
        self._variable_validator = variable_validator or PromptVariableValidator()

    def validate(
        self,
        template: Optional[PromptTemplate],
        version: Optional[PromptVersion],
        variables: Optional[Dict[str, Any]] = None,
        declared_variables: Optional[List[PromptVariable]] = None,
    ) -> ValidationResult:
        result = ValidationResult()

        # Request/business checks first (existence, status, model config).
        result.merge(self._request_validator.validate(template, version))

        # Without a version there is no template text or variables to check.
        if version is None:
            return result

        result.merge(self._template_validator.validate(version.template_text))
        result.merge(
            self._variable_validator.validate(
                version.template_text, variables, declared_variables
            )
        )
        return result
