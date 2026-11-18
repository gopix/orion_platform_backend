"""PromptRenderer — turns a prompt version + variables into a RenderedPrompt.

Pure and small: its only job is (template text + variables) -> rendered text.
It does NOT load prompts, validate business rules, call the LLM, or persist
anything. It depends only on the domain models and Jinja2.

Rendering is *strict*: if the template references a variable the caller did not
provide, rendering fails immediately (rather than silently producing an
incomplete prompt), surfacing the problem early.
"""
from typing import Any, Dict, Optional

from jinja2 import Environment, StrictUndefined
from jinja2 import TemplateSyntaxError as JinjaTemplateSyntaxError
from jinja2 import UndefinedError as JinjaUndefinedError

from src.modules.book_forge.ai.foundation.prompts.models import PromptVersion, RenderedPrompt


class PromptRenderError(Exception):
    """Raised when a prompt template cannot be rendered (syntax or missing var)."""


class PromptRenderer:
    """Renders a ``PromptVersion``'s template text against input variables."""

    def __init__(self) -> None:
        # StrictUndefined => referencing an unprovided variable raises at render.
        self._env = Environment(undefined=StrictUndefined)

    def render(
        self, template: PromptVersion, variables: Optional[Dict[str, Any]] = None
    ) -> RenderedPrompt:
        """Render ``template`` with ``variables`` and return a RenderedPrompt."""
        variables = variables or {}

        # 1 + 2. Load the template text and compile the Jinja2 template.
        try:
            jinja_template = self._env.from_string(template.template_text)
        except JinjaTemplateSyntaxError as exc:
            raise PromptRenderError(
                f"Invalid template syntax (version {template.version}): {exc.message}"
            ) from exc

        # 3. Substitute variables (strict: missing ones raise).
        try:
            rendered_text = jinja_template.render(**variables)
        except JinjaUndefinedError as exc:
            raise PromptRenderError(
                f"Missing template variable while rendering version "
                f"{template.version}: {exc.message}"
            ) from exc

        # 4. Return a model (not a bare string) so we can evolve metadata later.
        return RenderedPrompt(
            template_id=template.template_id,
            version=template.version,
            rendered_text=rendered_text,
            variables_used=variables,
            token_estimate=None,  # populated later, outside the renderer
        )
