"""PromptVariableValidator — validates the variables supplied at runtime.

Checks: variables referenced by the template but not provided (missing), declared
required variables that are absent, null values, empty strings (per policy), and
provided-but-unused variables (warning). It reports only; it never fills in
defaults or mutates the inputs.
"""
from typing import Any, Dict, List, Optional

from jinja2 import Environment, meta
from jinja2 import TemplateSyntaxError as JinjaTemplateSyntaxError

from src.modules.book_forge.ai.foundation.prompts.models import PromptVariable
from src.modules.book_forge.ai.foundation.prompts.validators.validation_result import (
    ValidationResult,
)


class PromptVariableValidator:
    def __init__(self, allow_empty_strings: bool = True) -> None:
        self._env = Environment()
        self._allow_empty_strings = allow_empty_strings

    def validate(
        self,
        template_text: str,
        variables: Optional[Dict[str, Any]] = None,
        declared: Optional[List[PromptVariable]] = None,
    ) -> ValidationResult:
        result = ValidationResult()
        variables = variables or {}
        declared = declared or []

        # Which variables does the template reference?
        try:
            referenced = meta.find_undeclared_variables(
                self._env.parse(template_text or "")
            )
        except JinjaTemplateSyntaxError:
            # Syntax is the template validator's concern; skip variable analysis.
            return result

        # Referenced by the template but not provided.
        for name in sorted(referenced):
            if name not in variables:
                result.add_error(f"Missing variable: {name}")

        # Declared-variable checks (required / null / empty-string policy).
        declared_names = set()
        for variable in declared:
            declared_names.add(variable.name)
            present = variable.name in variables
            value = variables.get(variable.name)

            if not present or value is None:
                if variable.required:
                    result.add_error(
                        f"Missing required variable: {variable.name}"
                    )
                elif present and value is None:
                    result.add_error(f"Variable '{variable.name}' is null")
                continue

            if isinstance(value, str) and value == "":
                if variable.required and not self._allow_empty_strings:
                    result.add_error(f"Variable '{variable.name}' is empty")
                else:
                    result.add_warning(
                        f"Variable '{variable.name}' is an empty string"
                    )

        # Null values on provided-but-undeclared variables.
        for name, value in variables.items():
            if value is None and name not in declared_names:
                result.add_error(f"Variable '{name}' is null")

        # Provided but neither referenced nor declared -> unused (warning).
        allowed = referenced | declared_names
        for name in variables:
            if name not in allowed:
                result.add_warning(f'Variable "{name}" is unused')

        return result
