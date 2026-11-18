"""Friendly, end-user prompt management for the blueprint pipeline.

A publisher never sees Jinja, JSON, model settings, or version numbers. They edit
one plain-English *guidance* box per book type. This service wraps that guidance
in the family's fixed scaffold, versions it, and activates it.

    guidance (plain English)  ->  family.compose()  ->  full template
                                                          -> new version -> active

**Which prompt gets edited.** The pipeline calls two prompts, so this service is
parameterised by *family* (see ``prompt_families``):

    chapter_content     (default) — how each chapter's prose is written
    syllabus_structure            — what counts as a chapter for this book type

Both are live: whatever you edit here is what the generation path reads. This used
to be hardcoded to ``blueprint_generation`` — the single prompt that once chose
chapters, weighted them and wrote prose all at once. When that job was split, the
old template stopped being called, so editing guidance here saved correctly and
changed nothing. Family-aware addressing is the fix for that silent no-op.

Book types map to templates by category:
    "default"/""      -> chapter_content            (the generic prompt)
    "history"         -> chapter_content_history
    "<category>"      -> chapter_content_<slug>

The generation pipeline resolves these per project category
(``resolve_template_name``), so activating a book-type prompt here changes how that
category's books are generated.
"""
from typing import Any, Dict, List, Optional

from jinja2 import Environment, StrictUndefined
from sqlalchemy.orm import Session

from src.modules.book_forge.ai.foundation.prompts.models import (
    PromptStatus,
    PromptTemplate,
    PromptVariable,
    PromptVersion,
    VersionStatus,
)
from src.modules.book_forge.ai.foundation.prompts.repositories import PromptRepository
from src.modules.book_forge.services import category_service
from src.modules.book_forge.services.prompt_families import (
    DEFAULT_FAMILY,
    PromptFamily,
    family_names,
    get_family,
)

_DEFAULT_MODEL = "gpt-4o-mini"

# Re-exported so callers (and the router's error message) can discover the
# addressable families.
FAMILY_NAMES = family_names
DEFAULT_TEMPLATE = DEFAULT_FAMILY


# ------------------------------------------------------------------ #
# Naming                                                             #
# ------------------------------------------------------------------ #
def _template_name(family: PromptFamily, category: Optional[str]) -> str:
    slug = (category or "").strip().lower().replace(" ", "_").replace("-", "_")
    if not slug or slug in ("default", "generic", "base"):
        return family.template
    return f"{family.template}_{slug}"


def _category_label(family: PromptFamily, template_name: str) -> str:
    if template_name == family.template:
        return "default"
    return template_name[len(family.template) + 1 :]


# ------------------------------------------------------------------ #
# Operations                                                         #
# ------------------------------------------------------------------ #
def list_book_types(
    db: Session, template: Optional[str] = None
) -> List[Dict[str, Any]]:
    """List every book-type prompt in a family, with a friendly summary."""
    family = get_family(template)
    repo = PromptRepository(db)
    out: List[Dict[str, Any]] = []
    for tpl in repo.list_templates(name_prefix=family.template):
        active = repo.get_active_version(tpl.id) if tpl.id else None
        label = _category_label(family, tpl.name)
        category = (
            category_service.get_category(db, label) if label != "default" else None
        )
        out.append(
            {
                "template": family.template,
                "category_id": category.id if category else None,
                "category_name": label,
                "active_version": active.version if active else None,
                "updated_at": tpl.updated_at,
                "has_guidance": bool(active and family.extract(active.template_text)),
            }
        )
    return out


def get_guidance(
    db: Session, category: Optional[str], template: Optional[str] = None
) -> Dict[str, Any]:
    """Return the current plain-English guidance for a book type."""
    family = get_family(template)
    repo = PromptRepository(db)
    name = _template_name(family, category)
    tpl = repo.get_template_by_name(name)
    active = repo.get_active_version(tpl.id) if tpl else None
    guidance = family.extract(active.template_text) if active else ""
    return {
        "template": family.template,
        "category": _category_label(family, name),
        "guidance": guidance or family.default_guidance.strip(),
        "active_version": active.version if active else None,
        "exists": tpl is not None,
    }


def set_guidance(
    db: Session,
    category: Optional[str],
    guidance: str,
    *,
    created_by: Optional[int] = None,
    model: Optional[str] = None,
    template: Optional[str] = None,
) -> Dict[str, Any]:
    """Save new guidance: compose -> new version -> activate.

    Creates the book-type template on first use.
    """
    family = get_family(template)
    repo = PromptRepository(db)
    name = _template_name(family, category)
    template_text = family.compose(guidance)

    # Registering a prompt for a category also registers the category itself, so
    # it becomes selectable when creating projects. (The generic/default template
    # is not a selectable category.)
    if name != family.template:
        category_service.upsert_category(db, category)

    tpl = repo.get_template_by_name(name)
    if tpl is None:
        label = _category_label(family, name)
        tpl = repo.create_template(
            PromptTemplate(
                name=name,
                category=label,
                description=f"{family.description} (book type: '{label}')",
                status=PromptStatus.ACTIVE,
                created_by=created_by,
            )
        )
        repo.create_variables(
            tpl.id,
            [
                PromptVariable(name=n, type=t, required=r)
                for n, t, r in family.variables
            ],
        )

    resolved_model = (model or "").strip() or _inherited_model(repo, family)
    versions = repo.get_versions(tpl.id)
    next_version = max((v.version for v in versions), default=0) + 1
    repo.create_version(
        PromptVersion(
            template_id=tpl.id,
            version=next_version,
            template_text=template_text,
            model=resolved_model,
            temperature=family.temperature,
            max_tokens=family.max_tokens,
            status=VersionStatus.DRAFT,
            created_by=created_by,
        )
    )
    repo.activate_version(tpl.id, next_version)
    return {
        "template": family.template,
        "category": _category_label(family, name),
        "active_version": next_version,
        "model": resolved_model,
        "guidance": (guidance or "").strip() or family.default_guidance.strip(),
    }


def preview(
    db: Session,
    category: Optional[str],
    guidance: str,
    template: Optional[str] = None,
) -> Dict[str, Any]:
    """Render the composed prompt with sample values — no LLM, no tokens spent."""
    family = get_family(template)
    composed = family.compose(guidance)
    rendered = (
        Environment(undefined=StrictUndefined)
        .from_string(composed)
        .render(**family.sample_vars)
    )
    return {
        "template": family.template,
        "category": _category_label(family, _template_name(family, category)),
        "rendered_prompt": rendered,
    }


def revert(
    db: Session, category: Optional[str], template: Optional[str] = None
) -> Dict[str, Any]:
    """Roll back to the previous version for a book type."""
    family = get_family(template)
    repo = PromptRepository(db)
    name = _template_name(family, category)
    label = _category_label(family, name)
    tpl = repo.get_template_by_name(name)
    if tpl is None:
        return {
            "template": family.template,
            "category": label,
            "active_version": None,
            "reverted": False,
        }

    versions = sorted(repo.get_versions(tpl.id), key=lambda v: v.version)
    if len(versions) < 2:
        return {
            "template": family.template,
            "category": label,
            "active_version": versions[-1].version if versions else None,
            "reverted": False,
        }
    previous = versions[-2].version
    repo.activate_version(tpl.id, previous)
    return {
        "template": family.template,
        "category": label,
        "active_version": previous,
        "reverted": True,
    }


def _inherited_model(repo: PromptRepository, family: PromptFamily) -> str:
    """Reuse the family's base model so the publisher never has to set one."""
    base = repo.get_template_by_name(family.template)
    active = repo.get_active_version(base.id) if base else None
    if active and active.model:
        return active.model
    return family.model or _DEFAULT_MODEL


# Composing now depends on which family is being edited; these keep the previous
# module-level helper names usable.
def compose_template(guidance: str, template: Optional[str] = None) -> str:
    return get_family(template).compose(guidance)


def extract_guidance(
    template_text: Optional[str], template: Optional[str] = None
) -> str:
    return get_family(template).extract(template_text)
