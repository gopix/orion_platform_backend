"""PromptRepository — the data-access layer for the Prompt Engine.

Stores and retrieves prompt-related data. Nothing else: it does not render
templates, validate variables, execute prompts, call the LLM, or contain
business rules. It depends only on the domain models, the database session, and
SQLAlchemy — and it returns domain models, never ORM rows.
"""
from typing import List, Optional

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.core.logger import get_logger
from src.modules.book_forge.ai.foundation.llm.models import LLMUsage
from src.modules.book_forge.ai.foundation.prompts.models import (
    PromptExecution,
    PromptTemplate,
    PromptVariable,
    PromptVersion,
)
from src.modules.book_forge.models.bookforge_prompt_models import (
    PromptExecutionORM,
    PromptTemplateORM,
    PromptVariableORM,
    PromptVersionORM,
)

logger = get_logger(__name__)


class PromptRepository:
    """Persistence for prompt templates, versions, variables, and executions."""

    def __init__(self, db: Session):
        self._db = db

    # ------------------------------------------------------------------ #
    # Templates                                                          #
    # ------------------------------------------------------------------ #
    def create_template(self, template: PromptTemplate) -> PromptTemplate:
        orm = PromptTemplateORM(
            name=template.name,
            description=template.description,
            active_version=template.active_version,
            status=template.status.value,
            created_by=template.created_by,
        )
        return self._commit(orm, self._to_template)

    def update_template(self, template: PromptTemplate) -> Optional[PromptTemplate]:
        orm = self._db.get(PromptTemplateORM, template.id)
        if orm is None:
            return None
        orm.name = template.name
        orm.description = template.description
        orm.active_version = template.active_version
        orm.status = template.status.value
        return self._commit(orm, self._to_template)

    def get_template(self, template_id: int) -> Optional[PromptTemplate]:
        orm = self._db.get(PromptTemplateORM, template_id)
        return self._to_template(orm) if orm else None

    def get_template_by_name(self, name: str) -> Optional[PromptTemplate]:
        orm = (
            self._db.query(PromptTemplateORM)
            .filter(PromptTemplateORM.name == name)
            .first()
        )
        return self._to_template(orm) if orm else None

    def list_templates(
        self, name_prefix: Optional[str] = None
    ) -> List[PromptTemplate]:
        """List templates, optionally filtered by a name prefix."""
        query = self._db.query(PromptTemplateORM)
        if name_prefix:
            query = query.filter(PromptTemplateORM.name.like(f"{name_prefix}%"))
        rows = query.order_by(PromptTemplateORM.name.asc()).all()
        return [self._to_template(row) for row in rows]

    # ------------------------------------------------------------------ #
    # Versions                                                           #
    # ------------------------------------------------------------------ #
    def create_version(self, version: PromptVersion) -> PromptVersion:
        orm = PromptVersionORM(
            template_id=version.template_id,
            version=version.version,
            template_text=version.template_text,
            model=version.model,
            temperature=version.temperature,
            max_tokens=version.max_tokens,
            status=version.status.value,
            created_by=version.created_by,
        )
        return self._commit(orm, self._to_version)

    def get_active_version(self, template_id: int) -> Optional[PromptVersion]:
        orm = (
            self._db.query(PromptVersionORM)
            .filter(
                PromptVersionORM.template_id == template_id,
                PromptVersionORM.status == "active",
            )
            .order_by(PromptVersionORM.version.desc())
            .first()
        )
        return self._to_version(orm) if orm else None

    def activate_version(
        self, template_id: int, version: int
    ) -> Optional[PromptVersion]:
        target = (
            self._db.query(PromptVersionORM)
            .filter(
                PromptVersionORM.template_id == template_id,
                PromptVersionORM.version == version,
            )
            .first()
        )
        if target is None:
            return None
        try:
            # Archive any currently-active versions of this template.
            self._db.query(PromptVersionORM).filter(
                PromptVersionORM.template_id == template_id,
                PromptVersionORM.status == "active",
            ).update({PromptVersionORM.status: "archived"})

            target.status = "active"

            # Point the template's active_version at this version number.
            template = self._db.get(PromptTemplateORM, template_id)
            if template is not None:
                template.active_version = version

            self._db.commit()
            self._db.refresh(target)
            return self._to_version(target)
        except SQLAlchemyError as exc:
            self._db.rollback()
            logger.error(
                "Error activating version %s for template %s: %s",
                version,
                template_id,
                exc,
                exc_info=True,
            )
            raise

    def get_versions(self, template_id: int) -> List[PromptVersion]:
        rows = (
            self._db.query(PromptVersionORM)
            .filter(PromptVersionORM.template_id == template_id)
            .order_by(PromptVersionORM.version.desc())
            .all()
        )
        return [self._to_version(row) for row in rows]

    # ------------------------------------------------------------------ #
    # Variables                                                          #
    # ------------------------------------------------------------------ #
    def create_variables(
        self, template_id: int, variables: List[PromptVariable]
    ) -> List[PromptVariable]:
        orms = [
            PromptVariableORM(
                template_id=template_id,
                name=variable.name,
                type=variable.type.value,
                required=variable.required,
                default_value=(
                    None
                    if variable.default_value is None
                    else str(variable.default_value)
                ),
                description=variable.description,
            )
            for variable in variables
        ]
        try:
            self._db.add_all(orms)
            self._db.commit()
            for orm in orms:
                self._db.refresh(orm)
            return [self._to_variable(orm) for orm in orms]
        except SQLAlchemyError as exc:
            self._db.rollback()
            logger.error(
                "Error creating variables for template %s: %s",
                template_id,
                exc,
                exc_info=True,
            )
            raise

    def get_variables(self, template_id: int) -> List[PromptVariable]:
        rows = (
            self._db.query(PromptVariableORM)
            .filter(PromptVariableORM.template_id == template_id)
            .all()
        )
        return [self._to_variable(row) for row in rows]

    # ------------------------------------------------------------------ #
    # Executions                                                         #
    # ------------------------------------------------------------------ #
    def save_execution(self, execution: PromptExecution) -> PromptExecution:
        usage = execution.usage
        orm = PromptExecutionORM(
            request_id=execution.request_id,
            prompt_id=execution.prompt_id,
            version=execution.version,
            provider=execution.provider,
            model=execution.model,
            rendered_prompt=execution.rendered_prompt,
            response=execution.response,
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
            latency_ms=execution.latency_ms
            or (usage.latency_ms if usage else None),
            cost=execution.cost or (usage.estimated_cost if usage else None),
            status=execution.status.value,
        )
        return self._commit(orm, self._to_execution)

    def get_execution_history(
        self, prompt_id: int, skip: int = 0, limit: int = 100
    ) -> List[PromptExecution]:
        rows = (
            self._db.query(PromptExecutionORM)
            .filter(PromptExecutionORM.prompt_id == prompt_id)
            .order_by(PromptExecutionORM.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
        return [self._to_execution(row) for row in rows]

    # ------------------------------------------------------------------ #
    # Internals: commit + ORM -> domain mapping                          #
    # ------------------------------------------------------------------ #
    def _commit(self, orm, mapper):
        """Add, commit, refresh a single ORM row and map it to a domain model."""
        try:
            self._db.add(orm)
            self._db.commit()
            self._db.refresh(orm)
            return mapper(orm)
        except SQLAlchemyError as exc:
            self._db.rollback()
            logger.error("Repository write failed: %s", exc, exc_info=True)
            raise

    @staticmethod
    def _to_template(orm: PromptTemplateORM) -> PromptTemplate:
        return PromptTemplate.model_validate(orm)

    @staticmethod
    def _to_version(orm: PromptVersionORM) -> PromptVersion:
        return PromptVersion.model_validate(orm)

    @staticmethod
    def _to_variable(orm: PromptVariableORM) -> PromptVariable:
        return PromptVariable.model_validate(orm)

    @staticmethod
    def _to_execution(orm: PromptExecutionORM) -> PromptExecution:
        usage = None
        if orm.input_tokens is not None or orm.output_tokens is not None:
            usage = LLMUsage(
                input_tokens=orm.input_tokens or 0,
                output_tokens=orm.output_tokens or 0,
                provider=orm.provider,
                model=orm.model,
                latency_ms=orm.latency_ms,
                estimated_cost=orm.cost,
            )
        return PromptExecution(
            request_id=orm.request_id,
            prompt_id=orm.prompt_id,
            version=orm.version,
            provider=orm.provider,
            model=orm.model,
            rendered_prompt=orm.rendered_prompt,
            response=orm.response,
            usage=usage,
            latency_ms=orm.latency_ms,
            cost=orm.cost,
            status=orm.status,
        )
