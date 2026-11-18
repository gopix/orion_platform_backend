"""PromptTemplateValidator — validates the template text itself.

Checks: empty template, invalid Jinja syntax, unsupported constructs
(``include`` / ``import`` / ``extends``), and duplicate placeholders (warning).
It only reports problems — it never edits the template.
"""
import re

from jinja2 import Environment, nodes
from jinja2 import TemplateSyntaxError as JinjaTemplateSyntaxError

from src.modules.book_forge.ai.foundation.prompts.validators.validation_result import (
    ValidationResult,
)

# Simple {{ name }} references, used to detect duplicates.
_PLACEHOLDER_RE = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")

# Jinja constructs BookForge does not permit in prompt templates.
_UNSUPPORTED = (
    (nodes.Include, "include"),
    (nodes.Import, "import"),
    (nodes.FromImport, "from-import"),
    (nodes.Extends, "extends"),
)


class PromptTemplateValidator:
    def __init__(self) -> None:
        self._env = Environment()

    def validate(self, template_text: str) -> ValidationResult:
        result = ValidationResult()

        if not template_text or not template_text.strip():
            result.add_error("Template is empty")
            return result

        try:
            ast = self._env.parse(template_text)
        except JinjaTemplateSyntaxError as exc:
            result.add_error(f"Invalid template syntax: {exc.message}")
            return result

        for node_type, label in _UNSUPPORTED:
            if next(ast.find_all(node_type), None) is not None:
                result.add_error(
                    f"Unsupported template construct: '{label}' is not allowed"
                )

        # Duplicate placeholders are not necessarily wrong -> warning only.
        seen: set = set()
        reported: set = set()
        for name in _PLACEHOLDER_RE.findall(template_text):
            if name in seen and name not in reported:
                result.add_warning(f'Placeholder "{name}" appears multiple times')
                reported.add(name)
            seen.add(name)

        return result
