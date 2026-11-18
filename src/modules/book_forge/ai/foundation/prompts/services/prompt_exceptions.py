"""Exceptions raised by the Prompt Engine service layer.

The service decides how to react to failures from its collaborators:
* a missing template/version -> PromptNotFoundException
* invalid input (validation failed) -> PromptValidationException (carries the result)
* a failure during model invocation -> PromptExecutionException
"""
from typing import Optional

from src.modules.book_forge.ai.foundation.prompts.validators import ValidationResult


class PromptEngineError(Exception):
    """Base class for all Prompt Engine service errors."""


class PromptNotFoundException(PromptEngineError):
    """A requested template or active version does not exist."""


class PromptValidationException(PromptEngineError):
    """Input failed validation. Carries the structured ``ValidationResult``."""

    def __init__(self, result: ValidationResult, message: Optional[str] = None):
        self.result = result
        super().__init__(message or "; ".join(result.errors) or "Validation failed")


class PromptExecutionException(PromptEngineError):
    """The prompt could not be executed (e.g. the LLM call failed)."""
