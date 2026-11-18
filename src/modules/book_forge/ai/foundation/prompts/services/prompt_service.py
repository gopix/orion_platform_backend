"""PromptService — the facade / orchestrator of the Prompt Engine.

It coordinates its collaborators (repository, validator, renderer, llm_service)
through the full prompt lifecycle. It does not render, validate, query the DB,
or call any model SDK itself — it only calls the abstractions.

All collaborators are injected via the constructor (no object creation inside),
which keeps the service testable.
"""
from typing import Any, Dict, List, Optional

from src.core.logger import get_logger
from src.modules.book_forge.ai.foundation.llm.models import LLMMessage, LLMRequest, LLMResponse, LLMRole
from src.modules.book_forge.ai.foundation.llm.providers import LLMProvider
from src.modules.book_forge.ai.foundation.llm.services import LLMService
from src.modules.book_forge.ai.foundation.llm.utils import count_tokens, provider_for_model
from src.modules.book_forge.ai.foundation.prompts.models import (
    ExecutionStatus,
    PromptExecution,
    PromptTemplate,
    PromptVersion,
    RenderedPrompt,
)
from src.modules.book_forge.ai.foundation.prompts.renderers import PromptRenderer
from src.modules.book_forge.ai.foundation.prompts.repositories import PromptRepository
from src.modules.book_forge.ai.foundation.prompts.services.prompt_exceptions import (
    PromptExecutionException,
    PromptNotFoundException,
    PromptValidationException,
)
from src.modules.book_forge.ai.foundation.prompts.validators import PromptValidator

logger = get_logger(__name__)

_DEFAULT_MAX_TOKENS = 1024


class PromptService:
    def __init__(
        self,
        repository: PromptRepository,
        validator: PromptValidator,
        renderer: PromptRenderer,
        llm_service: LLMService,
    ):
        self._repository = repository
        self._validator = validator
        self._renderer = renderer
        self._llm_service = llm_service

    # ================================================================== #
    # Template management                                                #
    # ================================================================== #
    def create_template(self, template: PromptTemplate) -> PromptTemplate:
        return self._repository.create_template(template)

    def update_template(self, template: PromptTemplate) -> PromptTemplate:
        updated = self._repository.update_template(template)
        if updated is None:
            raise PromptNotFoundException(
                f"Prompt template {template.id} not found"
            )
        return updated

    def get_template(self, template_id: int) -> PromptTemplate:
        template = self._repository.get_template(template_id)
        if template is None:
            raise PromptNotFoundException(f"Prompt template {template_id} not found")
        return template

    # ================================================================== #
    # Version management                                                 #
    # ================================================================== #
    def create_version(self, version: PromptVersion) -> PromptVersion:
        return self._repository.create_version(version)

    def activate_version(self, template_id: int, version: int) -> PromptVersion:
        activated = self._repository.activate_version(template_id, version)
        if activated is None:
            raise PromptNotFoundException(
                f"Version {version} of template {template_id} not found"
            )
        return activated

    def get_active_version(self, template_id: int) -> PromptVersion:
        version = self._repository.get_active_version(template_id)
        if version is None:
            raise PromptNotFoundException(
                f"No active version for template {template_id}"
            )
        return version

    # ================================================================== #
    # Rendering (no tokens spent, not persisted)                         #
    # ================================================================== #
    def render_prompt(
        self, template_name: str, variables: Optional[Dict[str, Any]] = None
    ) -> RenderedPrompt:
        _, _, rendered = self._prepare(template_name, variables or {})
        return rendered

    # ================================================================== #
    # Execution                                                          #
    # ================================================================== #
    def execute_prompt(
        self,
        template_name: str,
        variables: Optional[Dict[str, Any]] = None,
        *,
        provider: Optional[LLMProvider] = None,
        project_id: Optional[int] = None,
        document_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> LLMResponse:
        """Full pipeline: load -> validate -> render -> LLM -> save history."""
        return self._run(
            template_name,
            variables or {},
            persist=True,
            provider=provider,
            project_id=project_id,
            document_id=document_id,
            user_id=user_id,
        )

    def test_prompt(
        self,
        template_name: str,
        variables: Optional[Dict[str, Any]] = None,
        *,
        provider: Optional[LLMProvider] = None,
    ) -> LLMResponse:
        """Same as execute_prompt but does NOT persist execution history."""
        return self._run(
            template_name, variables or {}, persist=False, provider=provider
        )

    # ================================================================== #
    # History                                                            #
    # ================================================================== #
    def get_execution_history(
        self, template_id: int, skip: int = 0, limit: int = 100
    ) -> List[PromptExecution]:
        return self._repository.get_execution_history(
            template_id, skip=skip, limit=limit
        )

    # ================================================================== #
    # Internals                                                          #
    # ================================================================== #
    def _prepare(self, template_name: str, variables: Dict[str, Any]):
        """Load -> validate -> render. Shared by rendering and execution."""
        template = self._repository.get_template_by_name(template_name)
        if template is None:
            raise PromptNotFoundException(
                f"Prompt template '{template_name}' not found"
            )

        version = self._repository.get_active_version(template.id)
        if version is None:
            raise PromptNotFoundException(
                f"No active version for template '{template_name}'"
            )

        declared = self._repository.get_variables(template.id)

        result = self._validator.validate(template, version, variables, declared)
        if not result.is_valid:
            raise PromptValidationException(result)

        rendered = self._renderer.render(version, variables)
        rendered.token_estimate = count_tokens(rendered.rendered_text, version.model)
        return template, version, rendered

    def _run(
        self,
        template_name: str,
        variables: Dict[str, Any],
        *,
        persist: bool,
        provider: Optional[LLMProvider] = None,
        project_id: Optional[int] = None,
        document_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> LLMResponse:
        template, version, rendered = self._prepare(template_name, variables)

        # Route to the provider that owns the model unless overridden.
        selected_provider = provider or provider_for_model(version.model)

        request = LLMRequest(
            model=version.model,
            messages=[LLMMessage(role=LLMRole.USER, content=rendered.rendered_text)],
            max_tokens=version.max_tokens or _DEFAULT_MAX_TOKENS,
            temperature=version.temperature,
            project_id=project_id,
            document_id=document_id,
            user_id=user_id,
        )

        execution = PromptExecution(
            request_id=request.request_id,
            prompt_id=template.id,
            version=version.version,
            provider=selected_provider.value,
            model=version.model,
            rendered_prompt=rendered.rendered_text,
            status=ExecutionStatus.PENDING,
        )

        try:
            response = self._llm_service.generate(request, provider=selected_provider)
        except Exception as exc:
            execution.status = ExecutionStatus.FAILED
            if persist:
                self._safe_save(execution)
            logger.error(
                "Prompt execution failed for '%s': %s", template_name, exc,
                exc_info=True,
            )
            raise PromptExecutionException(
                f"Execution of prompt '{template_name}' failed: {exc}"
            ) from exc

        # Enrich the execution record from the (usage-enriched) response.
        execution.response = response.content
        execution.usage = response.usage
        execution.latency_ms = response.usage.latency_ms
        execution.cost = response.usage.estimated_cost
        execution.status = ExecutionStatus.SUCCESS

        if persist:
            self._safe_save(execution)

        return response

    def _safe_save(self, execution: PromptExecution) -> None:
        """Persist execution history without letting a save error mask the run."""
        try:
            self._repository.save_execution(execution)
        except Exception as exc:  # noqa: BLE001 - history is best-effort
            logger.error(
                "Failed to save execution history (request_id=%s): %s",
                execution.request_id,
                exc,
                exc_info=True,
            )
