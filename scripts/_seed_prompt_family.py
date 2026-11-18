"""Shared seeding logic for guidance-managed prompt families.

The scaffold, default guidance, variables and model settings all live in
``services/prompt_families`` — the same definitions the guidance API composes
from. This module only handles the upsert-by-content bookkeeping, so a seed
script is a two-line wrapper.

Upsert-by-content: if the active version already matches the composed text this
does nothing; otherwise it creates the NEXT version and activates it (the Prompt
Engine archives the previous one, so you keep history + rollback).
"""
from src.core.database import SessionLocal
from src.modules.book_forge.ai.foundation.prompts.models import (
    PromptTemplate,
    PromptVariable,
    PromptVersion,
    VersionStatus,
)
from src.modules.book_forge.ai.foundation.prompts.repositories import PromptRepository
from src.modules.book_forge.services.prompt_families import get_family


def seed(template_name: str) -> None:
    """Create or update the base template for one prompt family."""
    family = get_family(template_name)
    db = SessionLocal()
    try:
        repo = PromptRepository(db)
        template_text = family.compose(family.default_guidance)

        template = repo.get_template_by_name(family.template)
        if template is None:
            template = repo.create_template(
                PromptTemplate(name=family.template, description=family.description)
            )
            print(f"- Created template '{family.template}'.")

        existing = {v.name for v in repo.get_variables(template.id)}
        missing = [
            PromptVariable(name=n, type=t, required=r)
            for n, t, r in family.variables
            if n not in existing
        ]
        if missing:
            repo.create_variables(template.id, missing)
            print(f"- Declared variables: {', '.join(v.name for v in missing)}.")

        active = repo.get_active_version(template.id)
        if active and (active.template_text or "").strip() == template_text.strip():
            print(f"Active '{family.template}' prompt already up to date.")
            return

        versions = repo.get_versions(template.id)
        next_version = max((v.version for v in versions), default=0) + 1
        repo.create_version(
            PromptVersion(
                template_id=template.id,
                version=next_version,
                template_text=template_text,
                model=family.model,
                temperature=family.temperature,
                max_tokens=family.max_tokens,
                status=VersionStatus.DRAFT,
            )
        )
        repo.activate_version(template.id, next_version)
        print(f"OK - seeded and activated {family.template} v{next_version}.")
    finally:
        db.close()
