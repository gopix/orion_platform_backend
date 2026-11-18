"""Prompt Engine service layer (the facade)."""
from sqlalchemy.orm import Session

from src.modules.book_forge.ai.foundation.llm.services import llm_service
from src.modules.book_forge.ai.foundation.prompts.renderers import PromptRenderer
from src.modules.book_forge.ai.foundation.prompts.repositories import PromptRepository
from src.modules.book_forge.ai.foundation.prompts.services.prompt_exceptions import (
    PromptEngineError,
    PromptExecutionException,
    PromptNotFoundException,
    PromptValidationException,
)
from src.modules.book_forge.ai.foundation.prompts.services.prompt_service import PromptService
from src.modules.book_forge.ai.foundation.prompts.validators import PromptValidator

__all__ = [
    "PromptService",
    "build_prompt_service",
    "PromptEngineError",
    "PromptNotFoundException",
    "PromptValidationException",
    "PromptExecutionException",
]


def build_prompt_service(db: Session) -> PromptService:
    """Composition root: wire a PromptService with its collaborators for a request.

    Kept outside the service so the service itself never constructs its own
    dependencies.
    """
    return PromptService(
        repository=PromptRepository(db),
        validator=PromptValidator(),
        renderer=PromptRenderer(),
        llm_service=llm_service,
    )
